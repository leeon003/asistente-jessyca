"""Pruebas dedicadas para ActionGuard y los ejecutores de ratón y teclado (Subetapa 08.4)."""

from __future__ import annotations

from datetime import UTC, datetime
import pytest

from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionTarget,
    DesktopActionType,
)
from core.desktop_executors_models import (
    ActionTimeoutError,
    InsufficientConfidenceError,
    StaleTargetError,
    TargetNotFoundError,
    ValidatedTarget,
)
from core.emergency_stop import EmergencyStopTriggeredError, get_emergency_stop_manager
from core.ui_inspection_models import UIElementBounds
from tools.desktop.action_guard import ActionGuard
from tools.desktop.executors import FakeKeyboardExecutor, FakeMouseExecutor


def test_valid_action_executes_successfully() -> None:
    mouse = FakeMouseExecutor()
    kb = FakeKeyboardExecutor()
    guard = ActionGuard(mouse_executor=mouse, keyboard_executor=kb)

    target = ValidatedTarget(
        hwnd=1001,
        owner_title="Test Application",
        bounds=UIElementBounds(x=100, y=200, width=50, height=30),
        confidence=0.95,
        state_hash="hash_valid_12345",
        timestamp=datetime.now(UTC),
    )

    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(window_handle=1001, x=125, y=215),
    )

    res = guard.execute_guarded_action(req, target, current_ui_state_hash="hash_valid_12345")
    assert res.success is True
    assert len(mouse.operations) == 1
    assert mouse.operations[0]["op"] == "click"
    assert mouse.operations[0]["x"] == 125  # Center X: 100 + 25
    assert mouse.operations[0]["y"] == 215  # Center Y: 200 + 15


def test_invalid_target_rejected() -> None:
    guard = ActionGuard()
    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(),
    )

    with pytest.raises(TargetNotFoundError):
        guard.execute_guarded_action(req, validated_target=None)


def test_incorrect_window_handle_rejected() -> None:
    guard = ActionGuard()
    invalid_target = ValidatedTarget(
        hwnd=0,  # HWND inválido
        owner_title="Test App",
        bounds=UIElementBounds(x=0, y=0, width=10, height=10),
        confidence=0.9,
        state_hash="h123",
        timestamp=datetime.now(UTC),
    )

    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(window_handle=0),
    )

    with pytest.raises(TargetNotFoundError):
        guard.execute_guarded_action(req, invalid_target)


def test_insufficient_confidence_rejected() -> None:
    guard = ActionGuard(min_confidence=0.70)
    low_conf_target = ValidatedTarget(
        hwnd=1001,
        owner_title="Test App",
        bounds=UIElementBounds(x=10, y=10, width=20, height=20),
        confidence=0.45,  # Confianza inferior al umbral 0.70
        state_hash="h123",
        timestamp=datetime.now(UTC),
    )

    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(window_handle=1001),
    )

    with pytest.raises(InsufficientConfidenceError):
        guard.execute_guarded_action(req, low_conf_target)


def test_timeout_exceeded_rejected() -> None:
    guard = ActionGuard(action_timeout_seconds=2.0)  # Limite de 2000ms
    target = ValidatedTarget(
        hwnd=1001,
        owner_title="Test App",
        bounds=UIElementBounds(x=10, y=10, width=20, height=20),
        confidence=0.9,
        state_hash="h123",
        timestamp=datetime.now(UTC),
    )

    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(window_handle=1001),
        duration_ms=5000.0,  # 5000ms excede el timeout de 2000ms
    )

    with pytest.raises(ActionTimeoutError):
        guard.execute_guarded_action(req, target)


def test_emergency_stop_blocks_execution() -> None:
    em = get_emergency_stop_manager()
    guard = ActionGuard(emergency_stop_manager=em)
    target = ValidatedTarget(
        hwnd=1001,
        owner_title="Test App",
        bounds=UIElementBounds(x=10, y=10, width=20, height=20),
        confidence=0.9,
        state_hash="h123",
        timestamp=datetime.now(UTC),
    )
    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(window_handle=1001),
    )

    em.trigger_stop("Emergency stop test for ActionGuard", source="test")
    try:
        with pytest.raises(EmergencyStopTriggeredError):
            guard.execute_guarded_action(req, target)
    finally:
        em.reset("cleanup")


def test_stale_target_position_changed_rejected() -> None:
    guard = ActionGuard()
    stale_target = ValidatedTarget(
        hwnd=1001,
        owner_title="Test App",
        bounds=UIElementBounds(x=10, y=10, width=20, height=20),
        confidence=0.9,
        state_hash="original_hash_123",  # Hash inspeccionado previamente
        timestamp=datetime.now(UTC),
    )
    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(window_handle=1001),
    )

    # El estado visual actual cambió y produce un hash diferente ("changed_hash_999")
    with pytest.raises(StaleTargetError):
        guard.execute_guarded_action(req, stale_target, current_ui_state_hash="changed_hash_999")


def test_fake_mouse_and_keyboard_type_text_recorded() -> None:
    mouse = FakeMouseExecutor()
    kb = FakeKeyboardExecutor()
    guard = ActionGuard(mouse_executor=mouse, keyboard_executor=kb)

    target = ValidatedTarget(
        hwnd=2002,
        owner_title="Input Form",
        bounds=UIElementBounds(x=50, y=50, width=100, height=30),
        confidence=0.99,
        state_hash="hash_form_123",
        timestamp=datetime.now(UTC),
    )

    req = DesktopActionRequest(
        action_type=DesktopActionType.TYPE_TEXT,
        target=DesktopActionTarget(window_handle=2002),
        text="Hello Jessyca 3.0",
    )

    res = guard.execute_guarded_action(req, target, current_ui_state_hash="hash_form_123")
    assert res.success is True

    # Mouse debe hacer clic para poner el foco
    assert len(mouse.operations) == 1
    assert mouse.operations[0]["op"] == "click"

    # Keyboard debe escribir el texto
    assert len(kb.operations) == 1
    assert kb.operations[0]["op"] == "type_text"
    assert kb.operations[0]["text_len"] == 16
