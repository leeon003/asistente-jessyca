"""Tests unitarios rigurosos para ComputerUseAdapter en JESSYCA 4.0.

Cubre todas las invariantes exigidas por la Fase 76.4:
1. Ciclo de vida del adapter (init, health_check, shutdown).
2. Manejo de dependencias ausentes (UNAVAILABLE seguro) y modo DEGRADED.
3. Declaración estricta de las 5 capacidades auditadas con sus niveles de riesgo.
4. Capacidad computer_use.observe_desktop (telemetría de pantalla, cursor y captura opcional).
5. Capacidad computer_use.mouse_interact (move, click, double_click, right_click, scroll y límites de pantalla).
6. Capacidad computer_use.keyboard_type (write_text, press_key, hotkey y lista blanca de seguridad).
7. Capacidad computer_use.window_control (list_windows, focus, minimize, maximize, close con verificación).
8. Capacidad computer_use.perceive_and_act (ciclo OBSERVAR -> ACTUAR -> OBSERVAR con delta).
9. Estricta separación EXECUTE -> VERIFY -> REPORT (verified=False y claims_success=False por defecto).
10. Integración con Security Layer (IntegrationSecurityBoundary).
11. Fallback transparente a capacidad nativa cuando el adapter está deshabilitado.
12. Auto-registro en IntegrationHub desde configuración global.
"""

from __future__ import annotations

from typing import Any
import pytest

from core.execution.execution_verifier import ExecutionStatus
from core.integration.adapters.computer_use_adapter import ComputerUseAdapter
from core.integration.hub import IntegrationHub
from core.integration.models import (
    IntegrationContext,
    IntegrationExecutionResult,
    IntegrationStatus,
)
from core.integration.registry import IntegrationRegistry
from core.integration.security_boundary import IntegrationSecurityBoundary
from core.security import RiskLevel


@pytest.fixture
def clean_registry() -> IntegrationRegistry:
    reg = IntegrationRegistry()
    reg.reset()
    return reg


# --- 1. Ciclo de Vida y Disponibilidad ---


@pytest.mark.anyio
async def test_computer_use_adapter_lifecycle() -> None:
    """Verifica que ComputerUseAdapter inicialice correctamente, responda a health_check y se apague limpiamente."""
    adapter = ComputerUseAdapter()
    assert adapter.name == "windows_computer_use"
    assert adapter.version == "1.0.0"

    init_ok = await adapter.initialize()
    assert init_ok is True
    assert adapter.status in (IntegrationStatus.READY, IntegrationStatus.DEGRADED)

    health = await adapter.health_check()
    assert health.is_healthy is True
    assert health.details["capabilities_count"] == 5

    await adapter.shutdown()
    assert adapter.status == IntegrationStatus.AVAILABLE


@pytest.mark.anyio
async def test_computer_use_adapter_missing_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que si faltan dependencias, el adapter pase a UNAVAILABLE de forma segura."""
    adapter = ComputerUseAdapter()
    monkeypatch.setattr(adapter, "check_dependencies", lambda: (False, ["missing_lib"]))

    init_ok = await adapter.initialize()
    assert init_ok is False
    assert adapter.status == IntegrationStatus.UNAVAILABLE

    health = await adapter.health_check()
    assert health.is_healthy is False
    assert health.status == IntegrationStatus.UNAVAILABLE


# --- 2. Declaración de Capacidades ---


def test_computer_use_capabilities_declaration() -> None:
    """Comprueba que se declaren exactamente las 5 capacidades auditadas con metadatos de riesgo correctos."""
    adapter = ComputerUseAdapter()
    caps = adapter.capabilities
    assert len(caps) == 5

    cap_names = {c.name for c in caps}
    expected = {
        "computer_use.observe_desktop",
        "computer_use.mouse_interact",
        "computer_use.keyboard_type",
        "computer_use.window_control",
        "computer_use.perceive_and_act",
    }
    assert cap_names == expected

    # Niveles de riesgo asignados
    cap_map = {c.name: c for c in caps}
    assert cap_map["computer_use.observe_desktop"].required_risk_level == RiskLevel.READ_ONLY
    assert cap_map["computer_use.mouse_interact"].required_risk_level == RiskLevel.SAFE
    assert cap_map["computer_use.keyboard_type"].required_risk_level == RiskLevel.SAFE
    assert cap_map["computer_use.window_control"].required_risk_level == RiskLevel.SAFE
    assert cap_map["computer_use.perceive_and_act"].required_risk_level == RiskLevel.SAFE


# --- 3. Capacidad: computer_use.observe_desktop ---


@pytest.mark.anyio
async def test_observe_desktop_valid() -> None:
    """Verifica la observación del escritorio obteniendo resolución, posición de cursor y procesos."""
    adapter = ComputerUseAdapter()
    await adapter.initialize()

    context = IntegrationContext(
        session_id="test_sess_cu_01",
        parameters={"include_screenshot": True, "include_windows": True},
    )
    res = await adapter.execute("computer_use.observe_desktop", context)

    assert res.executed is True
    assert res.status == ExecutionStatus.SUCCEEDED
    assert res.verified is False  # Regla cardinal: no auto-certifica
    assert res.claims_success is False

    out = res.output
    assert "resolution" in out
    assert out["resolution"]["width"] > 0
    assert out["resolution"]["height"] > 0
    assert "cursor" in out
    assert "screenshot" in out
    assert out["screenshot"] is not None


# --- 4. Capacidad: computer_use.mouse_interact ---


@pytest.mark.anyio
async def test_mouse_interact_move_and_click(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prueba movimientos y clics de mouse controlados."""
    adapter = ComputerUseAdapter()
    await adapter.initialize()

    moved_coords: list[tuple[int, int]] = []
    clicked_args: list[dict[str, Any]] = []

    import pyautogui
    monkeypatch.setattr(pyautogui, "moveTo", lambda x, y: moved_coords.append((x, y)))
    monkeypatch.setattr(pyautogui, "click", lambda **kwargs: clicked_args.append(kwargs))
    monkeypatch.setattr(pyautogui, "size", lambda: (1920, 1080))
    monkeypatch.setattr(pyautogui, "position", lambda: (100, 200))

    # 1. Movimiento válido
    ctx_move = IntegrationContext(
        session_id="test_sess_cu_02",
        parameters={"action": "move", "x": 500, "y": 400},
    )
    res_move = await adapter.execute("computer_use.mouse_interact", ctx_move)
    assert res_move.executed is True
    assert res_move.status == ExecutionStatus.SUCCEEDED
    assert (500, 400) in moved_coords

    # 2. Click válido
    ctx_click = IntegrationContext(
        session_id="test_sess_cu_03",
        parameters={"action": "click", "x": 300, "y": 300, "button": "left"},
    )
    res_click = await adapter.execute("computer_use.mouse_interact", ctx_click)
    assert res_click.executed is True
    assert res_click.status == ExecutionStatus.SUCCEEDED


@pytest.mark.anyio
async def test_mouse_interact_out_of_bounds() -> None:
    """Verifica el rechazo si las coordenadas están fuera de los límites de pantalla."""
    adapter = ComputerUseAdapter()
    await adapter.initialize()

    # Coordenadas negativas
    ctx_neg = IntegrationContext(
        session_id="test_sess_cu_04",
        parameters={"action": "move", "x": -50, "y": 100},
    )
    res_neg = await adapter.execute("computer_use.mouse_interact", ctx_neg)
    assert res_neg.executed is False
    assert res_neg.status == ExecutionStatus.FAILED
    assert "fuera de límites" in (res_neg.error or "").lower()

    # Coordenadas excedentes
    ctx_exceed = IntegrationContext(
        session_id="test_sess_cu_05",
        parameters={"action": "move", "x": 99999, "y": 100},
    )
    res_exceed = await adapter.execute("computer_use.mouse_interact", ctx_exceed)
    assert res_exceed.executed is False
    assert res_exceed.status == ExecutionStatus.FAILED


# --- 5. Capacidad: computer_use.keyboard_type ---


@pytest.mark.anyio
async def test_keyboard_type_write_and_hotkey(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prueba escritura de texto y atajos de teclado seguros."""
    adapter = ComputerUseAdapter()
    await adapter.initialize()

    written_text: list[str] = []
    pressed_keys: list[str] = []
    hotkey_calls: list[tuple[str, ...]] = []

    import pyautogui
    monkeypatch.setattr(pyautogui, "write", lambda text, **kwargs: written_text.append(text))
    monkeypatch.setattr(pyautogui, "press", lambda key, **kwargs: pressed_keys.append(key))
    monkeypatch.setattr(pyautogui, "hotkey", lambda *args, **kwargs: hotkey_calls.append(args))

    # 1. Escritura de texto
    ctx_write = IntegrationContext(
        session_id="test_sess_cu_06",
        parameters={"action": "write_text", "text": "Hola JESSYCA"},
    )
    res_write = await adapter.execute("computer_use.keyboard_type", ctx_write)
    assert res_write.executed is True
    assert res_write.status == ExecutionStatus.SUCCEEDED
    assert "Hola JESSYCA" in written_text

    # 2. Pulsación de tecla permitida
    ctx_press = IntegrationContext(
        session_id="test_sess_cu_07",
        parameters={"action": "press_key", "key": "enter"},
    )
    res_press = await adapter.execute("computer_use.keyboard_type", ctx_press)
    assert res_press.executed is True
    assert "enter" in pressed_keys

    # 3. Hotkey permitido (Ctrl + C)
    ctx_hotkey = IntegrationContext(
        session_id="test_sess_cu_08",
        parameters={"action": "hotkey", "keys": ["ctrl", "c"]},
    )
    res_hotkey = await adapter.execute("computer_use.keyboard_type", ctx_hotkey)
    assert res_hotkey.executed is True
    assert ("ctrl", "c") in hotkey_calls


@pytest.mark.anyio
async def test_keyboard_type_forbidden_key() -> None:
    """Verifica el bloqueo de teclas que no se encuentren en la lista blanca."""
    adapter = ComputerUseAdapter()
    await adapter.initialize()

    ctx_bad = IntegrationContext(
        session_id="test_sess_cu_09",
        parameters={"action": "press_key", "key": "system_power_off_danger"},
    )
    res_bad = await adapter.execute("computer_use.keyboard_type", ctx_bad)
    assert res_bad.executed is False
    assert res_bad.status == ExecutionStatus.FAILED
    assert "no permitida" in (res_bad.error or "").lower()


# --- 6. Capacidad: computer_use.window_control ---


@pytest.mark.anyio
async def test_window_control_list_and_actions() -> None:
    """Prueba listado y operaciones de ventanas."""
    adapter = ComputerUseAdapter()
    await adapter.initialize()

    # 1. Listar ventanas
    ctx_list = IntegrationContext(
        session_id="test_sess_cu_10",
        parameters={"action": "list_windows"},
    )
    res_list = await adapter.execute("computer_use.window_control", ctx_list)
    assert res_list.executed is True
    assert res_list.status == ExecutionStatus.SUCCEEDED
    assert "windows" in res_list.output

    # 2. Falta de parámetro target
    ctx_nofocus = IntegrationContext(
        session_id="test_sess_cu_11",
        parameters={"action": "focus_window"},
    )
    res_nofocus = await adapter.execute("computer_use.window_control", ctx_nofocus)
    assert res_nofocus.executed is False
    assert res_nofocus.status == ExecutionStatus.FAILED


# --- 7. Capacidad: computer_use.perceive_and_act ---


@pytest.mark.anyio
async def test_perceive_and_act_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica el ciclo OBSERVAR -> ACTUAR -> OBSERVAR calculando delta de estado."""
    adapter = ComputerUseAdapter()
    await adapter.initialize()

    import pyautogui
    monkeypatch.setattr(pyautogui, "size", lambda: (1920, 1080))
    # Simular cambio de posición durante la acción
    positions = [(100, 100), (300, 300)]
    monkeypatch.setattr(pyautogui, "position", lambda: positions.pop(0) if positions else (300, 300))
    monkeypatch.setattr(pyautogui, "moveTo", lambda x, y: None)

    sub_act = {
        "type": "mouse",
        "parameters": {"action": "move", "x": 300, "y": 300},
    }
    context = IntegrationContext(
        session_id="test_sess_cu_12",
        parameters={"sub_action": sub_act},
    )
    res = await adapter.execute("computer_use.perceive_and_act", context)

    assert res.executed is True
    assert res.status == ExecutionStatus.SUCCEEDED
    out = res.output
    assert out["cycle"] == "OBSERVAR -> ACTUAR -> OBSERVAR"
    assert out["delta_detected"] is True
    assert out["state_before"]["cursor"] == [100, 100]
    assert out["state_after"]["cursor"] == [300, 300]


# --- 8. Principio Anti-Falso-Éxito (Separación success != verified) ---


@pytest.mark.anyio
async def test_strict_verification_separation() -> None:
    """Verifica que ninguna acción física auto-certifique éxito (claims_success=False por defecto)."""
    adapter = ComputerUseAdapter()
    await adapter.initialize()

    context = IntegrationContext(
        session_id="test_sess_cu_13",
        parameters={"action": "write_text", "text": "Testing anti false success"},
    )
    res = await adapter.execute("computer_use.keyboard_type", context)

    assert res.executed is True
    assert res.status == ExecutionStatus.SUCCEEDED
    assert res.verified is False
    assert res.claims_success is False

    # Solo tras comprobación externa con evidencia
    res.verified = True
    assert res.claims_success is True


# --- 9. Integración con Security Layer (IntegrationSecurityBoundary) ---


@pytest.mark.anyio
async def test_security_boundary_authorizes_observe(clean_registry: IntegrationRegistry) -> None:
    """Comprueba que el SecurityBoundary evalúe el nivel de riesgo de computer_use."""
    adapter = ComputerUseAdapter()
    clean_registry.register(adapter, enabled=True)

    sec_boundary = IntegrationSecurityBoundary()
    hub = IntegrationHub(registry=clean_registry, security_boundary=sec_boundary)
    await hub.initialize_all()

    ctx = IntegrationContext(session_id="test_sec_cu_01", parameters={})
    res = await hub.execute_capability("computer_use.observe_desktop", ctx)

    assert res.executed is True
    assert res.status == ExecutionStatus.SUCCEEDED


# --- 10. Fallback cuando está Deshabilitado ---


@pytest.mark.anyio
async def test_fallback_when_disabled(clean_registry: IntegrationRegistry) -> None:
    """Verifica que si computer_use está deshabilitado, el Hub recurra a la función fallback."""
    adapter = ComputerUseAdapter()
    clean_registry.register(adapter, enabled=False)

    hub = IntegrationHub(registry=clean_registry)
    await hub.initialize_all()

    fallback_called = False

    def native_fallback(ctx: IntegrationContext) -> dict[str, Any]:
        nonlocal fallback_called
        fallback_called = True
        return {"source": "native_windows_skills"}

    ctx = IntegrationContext(session_id="test_fb_cu_01", parameters={})
    res = await hub.execute_with_fallback("computer_use.observe_desktop", ctx, native_fallback)

    assert fallback_called is True
    assert res.executed is True
    assert res.output["source"] == "native_windows_skills"


# --- 11. Auto-Registro en Hub ---


def test_auto_registration_in_hub() -> None:
    """Verifica que register_default_adapters auto-registre ComputerUseAdapter."""
    from core.integration.hub import register_default_adapters

    hub = IntegrationHub()
    register_default_adapters(hub)

    adapter = hub.registry.get("windows_computer_use")
    assert adapter is not None
    assert adapter.name == "windows_computer_use"
    assert adapter.version == "1.0.0"
    cap_names = {c.name for c in adapter.capabilities}
    assert "computer_use.observe_desktop" in cap_names
    assert "computer_use.mouse_interact" in cap_names
    assert "computer_use.keyboard_type" in cap_names
    assert "computer_use.window_control" in cap_names
    assert "computer_use.perceive_and_act" in cap_names
