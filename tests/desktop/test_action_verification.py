"""Pruebas dedicadas para la fase VERIFY y el ActionVerifier (Subetapa 08.4)."""

from __future__ import annotations

import threading
import pytest

from core.action_verification_models import (
    ActionVerificationRequest,
    ExpectedState,
    VerificationStatus,
)
from core.emergency_stop import CancellationToken, get_emergency_stop_manager
from core.ui_inspection_models import (
    UIControlType,
    UIElementBounds,
    UIElementInfo,
    UIElementTree,
)
from tools.desktop.action_verifier import ActionVerifier
from tools.desktop.ui_backend import FakeUIInspectionBackend


def test_verification_success() -> None:
    root = UIElementInfo(
        automation_id="BtnSave",
        name="Saved Successfully",
        control_type=UIControlType.TEXT,
        class_name="Static",
        bounds=UIElementBounds(x=10, y=10, width=100, height=20),
        is_enabled=True,
        is_offscreen=False,
        has_keyboard_focus=False,
        process_id=100,
        framework_id="Win32",
    )
    backend = FakeUIInspectionBackend(mock_tree=UIElementTree(root=root))
    verifier = ActionVerifier(ui_backend=backend)

    exp = ExpectedState(
        expected_window_title="Saved Successfully",
        expected_control_type="Text",
    )
    req = ActionVerificationRequest(
        action_id="act-ver-1",
        action_type="click_element",
        expected_state=exp,
        poll_interval_seconds=0.01,
        timeout_seconds=0.5,
    )

    res = verifier.verify_action_outcome(req)
    assert res.success is True
    assert res.status == VerificationStatus.VERIFIED_SUCCESS
    assert res.observed is not None
    assert "Saved Successfully" in res.observed.observed_window_title


def test_verification_timeout() -> None:
    # Backend con un elemento que NUNCA coincide con lo esperado ("Save Dialog")
    root = UIElementInfo(
        automation_id="WinMain",
        name="Main Application Window",
        control_type=UIControlType.WINDOW,
        class_name="Window",
        bounds=UIElementBounds(x=0, y=0, width=500, height=400),
        is_enabled=True,
        is_offscreen=False,
        has_keyboard_focus=False,
        process_id=100,
        framework_id="Win32",
    )
    backend = FakeUIInspectionBackend(mock_tree=UIElementTree(root=root))
    verifier = ActionVerifier(ui_backend=backend)

    exp = ExpectedState(expected_window_title="NonExistent Save Dialog")
    req = ActionVerificationRequest(
        action_id="act-ver-timeout",
        action_type="click_element",
        expected_state=exp,
        poll_interval_seconds=0.01,
        timeout_seconds=0.1,  # Fast timeout for test
    )

    res = verifier.verify_action_outcome(req)
    assert res.success is False
    assert res.status == VerificationStatus.VERIFICATION_TIMEOUT


def test_verification_state_mismatch() -> None:
    root = UIElementInfo(
        automation_id="TxtStatus",
        name="Status: Error Occurred",
        control_type=UIControlType.TEXT,
        class_name="Static",
        bounds=UIElementBounds(x=10, y=10, width=100, height=20),
        is_enabled=True,
        is_offscreen=False,
        has_keyboard_focus=False,
        process_id=100,
        framework_id="Win32",
    )
    backend = FakeUIInspectionBackend(mock_tree=UIElementTree(root=root))
    verifier = ActionVerifier(ui_backend=backend)

    exp = ExpectedState(
        expected_window_title="Status",
        expected_text="Status: Success",
        expect_value_match=True,
    )
    req = ActionVerificationRequest(
        action_id="act-ver-mismatch",
        action_type="type_text",
        expected_state=exp,
        poll_interval_seconds=0.01,
        timeout_seconds=0.1,
    )

    res = verifier.verify_action_outcome(req)
    assert res.success is False
    assert res.status == VerificationStatus.VERIFICATION_FAILED
    assert "discrepancia" in res.reason.lower() or "no coincide" in res.reason.lower() or "timeout" in res.reason.lower()


def test_verification_confidence_failure() -> None:
    # Elemento desactivado (is_enabled=False) produce baja confianza (0.50)
    root = UIElementInfo(
        automation_id="BtnDisabled",
        name="Disabled Button",
        control_type=UIControlType.BUTTON,
        class_name="Button",
        bounds=UIElementBounds(x=10, y=10, width=50, height=20),
        is_enabled=False,
        is_offscreen=False,
        has_keyboard_focus=False,
        process_id=100,
        framework_id="Win32",
    )
    backend = FakeUIInspectionBackend(mock_tree=UIElementTree(root=root))
    verifier = ActionVerifier(ui_backend=backend)

    exp = ExpectedState(expected_window_title="Disabled Button", expected_control_type="Button")
    req = ActionVerificationRequest(
        action_id="act-ver-conf",
        action_type="click_element",
        expected_state=exp,
        poll_interval_seconds=0.01,
        timeout_seconds=0.1,
        min_confidence=0.80,  # Requiere 0.80 pero el elemento es disabled (0.50)
    )

    res = verifier.verify_action_outcome(req)
    assert res.success is False
    assert res.status in (VerificationStatus.CONFIDENCE_FAILED, VerificationStatus.VERIFICATION_TIMEOUT)


def test_verification_cancellation() -> None:
    backend = FakeUIInspectionBackend()
    verifier = ActionVerifier(ui_backend=backend)

    event = threading.Event()
    token = CancellationToken(event=event)
    event.set()  # Cancelación inmediata

    exp = ExpectedState(expected_window_title="Some Window")
    req = ActionVerificationRequest(
        action_id="act-ver-cancel",
        action_type="click_element",
        expected_state=exp,
        poll_interval_seconds=0.01,
        timeout_seconds=2.0,
    )

    res = verifier.verify_action_outcome(req, cancellation_token=token)
    assert res.success is False
    assert res.status == VerificationStatus.CANCELLED


def test_verification_emergency_stop() -> None:
    backend = FakeUIInspectionBackend()
    em = get_emergency_stop_manager()
    verifier = ActionVerifier(ui_backend=backend, emergency_stop_manager=em)

    em.trigger_stop("Emergency stop test for ActionVerifier", source="test")
    try:
        exp = ExpectedState(expected_window_title="Some Window")
        req = ActionVerificationRequest(
            action_id="act-ver-estop",
            action_type="click_element",
            expected_state=exp,
            poll_interval_seconds=0.01,
            timeout_seconds=2.0,
        )

        res = verifier.verify_action_outcome(req)
        assert res.success is False
        assert res.status == VerificationStatus.ABORTED_BY_EMERGENCY_STOP
    finally:
        em.reset("cleanup")


def test_verification_expect_disappearance() -> None:
    # Backend con un elemento diferente (el modal ya no existe)
    root = UIElementInfo(
        automation_id="MainWindow",
        name="Main Window",
        control_type=UIControlType.WINDOW,
        class_name="Window",
        bounds=UIElementBounds(x=0, y=0, width=500, height=400),
        is_enabled=True,
        is_offscreen=False,
        has_keyboard_focus=False,
        process_id=100,
        framework_id="Win32",
    )
    backend = FakeUIInspectionBackend(mock_tree=UIElementTree(root=root))
    verifier = ActionVerifier(ui_backend=backend)

    # Esperar la desaparición del "Save Modal"
    exp = ExpectedState(
        expected_window_title="Save Modal",
        expect_disappearance=True,
    )
    req = ActionVerificationRequest(
        action_id="act-ver-disappear",
        action_type="click_element",
        expected_state=exp,
        poll_interval_seconds=0.01,
        timeout_seconds=0.5,
    )

    res = verifier.verify_action_outcome(req)
    assert res.success is True
    assert res.status == VerificationStatus.VERIFIED_SUCCESS
    assert "desaparecido" in res.reason.lower()
