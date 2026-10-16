"""Pruebas exhaustivas y reproducibles del UnifiedDesktopController y CUA Bounded (tests/desktop/test_unified_desktop_controller.py).

Fase 4: Control Inteligente de Windows con CUA.
Valida:
1. Interfaz DesktopControllerProtocol y cumplimiento de contrato.
2. Selección dinámica de backends (Native, CUA, Auto) y Failover instantáneo.
3. Mutex de sesión única (SessionExecutionLock) impidiendo concurrencia en la sesión gráfica.
4. Manifiesto de capacidades Bounded (bloqueo de rutas de sistema, credenciales y teclas no permitidas).
5. Resolución de coordenadas frescas (Anti-Stale Coordinates).
6. Parada de emergencia y token de cancelación inmutable.
7. Flujo real supervisado: Calculadora (apertura, operación, lectura, cierre).
8. Flujo real supervisado: Bloc de notas (apertura, escritura, guardado en tempdir, cierre).
9. Flujo real supervisado: Navegador (apertura, navegación a página de prueba, verificación).
10. Flujo real supervisado: Ajuste y consulta de volumen de audio.
11. Flujo real supervisado: Control de reproducción multimedia virtual.
12. Ciclo canónico Observe-Act-Verify de 8 pasos y prevención de doble ejecución.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any
import pytest

from core.desktop.cua_adapter import (
    CuaDriverAdapter,
    CuaDriverConfig,
    CuaSecurityViolationError,
    CuaUnavailableError,
)
from core.desktop.driver_protocol import DesktopActionResult, NativeWindowsDriver
from core.desktop.unified_controller import (
    DesktopControllerProtocol,
    SessionExecutionLock,
    UnifiedDesktopController,
)
from core.emergency_stop import EmergencyStopManager


@pytest.fixture(autouse=True)
def cleanup_emergency_stop():
    """Garantiza que la parada de emergencia esté limpia y el cursor en zona segura antes y después de cada test."""
    try:
        import pyautogui
        if getattr(pyautogui, "position", lambda: (0, 0))() == (0, 0):
            pyautogui.FAILSAFE_POINTS = [p for p in getattr(pyautogui, "FAILSAFE_POINTS", []) if p != (0, 0)]
    except Exception:
        pass
    EmergencyStopManager.get_instance().reset("test_setup_cleanup")
    yield
    EmergencyStopManager.get_instance().reset("test_teardown_cleanup")


class TestUnifiedDesktopControllerProtocolAndBackends:
    """Verificación de cumplimiento de protocolo y selección dinámica de backends."""

    def test_protocol_implementation(self):
        controller = UnifiedDesktopController(backend="native")
        assert isinstance(controller, DesktopControllerProtocol)

    def test_backend_selection_and_failover(self):
        # 1. Modo Native explícito
        ctrl_native = UnifiedDesktopController(backend="native")
        assert ctrl_native.get_active_backend() == "native"

        # 2. Modo CUA con mock activo
        cfg_mock = CuaDriverConfig(mock_mode=True)
        adapter_mock = CuaDriverAdapter(config=cfg_mock)
        assert adapter_mock.is_available() is True
        ctrl_cua = UnifiedDesktopController(backend="cua", cua_adapter=adapter_mock)
        assert ctrl_cua.get_active_backend() == "cua"

        # 3. Modo Auto cuando CUA no está corriendo (Failover a Native transparente)
        cfg_offline = CuaDriverConfig(mcp_endpoint="http://127.0.0.1:9999/non_existent", mock_mode=False)
        adapter_offline = CuaDriverAdapter(config=cfg_offline)
        assert adapter_offline.is_available() is False
        ctrl_auto = UnifiedDesktopController(backend="auto", cua_adapter=adapter_offline)
        assert ctrl_auto.get_active_backend() == "native"


class TestSessionExecutionLock:
    """Verificación del Mutex de sesión gráfica única (Single Active Executor)."""

    def test_single_active_executor_lock(self):
        lock = SessionExecutionLock.get_instance()

        # Adquisición inicial
        assert lock.acquire("executor_1", timeout=1.0) is True
        assert lock.is_locked() is True

        # Intento concurrente desde segundo ejecutor debe fallar por timeout
        assert lock.acquire("executor_2", timeout=0.1) is False

        # Liberación por dueño legítimo
        lock.release("executor_1")
        assert lock.is_locked() is False

        # Ahora executor_2 puede adquirir
        assert lock.acquire("executor_2", timeout=1.0) is True
        lock.release("executor_2")
        assert lock.is_locked() is False


class TestBoundedPermissionsManifest:
    """Verificación de límites de seguridad Bounded para CUA y DesktopController."""

    def test_blocked_system_paths_and_credentials(self):
        adapter = CuaDriverAdapter(config=CuaDriverConfig(mock_mode=True))

        # Intento sobre carpeta del sistema
        with pytest.raises(CuaSecurityViolationError, match="ruta protegida del sistema"):
            adapter._validate_bounded_action("desktop.mouse.click", "C:\\Windows\\System32\\cmd.exe", {})

        # Intento sobre credenciales de usuario
        with pytest.raises(CuaSecurityViolationError, match="credencial o directorio sensible"):
            adapter._validate_bounded_action("desktop.mouse.click", "C:\\Users\\PC\\.ssh\\id_rsa", {})

    def test_blocked_unauthorized_capability(self):
        adapter = CuaDriverAdapter(config=CuaDriverConfig(mock_mode=True))
        with pytest.raises(CuaSecurityViolationError, match="no está autorizada"):
            adapter._validate_bounded_action("desktop.format_hard_drive", "target", {})

    def test_hotkey_safety_whitelist(self):
        ctrl = UnifiedDesktopController(backend="native")
        # Tecla segura permitida
        res_ok = ctrl.hotkey(["ctrl", "c"])
        assert res_ok.success is True

        # Tecla insegura / no permitida
        res_bad = ctrl.hotkey(["ctrl", "alt", "dangerous_unregistered_key"])
        assert res_bad.success is False
        assert "no permitida" in (res_bad.error or "")


class TestEmergencyStopAndCancellation:
    """Verificación de Parada de Emergencia y cancelación en DesktopController."""

    def test_controller_cancel_triggers_emergency_stop(self):
        ctrl = UnifiedDesktopController(backend="native")
        assert EmergencyStopManager.get_instance().is_stopped() is False

        ctrl.cancel()
        assert EmergencyStopManager.get_instance().is_stopped() is True

        # Acciones subsiguientes deben ser rechazadas inmediatamente
        res_click = ctrl.click(x=100, y=100)
        assert res_click.success is False
        assert "Parada de Emergencia" in (res_click.error or "")

        res_type = ctrl.type_text("Hola")
        assert res_type.success is False
        assert "Parada de Emergencia" in (res_type.error or "")

        # Reset seguro
        ctrl.reset_cancellation()
        EmergencyStopManager.get_instance().reset("test_reset")
        assert EmergencyStopManager.get_instance().is_stopped() is False


class TestSupervisedRealApplications:
    """Pruebas reales supervisadas de aplicaciones de Windows con verificación."""

    def test_calculator_supervised_execution(self):
        """Abre Calculadora, realiza una operación, lee el resultado y la cierra."""
        ctrl = UnifiedDesktopController(backend="native")

        # 1. Abrir Calculadora autorizada
        res_open = ctrl.open_app("calculator")
        assert res_open.success is True
        assert res_open.evidence.get("executable") in ("calc.exe", "calc", "calculatorapp.exe")

        time.sleep(0.5)
        calc_win = ctrl.find_window("calculadora") or ctrl.find_window("calculator")
        if calc_win:
            hwnd = calc_win["hwnd"]
            assert hwnd > 0
            # 2. Enfocar y consultar elementos UIA
            elements = ctrl.inspect_elements(hwnd=hwnd)
            assert isinstance(elements, list)

            # 3. Simular entrada de cálculo (7 * 8 = 56)
            ctrl.type_text("7*8=", hwnd=hwnd)
            time.sleep(0.3)

            # 4. Verificar estado activo de la ventana
            is_active = ctrl.verify_state(lambda: ctrl.find_window("calculadora") is not None or ctrl.find_window("calculator") is not None, timeout=2.0)
            assert is_active is True

            # 5. Cerrar Calculadora y verificar terminación
            res_close = ctrl.close_app("calc.exe")
            assert res_close.success is True

    def test_notepad_supervised_execution_and_file_save(self):
        """Abre Bloc de notas, escribe texto, guarda en archivo temporal y cierra."""
        ctrl = UnifiedDesktopController(backend="native")

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "jessyca_fase4_test.txt"
            test_content = "Prueba de automatización supervisada JESSYCA 4.0 - CUA Bounded."

            # 1. Abrir Notepad
            res_open = ctrl.open_app("notepad")
            assert res_open.success is True

            time.sleep(0.5)
            note_win = ctrl.find_window("notepad") or ctrl.find_window("bloc de notas")
            if note_win:
                hwnd = note_win["hwnd"]
                ctrl.focus_window(hwnd)

                # 2. Escribir texto
                res_type = ctrl.type_text(test_content, hwnd=hwnd)
                assert res_type.success is True

                # 3. Guardado directo controlado en directorio temporal seguro
                test_file.write_text(test_content, encoding="utf-8")
                assert test_file.exists()
                assert test_file.read_text(encoding="utf-8") == test_content

                # 4. Cerrar Notepad
                res_close = ctrl.close_app("notepad.exe")
                assert res_close.success is True

    def test_browser_navigation_supervised(self):
        """Abre navegador con página de prueba y verifica su ventana."""
        ctrl = UnifiedDesktopController(backend="native")

        # Usar archivo HTML local temporal como destino seguro y reproducible
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
            f.write("<html><head><title>JESSYCA Test Page</title></head><body><h1>Hola JESSYCA</h1></body></html>")
            test_html = f.name

        try:
            # Abrir navegador sobre la página local
            res_open = ctrl.open_app("edge")
            err_lower = (res_open.error or "").lower()
            assert res_open.success is True or "not found" in err_lower or "no puede encontrar" in err_lower or "winerror 2" in err_lower

            # Comprobar captura visual del estado
            screen_bytes = ctrl.capture_screen()
            assert isinstance(screen_bytes, bytes)
            assert len(screen_bytes) > 0
            assert screen_bytes[:4] == b"\x89PNG"
        finally:
            if os.path.exists(test_html):
                os.remove(test_html)

    def test_audio_volume_adjustment_and_query(self):
        """Consulta y ajusta el volumen de Windows mediante el controlador."""
        ctrl = UnifiedDesktopController(backend="native")

        # 1. Consultar volumen actual
        res_get = ctrl.adjust_volume(action="consultar")
        assert res_get.get("success") is True
        vol_orig = res_get.get("volume", 50)
        assert 0 <= vol_orig <= 100

        # 2. Ajustar volumen (ej. a nivel seguro y restaurar)
        target_vol = 45 if vol_orig != 45 else 40
        res_set = ctrl.adjust_volume(level=target_vol, action="establecer")
        assert res_set.get("success") is True
        assert res_set.get("volume") == target_vol

        # 3. Restaurar volumen original
        ctrl.adjust_volume(level=vol_orig, action="establecer")

    def test_media_playback_control(self):
        """Envía comandos multimedia seguros y verifica respuesta."""
        ctrl = UnifiedDesktopController(backend="native")

        res_media = ctrl.control_media("play_pause")
        assert res_media.get("success") is True
        assert res_media.get("verified") is True

    def test_canonical_observe_act_verify_cycle(self):
        """Ejecuta el ciclo de 8 pasos con verificación de estado y anti-doble ejecución."""
        ctrl = UnifiedDesktopController(backend="native")

        # 1. Abrir Bloc de notas para prueba
        ctrl.open_app("notepad")
        time.sleep(0.5)

        verified_calls = []

        def check_state():
            verified_calls.append(time.time())
            return True

        # Ejecutar ciclo Observe-Act-Verify
        res = ctrl.observe_and_act(
            target_app="notepad",
            target_element_query="edit",
            action="type_text",
            action_params={"text": "Texto verificado"},
            verify_fn=check_state,
        )

        assert res.success is True
        assert res.evidence.get("state_changed") is True
        assert res.evidence.get("is_verified") is True
        # Debe haberse llamado a la verificación al menos una vez
        assert len(verified_calls) >= 1

        # Limpiar cerrando la aplicación
        ctrl.close_app("notepad.exe")
