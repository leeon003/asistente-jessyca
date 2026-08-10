"""Pruebas de backends de inspección visual UI (Subetapa 08.3)."""

from __future__ import annotations

from core.ui_inspection_models import UIElementRequest
from tools.desktop.ui_backend import FakeUIInspectionBackend, WindowsUIAutomationBackend


def test_fake_ui_backend_returns_mock_tree() -> None:
    backend = FakeUIInspectionBackend()
    req = UIElementRequest(window_title="Test Window")

    res = backend.inspect_ui(req)

    assert res.tree.root.name == "Test Window"
    assert len(res.elements_flat) >= 4
    assert res.metadata.backend_name == "FakeUIInspectionBackend"


def test_windows_ui_backend_graceful_fallback() -> None:
    backend = WindowsUIAutomationBackend()
    req = UIElementRequest(window_title="NonExistentWindowTitle12345")

    res = backend.inspect_ui(req)

    assert res.tree.root is not None
    assert len(res.elements_flat) >= 1
