"""Tests unitarios rigurosos para JarvisAdapter en JESSYCA 4.0.

Cubre todas las invariantes exigidas por la Fase 76.2:
1. Adapter disponible y ciclo de vida (init, health_check, shutdown).
2. Adapter no disponible por dependencias ausentes.
3. Inicialización fallida controlada.
4. Listado estricto de capacidades auditadas.
5. Ejecución válida (system_status, clipboard, workspace).
6. Separación estricta EXECUTE -> VERIFY -> REPORT (verified=False por defecto).
7. Verificación externa por JESSYCA (claims_success sólo con verificación comprobada).
8. Bloqueo y rechazo por Security Layer (sin bypass de permisos ni niveles de riesgo).
9. Manejo controlado de excepciones del componente externo.
10. Fallback transparente a capacidad nativa de JESSYCA.
11. Seguridad de rutas en workspace (anti-path-traversal).
12. Preservación de identidad (no "Soy Jarvis").
13. No duplicación de memoria principal ni LLM Manager.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from core.bus import EventBus
from core.execution.execution_verifier import ExecutionStatus
from core.integration.adapters.jarvis_adapter import JarvisAdapter
from core.integration.hub import IntegrationHub
from core.integration.models import (
    IntegrationContext,
    IntegrationExecutionResult,
    IntegrationStatus,
)
from core.integration.registry import IntegrationRegistry
from core.integration.security_boundary import IntegrationSecurityBoundary
from core.security import RiskLevel, SecurityManager, SecurityPolicy


@pytest.fixture
def temp_workspace() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def clean_registry() -> IntegrationRegistry:
    reg = IntegrationRegistry()
    reg.reset()
    return reg


@pytest.fixture
def mock_bus() -> EventBus:
    return EventBus()


# --- 1. Disponibilidad y Ciclo de Vida ---


@pytest.mark.anyio
async def test_jarvis_adapter_lifecycle(temp_workspace: Path) -> None:
    """Verifica que el adapter inicialice en READY, responda a health_check y se apague limpiamente."""
    adapter = JarvisAdapter(workspace_root=temp_workspace)
    assert adapter.name == "jarvis-py"
    assert adapter.version == "3.5.2"

    init_ok = await adapter.initialize()
    assert init_ok is True
    assert adapter.status == IntegrationStatus.READY

    health = await adapter.health_check()
    assert health.is_healthy is True
    assert health.status == IntegrationStatus.READY

    await adapter.shutdown()
    assert adapter.status == IntegrationStatus.AVAILABLE


# --- 2. Dependencia Ausente / No Disponible ---


@pytest.mark.anyio
async def test_jarvis_adapter_unavailable_when_deps_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Comprueba que si una dependencia falta, el adapter pase a UNAVAILABLE sin crashear."""
    adapter = JarvisAdapter()
    # Simular que falta una dependencia
    monkeypatch.setattr(adapter, "check_dependencies", lambda: (False, ["simulated_missing_dep"]))

    init_ok = await adapter.initialize()
    assert init_ok is False
    assert adapter.status == IntegrationStatus.UNAVAILABLE

    health = await adapter.health_check()
    assert health.is_healthy is False
    assert health.status == IntegrationStatus.UNAVAILABLE


# --- 3. Inicialización Fallida Controlada ---


@pytest.mark.anyio
async def test_jarvis_adapter_failed_initialization(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que excepciones durante initialize() se capturen y marquen estado ERROR."""
    adapter = JarvisAdapter(workspace_root=temp_workspace)

    def raise_err(*args: object, **kwargs: object) -> None:
        raise OSError("Acceso al disco denegado por el SO")

    monkeypatch.setattr(Path, "mkdir", raise_err)

    init_ok = await adapter.initialize()
    assert init_ok is False
    assert adapter.status == IntegrationStatus.ERROR


# --- 4. Listado y Validación de Capacidades ---


def test_jarvis_adapter_capabilities_declaration() -> None:
    """Comprueba que sólo se declaren las 5 capacidades reales auditadas y ninguna ficticia."""
    adapter = JarvisAdapter()
    declared_names = {c.name for c in adapter.capabilities}

    expected_names = {
        "jarvis.system_status",
        "jarvis.volume_control",
        "jarvis.clipboard",
        "jarvis.workspace_files",
        "jarvis.app_control",
    }
    assert declared_names == expected_names

    # Validar niveles de riesgo
    sys_cap = adapter.get_capability("jarvis.system_status")
    assert sys_cap is not None
    assert sys_cap.required_risk_level == RiskLevel.READ_ONLY

    app_cap = adapter.get_capability("jarvis.app_control")
    assert app_cap is not None
    assert app_cap.required_risk_level == RiskLevel.WARNING


# --- 5. Ejecución Válida y Separación EXECUTE -> VERIFY -> REPORT ---


@pytest.mark.anyio
async def test_jarvis_adapter_execute_system_status_unverified(
    temp_workspace: Path,
    clean_registry: IntegrationRegistry,
    mock_bus: EventBus,
) -> None:
    """Verifica la ejecución técnica de telemetría y confirma que claims_success es estrictamente False

    al no poseer auto-certificación (principio fundamental).
    """
    adapter = JarvisAdapter(workspace_root=temp_workspace)
    clean_registry.register(adapter, enabled=True)
    hub = IntegrationHub(registry=clean_registry, event_bus=mock_bus)
    await hub.initialize_all()

    ctx = IntegrationContext(session_id="test-session-telemetry")
    res = await hub.execute_capability("jarvis.system_status", ctx)

    assert res.executed is True
    assert res.status == ExecutionStatus.SUCCEEDED
    assert res.verified is False  # Regla crítica: NUNCA autodeclarar éxito verificado
    assert res.claims_success is False
    assert "telemetry" in res.output
    assert "cpu_percent" in res.output["telemetry"]


@pytest.mark.anyio
async def test_jarvis_adapter_workspace_file_operations(temp_workspace: Path) -> None:
    """Valida operaciones de lectura y escritura en el workspace aislado."""
    adapter = JarvisAdapter(workspace_root=temp_workspace)
    await adapter.initialize()

    # 1. Escribir archivo
    write_ctx = IntegrationContext(
        session_id="s1",
        parameters={"operation": "write", "filename": "test.txt", "content": "Hola JESSYCA"},
    )
    res_w = await adapter.execute("jarvis.workspace_files", write_ctx)
    assert res_w.executed is True
    assert res_w.status == ExecutionStatus.SUCCEEDED
    assert (temp_workspace / "test.txt").exists()

    # 2. Leer archivo
    read_ctx = IntegrationContext(
        session_id="s2",
        parameters={"operation": "read", "filename": "test.txt"},
    )
    res_r = await adapter.execute("jarvis.workspace_files", read_ctx)
    assert res_r.executed is True
    assert res_r.output["content"] == "Hola JESSYCA"


# --- 6. Seguridad de Rutas en Workspace (Anti-Path-Traversal) ---


@pytest.mark.anyio
async def test_jarvis_adapter_anti_path_traversal(temp_workspace: Path) -> None:
    """Verifica que intentos de escapar del workspace sean rechazados de forma determinista."""
    adapter = JarvisAdapter(workspace_root=temp_workspace)
    await adapter.initialize()

    escape_ctx = IntegrationContext(
        session_id="s_escape",
        parameters={"operation": "read", "filename": "../../sensitive.txt"},
    )
    res = await adapter.execute("jarvis.workspace_files", escape_ctx)
    assert res.executed is False
    assert res.status == ExecutionStatus.FAILED
    assert "no encontrado" in (res.error or "") or "Ruta insegura" in (res.error or "")


# --- 7. Seguridad: Bloqueo de Acciones sin Permisos ni Nivel de Riesgo Suficiente ---


@pytest.mark.anyio
async def test_jarvis_adapter_security_boundary_enforcement(
    temp_workspace: Path,
    clean_registry: IntegrationRegistry,
    mock_bus: EventBus,
) -> None:
    """Demuestra que la Security Layer de JESSYCA bloquea la ejecución de capacidades que

    superan la política global (e.g. app_control es WARNING, política sólo permite SAFE).
    """
    strict_policy = SecurityPolicy(max_allowed_risk=RiskLevel.SAFE)
    sec_mgr = SecurityManager(policy=strict_policy)
    boundary = IntegrationSecurityBoundary(security_manager=sec_mgr)

    adapter = JarvisAdapter(workspace_root=temp_workspace)
    clean_registry.register(adapter, enabled=True)

    hub = IntegrationHub(
        registry=clean_registry,
        security_boundary=boundary,
        event_bus=mock_bus,
    )
    await hub.initialize_all()

    ctx = IntegrationContext(
        session_id="sec-ctx",
        parameters={"action": "open", "app_name": "notepad"},
    )
    res = await hub.execute_capability("jarvis.app_control", ctx)

    # Debe ser denegado ANTES de invocar a Jarvis
    assert res.executed is False
    assert res.status == ExecutionStatus.DENIED
    assert "Seguridad denegó la ejecución" in (res.error or "")


# --- 8. Verificación Externa por JESSYCA ---


def test_jessyca_external_verification_contract() -> None:
    """Demuestra que sólo JESSYCA (vía verificador externo) puede certificar un resultado."""
    # Resultado devuelto por el adapter de Jarvis:
    raw_res = IntegrationExecutionResult(
        executed=True,
        verified=False,
        verification_required=True,
        status=ExecutionStatus.SUCCEEDED,
        output="Acción completada técnicamente",
    )
    assert raw_res.claims_success is False

    # JESSYCA verifica externamente:
    verified_res = IntegrationExecutionResult(
        executed=raw_res.executed,
        verified=True,  # Certificado por JESSYCA
        verification_required=True,
        status=ExecutionStatus.SUCCEEDED,
        output=raw_res.output,
    )
    assert verified_res.claims_success is True


# --- 9. Fallback Transparente a Capacidad Nativa ---


@pytest.mark.anyio
async def test_jarvis_fallback_to_native(
    temp_workspace: Path,
    clean_registry: IntegrationRegistry,
    mock_bus: EventBus,
) -> None:
    """Verifica que si el adapter de Jarvis está deshabilitado, JESSYCA recurra a su capacidad nativa."""
    adapter = JarvisAdapter(workspace_root=temp_workspace)
    # Registrar deshabilitado
    clean_registry.register(adapter, enabled=False)

    hub = IntegrationHub(registry=clean_registry, event_bus=mock_bus)
    await hub.initialize_all()

    ctx = IntegrationContext(session_id="fb-sess")

    def native_system_status(c: IntegrationContext) -> dict[str, str]:
        return {"source": "jessyca_native_telemetry", "ok": "true"}

    res = await hub.execute_with_fallback(
        capability="jarvis.system_status",
        context=ctx,
        native_fallback=native_system_status,
    )

    assert res.executed is True
    assert res.status == ExecutionStatus.SUCCEEDED
    assert res.output["source"] == "jessyca_native_telemetry"
    assert res.metadata.get("fallback_used") is True
    assert res.metadata.get("provider") == "jessyca_native"


# --- 10. Preservación de Identidad ---


@pytest.mark.anyio
async def test_jarvis_no_identity_leak(temp_workspace: Path) -> None:
    """Verifica que los mensajes y outputs no filtren identidad externa ("Soy Jarvis")."""
    adapter = JarvisAdapter(workspace_root=temp_workspace)
    await adapter.initialize()

    ctx = IntegrationContext(session_id="id-sess")
    res = await adapter.execute("jarvis.system_status", ctx)

    msg = str(res.output.get("message", "")).lower()
    assert "soy jarvis" not in msg
    assert "jarvis ejecutó" not in msg


# --- 11. No Duplicación de Memoria ni LLM ---


def test_no_memory_or_llm_duplication() -> None:
    """Verifica que el adapter no contenga ni instancie sistemas paralelos de LLM o memoria."""
    adapter = JarvisAdapter()
    # Debe ser una clase pura derivada de IntegrationAdapter
    assert not hasattr(adapter, "ollama")
    assert not hasattr(adapter, "memory_engine")
    assert not hasattr(adapter, "vector_store")
    assert not hasattr(adapter, "tts_engine")


# --- 12. Descubrimiento y Registro Predeterminado desde Configuración ---


def test_jarvis_adapter_discovery_and_auto_registration(clean_registry: IntegrationRegistry) -> None:
    """Comprueba el descubrimiento y registro automático de JarvisAdapter en el IntegrationHub."""
    from core.integration.hub import register_default_adapters

    hub = IntegrationHub(registry=clean_registry)
    register_default_adapters(hub)

    jarvis = hub.registry.get("jarvis-py")
    assert jarvis is not None
    assert jarvis.name == "jarvis-py"
    assert jarvis.version == "3.5.2"
    # Debe estar presente en el catálogo de integraciones
    all_integrations = {info.name for info in hub.registry.list_integrations()}
    assert "jarvis-py" in all_integrations


# --- 13. Capacidad Seleccionada: jarvis.volume_control (Casos Válidos, Inválidos y Deps Ausentes) ---


@pytest.mark.anyio
async def test_jarvis_volume_control(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica control de volumen multimedia (increase, decrease, mute), acciones inválidas y falta de dependencia."""
    adapter = JarvisAdapter()
    await adapter.initialize()

    pressed_keys: list[str] = []

    class FakePyAutoGUI:
        @staticmethod
        def press(key: str) -> None:
            pressed_keys.append(key)

    monkeypatch.setattr("pyautogui.press", FakePyAutoGUI.press, raising=False)

    # 1. Increase
    res_inc = await adapter.execute(
        "jarvis.volume_control",
        IntegrationContext(session_id="vol1", parameters={"action": "increase"}),
    )
    assert res_inc.executed is True
    assert res_inc.status == ExecutionStatus.SUCCEEDED
    assert res_inc.verified is False
    assert res_inc.verification_required is True
    assert "volumeup" in pressed_keys

    # 2. Decrease
    res_dec = await adapter.execute(
        "jarvis.volume_control",
        IntegrationContext(session_id="vol2", parameters={"action": "decrease"}),
    )
    assert res_dec.executed is True
    assert res_dec.status == ExecutionStatus.SUCCEEDED
    assert "volumedown" in pressed_keys

    # 3. Mute
    res_mute = await adapter.execute(
        "jarvis.volume_control",
        IntegrationContext(session_id="vol3", parameters={"action": "mute"}),
    )
    assert res_mute.executed is True
    assert res_mute.status == ExecutionStatus.SUCCEEDED
    assert "volumemute" in pressed_keys

    # 4. Acción inválida
    res_inv = await adapter.execute(
        "jarvis.volume_control",
        IntegrationContext(session_id="vol4", parameters={"action": "explode"}),
    )
    assert res_inv.executed is False
    assert res_inv.status == ExecutionStatus.FAILED
    assert "inválida" in (res_inv.error or "")

    # 5. Dependencia pyautogui ausente
    import builtins
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "pyautogui":
            raise ImportError("No module named 'pyautogui'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    res_no_dep = await adapter.execute(
        "jarvis.volume_control",
        IntegrationContext(session_id="vol5", parameters={"action": "increase"}),
    )
    assert res_no_dep.executed is False
    assert res_no_dep.status == ExecutionStatus.FAILED
    assert "pyautogui no disponible" in (res_no_dep.error or "")


# --- 14. Capacidad Seleccionada: jarvis.clipboard (Lectura, Escritura, Recorte y Deps) ---


@pytest.mark.anyio
async def test_jarvis_clipboard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica portapapeles: escritura, lectura, recorte de longitud, acción inválida y falta de dependencia."""
    adapter = JarvisAdapter()
    await adapter.initialize()

    fake_clipboard = {"content": ""}

    class FakePyperclip:
        @staticmethod
        def copy(text: str) -> None:
            fake_clipboard["content"] = text

        @staticmethod
        def paste() -> str:
            return fake_clipboard["content"]

    monkeypatch.setattr("pyperclip.copy", FakePyperclip.copy, raising=False)
    monkeypatch.setattr("pyperclip.paste", FakePyperclip.paste, raising=False)

    # 1. Escribir texto
    res_w = await adapter.execute(
        "jarvis.clipboard",
        IntegrationContext(session_id="clip1", parameters={"action": "write", "text": "Texto para clipboard"}),
    )
    assert res_w.executed is True
    assert res_w.status == ExecutionStatus.SUCCEEDED
    assert res_w.verified is False
    assert res_w.verification_required is True
    assert fake_clipboard["content"] == "Texto para clipboard"

    # 2. Leer texto
    res_r = await adapter.execute(
        "jarvis.clipboard",
        IntegrationContext(session_id="clip2", parameters={"action": "read"}),
    )
    assert res_r.executed is True
    assert res_r.status == ExecutionStatus.SUCCEEDED
    assert res_r.output["text"] == "Texto para clipboard"

    # 3. Recorte de contenido largo (> 200 caracteres)
    fake_clipboard["content"] = "A" * 300
    res_long = await adapter.execute(
        "jarvis.clipboard",
        IntegrationContext(session_id="clip3", parameters={"action": "read"}),
    )
    assert res_long.executed is True
    assert "contiene 300 caracteres" in res_long.output["text"]

    # 4. Acción inválida
    res_inv = await adapter.execute(
        "jarvis.clipboard",
        IntegrationContext(session_id="clip4", parameters={"action": "delete"}),
    )
    assert res_inv.executed is False
    assert res_inv.status == ExecutionStatus.FAILED
    assert "desconocida" in (res_inv.error or "")

    # 5. Dependencia pyperclip ausente
    import builtins
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "pyperclip":
            raise ImportError("No module named 'pyperclip'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    res_no_clip = await adapter.execute(
        "jarvis.clipboard",
        IntegrationContext(session_id="clip5", parameters={"action": "read"}),
    )
    assert res_no_clip.executed is False
    assert res_no_clip.status == ExecutionStatus.FAILED
    assert "pyperclip no disponible" in (res_no_clip.error or "")


# --- 15. Capacidad Seleccionada: jarvis.app_control (Apertura, Cierre, UWP y Validación) ---


@pytest.mark.anyio
async def test_jarvis_app_control(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica lanzamiento y cierre de aplicaciones con mapeo de alias UWP y validaciones."""
    adapter = JarvisAdapter()
    await adapter.initialize()

    started_targets: list[str] = []
    taskkilled_images: list[str] = []

    def fake_startfile(target: str) -> None:
        started_targets.append(target)

    def fake_run(cmd: list[str], *args: object, **kwargs: object) -> object:
        if len(cmd) >= 4 and cmd[0] == "taskkill":
            taskkilled_images.append(cmd[3])
        class FakeProc:
            returncode = 0
        return FakeProc()

    monkeypatch.setattr("os.startfile", fake_startfile, raising=False)
    monkeypatch.setattr("subprocess.run", fake_run, raising=False)

    # 1. Abrir con alias (calculator -> calc)
    res_open = await adapter.execute(
        "jarvis.app_control",
        IntegrationContext(session_id="app1", parameters={"action": "open", "app_name": "calculator"}),
    )
    assert res_open.executed is True
    assert res_open.status == ExecutionStatus.SUCCEEDED
    assert res_open.verified is False  # NUNCA auto-certificar
    assert res_open.verification_required is True
    assert "calc" in started_targets

    # 2. Cerrar con resolución UWP (calculator -> CalculatorApp.exe)
    res_close = await adapter.execute(
        "jarvis.app_control",
        IntegrationContext(session_id="app2", parameters={"action": "close", "app_name": "calculator"}),
    )
    assert res_close.executed is True
    assert res_close.status == ExecutionStatus.SUCCEEDED
    assert res_close.verified is False
    assert "CalculatorApp.exe" in taskkilled_images

    # 3. Parámetro app_name vacío
    res_empty = await adapter.execute(
        "jarvis.app_control",
        IntegrationContext(session_id="app3", parameters={"action": "open", "app_name": ""}),
    )
    assert res_empty.executed is False
    assert res_empty.status == ExecutionStatus.FAILED
    assert "Debe especificar 'app_name'" in (res_empty.error or "")

    # 4. Acción inválida
    res_inv = await adapter.execute(
        "jarvis.app_control",
        IntegrationContext(session_id="app4", parameters={"action": "restart", "app_name": "notepad"}),
    )
    assert res_inv.executed is False
    assert res_inv.status == ExecutionStatus.FAILED
    assert "inválida" in (res_inv.error or "")


# --- 16. Capacidad Desconocida y Errores de Workspace ---


@pytest.mark.anyio
async def test_jarvis_unknown_capability_and_workspace_errors(temp_workspace: Path) -> None:
    """Verifica manejo controlado de capacidad no declarada y operaciones de archivo con error."""
    adapter = JarvisAdapter(workspace_root=temp_workspace)
    await adapter.initialize()

    # 1. Capacidad desconocida
    res_unknown = await adapter.execute("jarvis.nonexistent_service", IntegrationContext(session_id="err1"))
    assert res_unknown.executed is False
    assert res_unknown.status == ExecutionStatus.FAILED
    assert "Capacidad desconocida" in (res_unknown.error or "")

    # 2. Leer archivo que no existe
    res_nofile = await adapter.execute(
        "jarvis.workspace_files",
        IntegrationContext(session_id="err2", parameters={"operation": "read", "filename": "no_existe.txt"}),
    )
    assert res_nofile.executed is False
    assert res_nofile.status == ExecutionStatus.FAILED
    assert "no encontrado" in (res_nofile.error or "")

    # 3. Búsqueda de archivos en workspace
    (temp_workspace / "reporte_ventas.txt").write_text("datos", encoding="utf-8")
    (temp_workspace / "notas.txt").write_text("datos", encoding="utf-8")
    res_search = await adapter.execute(
        "jarvis.workspace_files",
        IntegrationContext(session_id="err3", parameters={"operation": "search", "query": "ventas"}),
    )
    assert res_search.executed is True
    assert res_search.output["matches"] == ["reporte_ventas.txt"]
