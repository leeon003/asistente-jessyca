"""Pruebas de contrato, gobernanza y robustez para la integración de pywinauto (Fase I4).

Verifica:
1. Inspección de sólo lectura sin efectos secundarios (CERO clicks en IUIInspectionBackend).
2. Resolución de control único vs ambiguo.
3. Manejo de elementos obsoletos / ventanas destruidas (stale elements).
4. Denegación de política de seguridad con CERO clicks.
5. Parada de emergencia activa con CERO clicks.
6. Falta de librería pywinauto (fallback explícito, typed error, cero elementos inventados).
7. Preservación de coordenadas multi-monitor (incluyendo valores negativos).
8. Ciclo de vida COM y fábrica get_ui_backend.
"""

from __future__ import annotations

import sys
from unittest import mock
from unittest.mock import MagicMock

import pytest

from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionTarget,
    DesktopActionType,
)
from core.emergency_stop import EmergencyStopManager
from core.exceptions import UIBackendUnavailableError
from core.ui_inspection_models import (
    ObservationProvenance,
    ObservationStatus,
    UIElementBounds,
    UIElementRequest,
)
from tools.desktop.pywinauto_action_executor import PyWinAutoGovernedActionExecutor
from tools.desktop.pywinauto_backend import PyWinAutoInspectionBackend
from tools.desktop.ui_backend import get_ui_backend

try:
    import pywinauto
except ImportError:
    pywinauto = None

requires_pywinauto = pytest.mark.skipif(
    pywinauto is None,
    reason="pywinauto no está instalado en este entorno",
)


# ==============================================================================
# 1. Contrato de Sólo Lectura: Inspección sin efectos (ZERO UI ACTIONS)
# ==============================================================================
def test_pywinauto_inspection_is_strictly_read_only() -> None:
    """Verifica que PyWinAutoInspectionBackend no expone ni ejecuta métodos de acción (clicks, send_keys)."""
    backend = PyWinAutoInspectionBackend()
    assert not hasattr(backend, "click")
    assert not hasattr(backend, "click_element")
    assert not hasattr(backend, "type_text")
    assert not hasattr(backend, "send_keys")
    assert not hasattr(backend, "drag_and_drop")


@requires_pywinauto
def test_pywinauto_inspect_ui_mocked_window() -> None:
    """Verifica la inspección jerárquica de elementos con coordenadas multi-monitor."""
    backend = PyWinAutoInspectionBackend()

    mock_win = MagicMock()
    mock_win.window_text.return_value = "Test App Window"
    mock_win.class_name.return_value = "TestClass"
    # Coordenadas en un monitor secundario a la izquierda (x negativo)
    mock_rect = MagicMock()
    mock_rect.left = -1920
    mock_rect.top = 50
    mock_rect.width.return_value = 1920
    mock_rect.height.return_value = 1080
    mock_win.rectangle.return_value = mock_rect
    mock_win.is_enabled.return_value = True
    mock_win.element_info.automation_id = "MainWin_AutoId"
    mock_win.element_info.control_type = "Window"
    mock_win.element_info.process_id = 9999
    mock_win.children.return_value = []

    mock_desktop = MagicMock()
    mock_desktop.windows.return_value = [mock_win]

    with mock.patch("pywinauto.Desktop", return_value=mock_desktop):
        req = UIElementRequest(window_title="Test App", max_depth=3, max_elements=50)
        res = backend.inspect_ui(req)

        assert res.is_available is True
        assert res.metadata.status == ObservationStatus.SUCCESS
        assert res.metadata.provenance == ObservationProvenance.REAL_PHYSICAL
        assert len(res.elements_flat) == 1

        root_elem = res.elements_flat[0]
        assert root_elem.name == "Test App Window"
        assert root_elem.automation_id == "MainWin_AutoId"
        # Invariante multi-monitor: x negativo preservado sin clamping a 0
        assert root_elem.bounds.x == -1920
        assert root_elem.bounds.y == 50
        assert root_elem.bounds.width == 1920


# ==============================================================================
# 2. Control Único vs Ambiguo en Inspección y Acción
# ==============================================================================
@requires_pywinauto
def test_pywinauto_inspect_ui_handles_ambiguous_windows_by_exact_match() -> None:
    """Verifica que ante múltiples ventanas que contienen la subcadena, prioriza coincidencia exacta."""
    backend = PyWinAutoInspectionBackend()

    mock_win1 = MagicMock()
    mock_win1.window_text.return_value = "Notepad - Document 1"
    mock_rect1 = MagicMock()
    mock_rect1.left, mock_rect1.top = 100, 100
    mock_rect1.width.return_value, mock_rect1.height.return_value = 800, 600
    mock_win1.rectangle.return_value = mock_rect1
    mock_win1.children.return_value = []

    mock_win2 = MagicMock()
    mock_win2.window_text.return_value = "Notepad"
    mock_rect2 = MagicMock()
    mock_rect2.left, mock_rect2.top = 200, 200
    mock_rect2.width.return_value, mock_rect2.height.return_value = 800, 600
    mock_win2.rectangle.return_value = mock_rect2
    mock_win2.children.return_value = []

    mock_desktop = MagicMock()
    mock_desktop.windows.return_value = [mock_win1, mock_win2]

    with mock.patch("pywinauto.Desktop", return_value=mock_desktop):
        req = UIElementRequest(window_title="Notepad")
        res = backend.inspect_ui(req)

        assert res.is_available is True
        # Debe haber seleccionado mock_win2 por coincidencia exacta
        assert res.tree.root.name == "Notepad"


@requires_pywinauto
def test_pywinauto_executor_rejects_ambiguous_targets() -> None:
    """Verifica que el ejecutor gobernado rechaza actuar si hay ambigüedad sin coincidencia única."""
    executor = PyWinAutoGovernedActionExecutor()

    mock_win1 = MagicMock()
    mock_win1.window_text.return_value = "Editor Window Copy A"
    mock_win2 = MagicMock()
    mock_win2.window_text.return_value = "Editor Window Copy B"

    mock_desktop = MagicMock()
    mock_desktop.windows.return_value = [mock_win1, mock_win2]

    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(name="Editor Window"),
    )

    with mock.patch("pywinauto.Desktop", return_value=mock_desktop):
        res = executor.execute_action(req, authorized=True)
        assert res.success is False
        assert res.metadata.action_type == "click_element"
        assert "AMBIGUOUS_TARGET" in res.message
        assert "coincidentes" in res.message


# ==============================================================================
# 3. Manejo de Elementos Obsoletos / Ventana Destruida (Stale Elements)
# ==============================================================================
@requires_pywinauto
def test_pywinauto_inspect_ui_handles_stale_element_gracefully() -> None:
    """Verifica que si un elemento se destruye durante la inspección, no tumba el proceso."""
    backend = PyWinAutoInspectionBackend()

    mock_win = MagicMock()
    mock_win.window_text.return_value = "Transient Window"
    # Lanzar RuntimeError / COMError simulando que el elemento desapareció
    mock_win.rectangle.side_effect = RuntimeError("Element has been destroyed / stale")

    mock_desktop = MagicMock()
    mock_desktop.windows.return_value = [mock_win]

    with mock.patch("pywinauto.Desktop", return_value=mock_desktop):
        req = UIElementRequest(window_title="Transient Window")
        res = backend.inspect_ui(req)

        # Debe responder limpiamente NO_ELEMENTS_FOUND sin lanzar excepción no capturada
        assert res.is_available is True
        assert res.metadata.status == ObservationStatus.NO_ELEMENTS_FOUND
        assert len(res.elements_flat) == 0


@requires_pywinauto
def test_pywinauto_executor_handles_stale_target_cleanly() -> None:
    """Verifica que el ejecutor devuelve fallo controlado si el control objetivo fue destruido."""
    executor = PyWinAutoGovernedActionExecutor()

    mock_win = MagicMock()
    mock_win.handle = 12345
    mock_ctrl = MagicMock()
    mock_ctrl.exists.return_value = False  # El control ya no existe en la ventana
    mock_win.child_window.return_value = mock_ctrl

    mock_desktop = MagicMock()
    mock_desktop.windows.return_value = [mock_win]

    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(window_handle=12345, automation_id="BtnMissing"),
    )

    with mock.patch("pywinauto.Desktop", return_value=mock_desktop):
        res = executor.execute_action(req, authorized=True)
        assert res.success is False
        assert "STALE" in res.message


# ==============================================================================
# 4. Denegación de Política de Seguridad con CERO Clicks
# ==============================================================================
@requires_pywinauto
def test_pywinauto_executor_policy_denial_results_in_zero_clicks() -> None:
    """Verifica que ante denegación de política o falta de autorización, se ejecutan CERO clicks."""
    mock_evaluator = MagicMock()
    mock_evaluator.is_authorized.return_value = False  # Denegado

    executor = PyWinAutoGovernedActionExecutor(policy_evaluator=mock_evaluator)

    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(x=500, y=500),
    )

    with mock.patch("pywinauto.mouse.click") as mock_mouse_click:
        res = executor.execute_action(req, authorized=False)

        assert res.success is False
        assert "POLICY_DENIED_ZERO_CLICKS" in res.message
        assert "no autorizada" in res.message
        # INVARIANTE CRÍTICO: CERO clicks ejecutados
        mock_mouse_click.assert_not_called()


@requires_pywinauto
def test_pywinauto_executor_emergency_stop_results_in_zero_clicks() -> None:
    """Verifica que con parada de emergencia activa, se ejecutan CERO clicks."""
    em = EmergencyStopManager()
    em.trigger_stop("Prueba de seguridad")

    executor = PyWinAutoGovernedActionExecutor(emergency_stop_manager=em)

    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(x=500, y=500),
    )

    with mock.patch("pywinauto.mouse.click") as mock_mouse_click:
        res = executor.execute_action(req, authorized=True)

        assert res.success is False
        assert "EMERGENCY_STOP_ACTIVE" in res.message
        mock_mouse_click.assert_not_called()

    em.reset("test_teardown")


# ==============================================================================
# 5. Falta de Dependencia (Lazy Import & Missing Library Fallback)
# ==============================================================================
def test_pywinauto_backend_missing_dependency_behavior() -> None:
    """Verifica que sin pywinauto, el backend devuelve BACKEND_UNAVAILABLE y cero elementos inventados."""
    backend = PyWinAutoInspectionBackend()

    with mock.patch.dict(sys.modules, {"pywinauto": None}):
        # inspect_ui debe retornar BACKEND_UNAVAILABLE sin inventar nada
        req = UIElementRequest(window_title="CualquierVentana")
        res = backend.inspect_ui(req)
        assert res.is_available is False
        assert res.metadata.status == ObservationStatus.BACKEND_UNAVAILABLE
        assert len(res.elements_flat) == 0

        # get_active_window y list_windows deben lanzar UIBackendUnavailableError tipado
        with pytest.raises(UIBackendUnavailableError):
            backend.get_active_window()

        with pytest.raises(UIBackendUnavailableError):
            backend.list_windows()


def test_pywinauto_executor_missing_dependency_fails_gracefully() -> None:
    """Verifica que sin pywinauto, el ejecutor retorna BACKEND_UNAVAILABLE sin crash."""
    executor = PyWinAutoGovernedActionExecutor()

    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(x=100, y=100),
    )

    with mock.patch.dict(sys.modules, {"pywinauto": None}):
        res = executor.execute_action(req, authorized=True)
        assert res.success is False
        assert "BACKEND_UNAVAILABLE" in res.message


# ==============================================================================
# 6. Fábrica get_ui_backend y Multi-Monitor Coordinates
# ==============================================================================
def test_get_ui_backend_supports_pywinauto() -> None:
    """Verifica que la fábrica get_ui_backend instancia PyWinAutoInspectionBackend cuando se solicita."""
    backend_pwa = get_ui_backend(mode="pywinauto")
    assert isinstance(backend_pwa, PyWinAutoInspectionBackend)

    backend_pwa_short = get_ui_backend(mode="pwa")
    assert isinstance(backend_pwa_short, PyWinAutoInspectionBackend)


def test_ui_element_bounds_preserves_negative_multimonitor_coords() -> None:
    """Verifica que UIElementBounds almacena y calcula propiedades correctamente con coordenadas negativas."""
    bounds = UIElementBounds(x=-1920, y=-1080, width=1920, height=1080)
    assert bounds.x == -1920
    assert bounds.y == -1080
    assert bounds.width == 1920
    assert bounds.height == 1080
    assert bounds.right == 0
    assert bounds.bottom == 0
    d = bounds.to_dict()
    assert d["x"] == -1920
    assert d["y"] == -1080
