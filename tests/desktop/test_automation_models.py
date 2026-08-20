"""Pruebas de los modelos inmutables de automatización de escritorio (Subetapa 08.4)."""

from __future__ import annotations

import pytest

from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionTarget,
    DesktopActionType,
    generate_action_fingerprint,
)


def test_desktop_action_target_summary_and_immutability() -> None:
    target = DesktopActionTarget(automation_id="Btn1", control_type="Button", process_id=123, x=10, y=20)

    assert "auto_id=Btn1" in target.to_summary()
    assert "pid=123" in target.to_summary()

    with pytest.raises(AttributeError):
        target.x = 50  # type: ignore


def test_desktop_action_request_privacy_dict() -> None:
    target = DesktopActionTarget(x=10, y=20)
    req = DesktopActionRequest(action_type=DesktopActionType.TYPE_TEXT, target=target, text="SuperSecretPassword123")

    safe_dict = req.to_dict(safe_privacy=True)
    assert "SuperSecretPassword123" not in str(safe_dict)
    assert safe_dict["text_length"] == 22
    assert "text_hash" in safe_dict


def test_generate_action_fingerprint_deterministic() -> None:
    fp1 = generate_action_fingerprint("windows.desktop", "click_element", {"x": 10, "y": 20}, {}, "req-1")
    fp2 = generate_action_fingerprint("windows.desktop", "click_element", {"x": 10, "y": 20}, {}, "req-1")
    fp3 = generate_action_fingerprint("windows.desktop", "click_element", {"x": 10, "y": 25}, {}, "req-1")

    assert fp1 == fp2
    assert fp1 != fp3
