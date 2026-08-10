"""Pruebas de enforzamiento de límites de jerarquía y elementos UI (Subetapa 08.3)."""

from __future__ import annotations

import pytest

from core.ui_inspection_models import (
    UIControlType,
    UIElementBounds,
    UIElementInfo,
    UIElementRequest,
    UIElementTree,
)
from core.ui_inspection_security import (
    UIInspectionLimitExceededError,
    UIInspectionSecurityManager,
)
from tools.desktop.ui_backend import FakeUIInspectionBackend
from tools.desktop.ui_inspection_service import UIInspectionService


def test_ui_inspection_service_truncates_excessive_tree_depth_and_count() -> None:
    # Crear una cadena profunda de 30 hijos
    curr = UIElementInfo(
        automation_id="Leaf",
        name="Leaf Node",
        control_type=UIControlType.TEXT,
        class_name="Text",
        bounds=UIElementBounds(x=0, y=0, width=10, height=10),
        is_enabled=True,
        is_offscreen=False,
        has_keyboard_focus=False,
        process_id=1,
        framework_id="Win32",
    )
    for i in range(30):
        curr = UIElementInfo(
            automation_id=f"Node_{i}",
            name=f"Node {i}",
            control_type=UIControlType.WINDOW,
            class_name="Window",
            bounds=UIElementBounds(x=0, y=0, width=100, height=100),
            is_enabled=True,
            is_offscreen=False,
            has_keyboard_focus=False,
            process_id=1,
            framework_id="Win32",
            children=(curr,),
        )

    backend = FakeUIInspectionBackend(mock_tree=UIElementTree(root=curr))
    service = UIInspectionService(backend=backend)
    service.max_tree_depth = 5
    service.max_elements = 10

    req = UIElementRequest()
    res = service.inspect_ui_elements(req, request_id="ui-limit-req")

    assert res.metadata.max_depth_reached <= 5
    assert len(res.elements_flat) <= 10


def test_ui_security_limits_exceeded_depth() -> None:
    sec = UIInspectionSecurityManager()
    sec.max_tree_depth = 20

    with pytest.raises(UIInspectionLimitExceededError):
        sec.validate_request(UIElementRequest(max_depth=25))
