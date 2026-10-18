"""Pruebas de Integración y Ejecución Real en Windows 11 y CUA Driver (tests/cognitive_brain/test_cua_windows_execution.py).

Valida de forma exhaustiva y determinista:
1. Seguridad Bounded de CuaDriverAdapter y protección de rutas críticas.
2. Exclusión mutua de hardware gráfico con SessionExecutionLock.
3. Ejecución real sobre Windows 11:
   - Apertura y cierre de Calculadora con verificación de PID.
   - Apertura y cierre de Bloc de notas con escritura de texto.
   - Captura de pantalla real en formato PNG.
   - Ajuste y consulta física de volumen de Windows (PyCaw).
4. Ciclo E2E completo en JessycaBrain con USE_JESSYCA_BRAIN=True (controlado):
   Usuario -> ReasoningEngine -> MemoryEngine -> PlannerEngine -> RiskEngine -> UnifiedDesktopController -> MemoryEngine.
5. Parada de emergencia y cancelación reactiva.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
import pytest

from core.cancellation import CancellationToken
from core.cognitive_brain.brain_orchestrator import JessycaBrain
from core.cognitive_brain.contracts import PlanStepExecutionState
from core.cognitive_brain.memory_engine import MemoryEngine
from core.cognitive_brain.planner_engine import PlannerEngine
from core.cognitive_brain.reasoning_engine import ReasoningEngine
from core.desktop.cua_adapter import (
    CuaDriverAdapter,
    CuaDriverConfig,
    CuaSecurityViolationError,
    CuaUnavailableError,
)
from core.desktop.unified_controller import (
    SessionExecutionLock,
    UnifiedDesktopController,
)
from core.emergency_stop import EmergencyStopManager


@pytest.fixture(autouse=True)
def ensure_emergency_stop_clean():
    """Asegura que el sistema no tenga parada de emergencia activa antes y después del test."""
    esm = EmergencyStopManager.get_instance()
    esm.reset()
    yield
    esm.reset()


# =========================================================================
# 1. SEGURIDAD Y CONTRATOS DE CUA DRIVER BOUNDED
# =========================================================================

def test_cua_adapter_bounded_security():
    """Valida que CUA Driver aplique estrictamente el modelo Bounded y bloquee rutas protegidas."""
    adapter = CuaDriverAdapter()

    # 1. Comprobar versión y modo
    assert adapter.manifest.get("mode") == "bounded"
    assert adapter.manifest.get("allow_unrestricted") is False

    # 2. Bloqueo de rutas protegidas del sistema
    with pytest.raises(CuaSecurityViolationError) as exc_sys:
        adapter._validate_bounded_action(
            capability="desktop.mouse.click",
            target="C:\\Windows\\System32\\cmd.exe",
            payload={},
        )
    assert "ruta protegida" in str(exc_sys.value).lower()

    # 3. Bloqueo de capacidades no autorizadas
    with pytest.raises(CuaSecurityViolationError) as exc_cap:
        adapter._validate_bounded_action(
            capability="unrestricted_shell_exec",
            target="calc.exe",
            payload={},
        )
    assert "no está autorizada" in str(exc_cap.value).lower()

    # 4. Bloqueo si Parada de Emergencia está activa
    EmergencyStopManager.get_instance().trigger_stop("Prueba de seguridad CUA", source="test")
    with pytest.raises(RuntimeError) as exc_stop:
        adapter._validate_bounded_action(
            capability="desktop.mouse.click",
            target="calc.exe",
            payload={},
        )
    assert "parada de emergencia" in str(exc_stop.value).lower()
    EmergencyStopManager.get_instance().reset()


def test_session_execution_lock_mutex():
    """Valida que SessionExecutionLock impida el uso concurrente del mouse y teclado por dos drivers."""
    lock = SessionExecutionLock.get_instance()

    # Propietario 1 obtiene lock
    assert lock.acquire(owner_id="driver_native", timeout=1.0) is True
    assert lock.is_locked() is True

    # Propietario 2 (CUA u otro hilo) intenta obtenerlo y es rechazado
    assert lock.acquire(owner_id="driver_cua", timeout=0.1) is False

    # Liberación por propietario legítimo
    lock.release(owner_id="driver_native")
    assert lock.is_locked() is False

    # Ahora propietario 2 puede adquirirlo
    assert lock.acquire(owner_id="driver_cua", timeout=1.0) is True
    lock.release(owner_id="driver_cua")


# =========================================================================
# 2. PRUEBAS FÍSICAS SOBRE WINDOWS 11 (UNIFIED DESKTOP CONTROLLER)
# =========================================================================

def test_real_windows_screen_capture():
    """Valida la captura física de pantalla de Windows en formato PNG."""
    controller = UnifiedDesktopController()
    png_bytes = controller.capture_screen()
    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 50
    # Cabecera mágica de archivo PNG: \x89PNG\r\n\x1a\n
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_real_windows_volume_control():
    """Valida la consulta y ajuste de volumen físico de Windows mediante PyCaw."""
    controller = UnifiedDesktopController()

    # Consulta de volumen
    query_res = controller.adjust_volume(action="consultar")
    if query_res.get("success"):
        assert "volume" in query_res
        assert 0 <= query_res["volume"] <= 100

        # Ajuste controlado de volumen
        orig_vol = query_res["volume"]
        target_vol = 35 if orig_vol != 35 else 40
        set_res = controller.adjust_volume(level=target_vol, action="establecer")
        assert set_res.get("success") is True
        assert set_res.get("volume") == target_vol

        # Restaurar volumen original
        controller.adjust_volume(level=orig_vol, action="establecer")
    else:
        # En caso de entornos de prueba virtualizados sin tarjeta de audio activa
        assert "error" in query_res


def test_real_windows_calculator_physical_lifecycle():
    """Valida el ciclo de vida completo de la Calculadora de Windows (Abrir -> Detectar -> Cerrar)."""
    controller = UnifiedDesktopController()

    # 1. Abrir Calculadora
    open_res = controller.open_app("calculator")
    assert open_res.success is True, f"Error abriendo calculadora: {open_res.error}"
    assert open_res.evidence.get("pid") is not None

    pid = open_res.evidence["pid"]
    time.sleep(1.0)

    # 2. Detectar ventana o proceso en ejecución
    win = controller.find_window("calculator") or controller.find_window("calc")
    assert win is not None or any("calc" in app["name"].lower() for app in controller.enumerate_apps())

    # 3. Cerrar Calculadora
    close_res = controller.close_app(pid)
    assert close_res.success is True
    assert close_res.evidence.get("is_verified") is True


def test_real_windows_notepad_physical_lifecycle():
    """Valida el ciclo de vida de Bloc de notas (Abrir -> Escribir -> Cerrar)."""
    controller = UnifiedDesktopController()

    # 1. Abrir Notepad
    open_res = controller.open_app("notepad")
    assert open_res.success is True, f"Error abriendo bloc de notas: {open_res.error}"
    pid = open_res.evidence["pid"]
    time.sleep(0.5)

    # 2. Escribir texto seguro
    type_res = controller.type_text("JESSYCA BRAIN 1.0 — Test de ejecucion real Windows 11.")
    assert type_res.success is True

    # 3. Cerrar Notepad
    close_res = controller.close_app(pid)
    assert close_res.success is True
    assert close_res.evidence.get("is_verified") is True


# =========================================================================
# 3. INTEGRACIÓN E2E DE JESSYCA BRAIN CON CONTROL REAL DE WINDOWS
# =========================================================================

def test_jessyca_brain_e2e_real_execution_calculator():
    """Valida el ciclo cognitivo completo con ejecución física real en Calculadora de Windows."""
    memory_engine = MemoryEngine.get_instance()
    controller = UnifiedDesktopController()
    brain = JessycaBrain(
        memory_engine=memory_engine,
        desktop_controller=controller,
    )

    user_input = "Abre la calculadora y calcula una operacion"
    res = brain.process_request(user_input, session_id="test_session_cua")

    assert res.success is True
    assert res.requires_action is True
    assert res.steps_total >= 1
    assert res.steps_executed >= 1
    assert "calculadora" in res.response_text.lower() or "operación" in res.response_text.lower()

    # Limpiar proceso de prueba
    time.sleep(0.3)
    controller.close_app("calc.exe")


def test_jessyca_brain_e2e_multi_step_compound_real_document():
    """Valida una instrucción de varios pasos con generación física de archivo en scratch/ y captura."""
    controller = UnifiedDesktopController()
    brain = JessycaBrain(
        desktop_controller=controller,
    )

    # Tarea compuesta: Generar informe y capturar pantalla
    user_input = "Investiga sobre computación cuántica y genera un reporte en resumen.txt"
    res = brain.process_request(user_input, session_id="test_compound_session")

    assert res.success is True
    assert res.requires_action is True
    assert res.steps_executed == res.steps_total

    # Verificar que el archivo físico fue creado en scratch/
    out_file = Path("scratch") / "resumen.txt"
    assert out_file.exists()
    assert out_file.stat().st_size > 0
    content = out_file.read_text(encoding="utf-8")
    assert "Jessyca Brain" in content or "resumen" in content.lower()


def test_jessyca_brain_emergency_stop_real_abort():
    """Valida que la parada de emergencia aborte la ejecución de forma inmediata e independiente."""
    esm = EmergencyStopManager.get_instance()
    esm.trigger_stop("Aborto preventivo de prueba", source="unit_test")

    controller = UnifiedDesktopController()
    brain = JessycaBrain(desktop_controller=controller)

    res = brain.process_request("Abre el bloc de notas", session_id="test_stop")
    assert res.success is False
    assert res.error == "EmergencyStopActive"
    assert "parada de emergencia" in res.response_text.lower()

    esm.reset()


def test_jessyca_brain_cancellation_token_abort():
    """Valida que un CancellationToken cancelado aborte la ejecución antes de interactuar físicamente."""
    token = CancellationToken()
    token.cancel()

    controller = UnifiedDesktopController()
    brain = JessycaBrain(desktop_controller=controller)

    res = brain.process_request("Abre la calculadora", session_id="test_token", cancellation_token=token)
    assert res.success is False
    assert res.error in ("ExecutionCancelledByUser", "TaskCancelledByUser")
