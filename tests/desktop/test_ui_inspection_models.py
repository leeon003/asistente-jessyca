"""Pruebas de los modelos inmutables de inspección UI (Subetapa 08.3)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.ui_inspection_models import (
    UIControlType,
    UIElementBounds,
    UIElementInfo,
    UIElementRequest,
    UIElementTree,
    UIInspectionMetadata,
    UIInspectionResult,
)


def test_ui_element_bounds_properties_and_immutability() -> None:
    bounds = UIElementBounds(x=10, y=20, width=100, height=50)

    assert bounds.x == 10
    assert bounds.y == 20
    assert bounds.right == 110
    assert bounds.bottom == 70

    with pytest.raises(AttributeError):
        bounds.x = 30  # type: ignore

    d = bounds.to_dict()
    assert d["right"] == 110


def test_ui_control_type_from_str() -> None:
    assert UIControlType.from_str("Button") == UIControlType.BUTTON
    assert UIControlType.from_str("button") == UIControlType.BUTTON
    assert UIControlType.from_str("Window") == UIControlType.WINDOW
    assert UIControlType.from_str("NonExistentType") == UIControlType.UNKNOWN


def test_ui_element_info_and_tree_immutability() -> None:
    bounds = UIElementBounds(x=0, y=0, width=500, height=400)
    btn = UIElementInfo(
        automation_id="Btn1",
        name="Submit",
        control_type=UIControlType.BUTTON,
        class_name="Button",
        bounds=bounds,
        is_enabled=True,
        is_offscreen=False,
        has_keyboard_focus=False,
        process_id=100,
        framework_id="Win32",
    )
    tree = UIElementTree(root=btn)

    meta = UIInspectionMetadata(
        element_count=1,
        max_depth_reached=1,
        processing_time_ms=5.0,
        backend_name="FakeUIInspectionBackend",
        timestamp=datetime.now(UTC),
    )
    res = UIInspectionResult(tree=tree, elements_flat=(btn,), metadata=meta, truncated=False)

    assert res.tree.root.name == "Submit"
    assert res.metadata.element_count == 1

    with pytest.raises(AttributeError):
        res.truncated = True  # type: ignore

    d = res.to_dict()
    assert d["tree"]["root"]["control_type"] == "Button"


def test_window_info_and_detected_element_hashing() -> None:
    now = datetime.now(UTC)
    bounds = UIElementBounds(x=0, y=0, width=800, height=600)
    win = WindowInfo(
        hwnd=1001,
        title="Test App",
        class_name="Window",
        process_id=1234,
        bounds=bounds,
        is_active=True,
        is_minimized=False,
        is_maximized=False,
        is_visible=True,
        timestamp=now,
    )
    assert win.hwnd == 1001
    assert win.is_active is True

    from core.ui_inspection_models import UIDetectionSource, compute_ui_state_hash

    state_hash = compute_ui_state_hash(win.hwnd, win.title, win.bounds, "Window")
    assert len(state_hash) == 16

    elem = DetectedUIElement(
        element_id="elem-1",
        control_type=UIControlType.BUTTON,
        bounds=UIElementBounds(x=10, y=10, width=50, height=20),
        name="OK",
        automation_id="btn_ok",
        class_name="Button",
        confidence=0.99,
        owner_hwnd=1001,
        owner_window_title="Test App",
        detection_source=UIDetectionSource.UI_AUTOMATION,
        timestamp=now,
        state_hash=state_hash,
    )
    assert elem.confidence == 0.99
    assert elem.state_hash == state_hash
