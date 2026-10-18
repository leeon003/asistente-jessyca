"""Pruebas rigurosas para la Fase 09: Procedencia de observaciones y rechazo de fakes como evidencia real.

Cubre:
1. Falta de dependencia ('uiautomation' ausente).
2. Excepción nativa de UIA (fallo de consulta sin delegación a Fake).
3. Consulta real sin resultados (distinción entre error técnico vs NO_ELEMENTS_FOUND).
4. Fake explícito de test (disponible vía inyección explícita con SYNTHETIC_TEST).
5. Producción sin navegador disponible (rechazo de FakeBrowserAdapter implícito).
6. Verificador que rechaza evidencia sintética como prueba física.
"""

from __future__ import annotations

import sys
import unittest.mock as mock
from datetime import UTC, datetime

import pytest

from core.action_verification_models import (
    ActionVerificationRequest,
    ExpectedState,
    VerificationStatus,
)
from core.agents.browser_agent import BrowserAgent
from core.browser_session_manager import BrowserSessionManager, FakeBrowserAdapter
from core.control_plane.models import AgentLoopState
from core.exceptions import UIBackendUnavailableError, UIInspectionError
from core.ui_inspection_models import (
    ObservationProvenance,
    ObservationStatus,
    UIControlType,
    UIElementBounds,
    UIElementInfo,
    UIElementRequest,
    UIElementTree,
)
from tools.desktop.action_verifier import ActionVerifier
from tools.desktop.ui_backend import (
    FakeUIInspectionBackend,
    WindowsUIAutomationBackend,
    get_ui_backend,
)


# ==============================================================================
# 1. Falta de dependencia ('uiautomation' no disponible)
# ==============================================================================
def test_windows_ui_backend_missing_dependency_raises_typed_error() -> None:
    """Verifica que sin uiautomation, get_active_window y list_windows lanzan UIBackendUnavailableError."""
    backend = WindowsUIAutomationBackend()

    with mock.patch.dict(sys.modules, {"uiautomation": None}):
        with pytest.raises(UIBackendUnavailableError) as exc_active:
            backend.get_active_window()
        assert "uiautomation" in str(exc_active.value).lower()

        with pytest.raises(UIBackendUnavailableError) as exc_list:
            backend.list_windows()
        assert "uiautomation" in str(exc_list.value).lower()


def test_windows_ui_backend_missing_dependency_returns_unavailable_inspection() -> None:
    """Verifica que sin uiautomation, inspect_ui devuelve estado BACKEND_UNAVAILABLE y cero elementos inventados."""
    backend = WindowsUIAutomationBackend()
    req = UIElementRequest(window_title="MiVentana")

    with mock.patch.dict(sys.modules, {"uiautomation": None}):
        res = backend.inspect_ui(req)

        assert res.is_available is False
        assert res.is_synthetic is False
        assert res.metadata.status == ObservationStatus.BACKEND_UNAVAILABLE
        assert res.metadata.provenance == ObservationProvenance.UNAVAILABLE
        assert "uiautomation" in (res.metadata.error_message or "").lower()
        # NINGÚN elemento ni ventana inventada
        assert len(res.elements_flat) == 0
        assert res.tree.root.name == "Backend Unavailable"


# ==============================================================================
# 2. Excepción nativa de UIA (fallos durante la consulta)
# ==============================================================================
def test_windows_ui_backend_exception_raises_ui_inspection_error() -> None:
    """Verifica que excepciones nativas de Windows/COM elevan UIInspectionError y no retornan fakes."""
    backend = WindowsUIAutomationBackend()

    mock_auto = mock.MagicMock()
    mock_auto.GetForegroundControl.side_effect = RuntimeError("COM RPC Exception 0x80040154")
    mock_auto.GetRootControl.side_effect = RuntimeError("Root Control Detached")

    with mock.patch.dict(sys.modules, {"uiautomation": mock_auto}):
        with pytest.raises(UIInspectionError) as exc_win:
            backend.get_active_window()
        assert "0x80040154" in str(exc_win.value)

        with pytest.raises(UIInspectionError) as exc_list:
            backend.list_windows()
        assert "Root Control Detached" in str(exc_list.value)


def test_windows_ui_backend_inspection_exception_returns_typed_error_result() -> None:
    """Verifica que un fallo durante la inspección UIA retorna INSPECTION_ERROR y cero elementos falsos."""
    backend = WindowsUIAutomationBackend()
    req = UIElementRequest(window_title="MiVentana")

    mock_auto = mock.MagicMock()
    mock_auto.GetRootControl.side_effect = Exception("UI Automation Driver Crash")

    with mock.patch.dict(sys.modules, {"uiautomation": mock_auto}):
        res = backend.inspect_ui(req)

        assert res.is_available is False
        assert res.is_synthetic is False
        assert res.metadata.status == ObservationStatus.INSPECTION_ERROR
        assert res.metadata.provenance == ObservationProvenance.UNAVAILABLE
        assert "UI Automation Driver Crash" in (res.metadata.error_message or "")
        assert len(res.elements_flat) == 0


# ==============================================================================
# 3. Consulta real sin resultados (distinción vs fallo técnico)
# ==============================================================================
def test_real_query_distinguishes_no_elements_found_from_unavailable() -> None:
    """Verifica que cuando UIA funciona pero la ventana objetivo no existe, devuelve NO_ELEMENTS_FOUND con REAL_PHYSICAL."""
    backend = WindowsUIAutomationBackend()
    req = UIElementRequest(window_title="NonExistentTargetWindow")

    mock_auto = mock.MagicMock()
    mock_root = mock.MagicMock()
    mock_auto.GetRootControl.return_value = mock_root

    mock_win = mock.MagicMock()
    mock_win.Exists.return_value = False
    mock_auto.WindowControl.return_value = mock_win

    with mock.patch.dict(sys.modules, {"uiautomation": mock_auto}):
        res = backend.inspect_ui(req)

        # Es una observación real que físicamente comprobó que no hay elementos
        assert res.metadata.status == ObservationStatus.NO_ELEMENTS_FOUND
        assert res.metadata.provenance == ObservationProvenance.REAL_PHYSICAL
        assert res.is_available is True
        assert res.is_synthetic is False
        assert len(res.elements_flat) == 0
        assert "NonExistentTargetWindow" in (res.metadata.error_message or "")


def test_real_list_windows_empty_returns_empty_tuple_without_fake_fallback() -> None:
    """Verifica que si list_windows no encuentra ventanas reales, devuelve () y no llama a FakeUIInspectionBackend."""
    backend = WindowsUIAutomationBackend()

    mock_auto = mock.MagicMock()
    mock_root = mock.MagicMock()
    mock_root.GetChildren.return_value = []
    mock_auto.GetRootControl.return_value = mock_root

    with mock.patch.dict(sys.modules, {"uiautomation": mock_auto}):
        wins = backend.list_windows()

        assert wins == ()
        assert len(wins) == 0


# ==============================================================================
# 4. Fake explícito de test e inyección controlada
# ==============================================================================
def test_fake_ui_backend_explicit_injection_marks_synthetic_provenance() -> None:
    """Verifica que FakeUIInspectionBackend provee explícitamente procedencia SYNTHETIC_TEST."""
    backend = FakeUIInspectionBackend()
    req = UIElementRequest(window_title="Test Mock Window")

    res = backend.inspect_ui(req)
    assert res.is_synthetic is True
    assert res.metadata.provenance == ObservationProvenance.SYNTHETIC_TEST
    assert res.metadata.status == ObservationStatus.SUCCESS
    assert res.metadata.backend_name == "FakeUIInspectionBackend"
    assert len(res.elements_flat) >= 1

    win = backend.get_active_window()
    assert win.is_synthetic is True
    assert win.provenance == ObservationProvenance.SYNTHETIC_TEST

    wins = backend.list_windows()
    assert all(w.is_synthetic for w in wins)
    assert all(w.provenance == ObservationProvenance.SYNTHETIC_TEST for w in wins)


def test_get_ui_backend_factory() -> None:
    """Verifica que la fábrica get_ui_backend selecciona explícitamente real vs fake."""
    assert isinstance(get_ui_backend("fake"), FakeUIInspectionBackend)
    assert isinstance(get_ui_backend("test"), FakeUIInspectionBackend)
    assert isinstance(get_ui_backend("demo"), FakeUIInspectionBackend)
    assert isinstance(get_ui_backend("real"), WindowsUIAutomationBackend)
    assert isinstance(get_ui_backend("production"), WindowsUIAutomationBackend)


# ==============================================================================
# 5. Producción sin navegador disponible
# ==============================================================================
def test_browser_agent_in_production_declares_unavailable_without_session_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que BrowserAgent en producción sin session_manager rechaza navegación y marca UNAVAILABLE."""
    monkeypatch.setenv("ENVIRONMENT", "production")

    def unavailable_browser(**kwargs):
        raise RuntimeError("Simulated missing browser installation")
    monkeypatch.setattr("core.browser_playwright_adapter.PlaywrightBrowserAdapter", unavailable_browser)

    agent = BrowserAgent(session_manager=None)
    assert agent._browser_available is False
    assert agent.session_manager is None

    result = agent.execute_intent("https://www.google.com")

    assert result.final_state == AgentLoopState.STOPPED_ERROR
    assert "no disponible" in result.stop_reason.lower()
    assert result.output_metadata.get("status") == "BROWSER_UNAVAILABLE"
    assert result.output_metadata.get("provenance") == "UNAVAILABLE"


def test_browser_agent_with_explicit_fake_session_manager_tracks_synthetic() -> None:
    """Verifica que la inyección explícita de FakeBrowserAdapter en BrowserAgent marca procedencia sintética."""
    fake_adapter = FakeBrowserAdapter()
    session_mgr = BrowserSessionManager(adapter=fake_adapter)

    agent = BrowserAgent(session_manager=session_mgr)
    result = agent.execute_intent("https://www.google.com")

    assert result.final_state == AgentLoopState.COMPLETED
    assert result.output_metadata.get("is_synthetic") is True
    assert result.output_metadata.get("provenance") == "SYNTHETIC_TEST"


# ==============================================================================
# 6. Verificador que rechaza evidencia sintética como prueba física
# ==============================================================================
def test_action_verifier_rejects_synthetic_evidence_when_real_required() -> None:
    """Verifica que ActionVerifier con require_real_evidence=True rechaza evidencia sintética."""
    root = UIElementInfo(
        automation_id="BtnSave",
        name="Save Complete",
        control_type=UIControlType.BUTTON,
        class_name="Button",
        bounds=UIElementBounds(x=10, y=10, width=50, height=20),
        is_enabled=True,
        is_offscreen=False,
        has_keyboard_focus=False,
        process_id=100,
        framework_id="Win32",
    )
    fake_backend = FakeUIInspectionBackend(mock_tree=UIElementTree(root=root))
    verifier = ActionVerifier(ui_backend=fake_backend, require_real_evidence=True)

    exp = ExpectedState(expected_window_title="Save Complete", expected_control_type="Button")
    req = ActionVerificationRequest(
        action_id="act-test-reject",
        action_type="click",
        expected_state=exp,
        timeout_seconds=0.1,
    )

    res = verifier.verify_action_outcome(req)

    # Debe ser rechazado porque proviene de un backend sintético
    assert res.success is False
    assert res.status == VerificationStatus.SYNTHETIC_REJECTED
    assert res.is_synthetic is True
    assert "sintética rechazada" in res.reason.lower()


def test_action_verifier_handles_backend_unavailable() -> None:
    """Verifica que ActionVerifier responde BACKEND_UNAVAILABLE si la percepción técnica falla."""
    mock_backend = mock.MagicMock()
    with mock.patch.dict(sys.modules, {"uiautomation": None}):
        mock_backend.inspect_ui.return_value = WindowsUIAutomationBackend().inspect_ui(
            UIElementRequest(window_title="Test")
        )
    verifier = ActionVerifier(ui_backend=mock_backend)

    exp = ExpectedState(expected_window_title="Test Window")
    req = ActionVerificationRequest(
        action_id="act-test-unavail",
        action_type="click",
        expected_state=exp,
        timeout_seconds=0.1,
    )

    res = verifier.verify_action_outcome(req)

    assert res.success is False
    assert res.status == VerificationStatus.BACKEND_UNAVAILABLE
    assert "no disponible" in res.reason.lower()
