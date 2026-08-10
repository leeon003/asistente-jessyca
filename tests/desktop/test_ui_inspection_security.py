"""Pruebas de la frontera de seguridad UIInspectionSecurityManager (Subetapa 08.3)."""

from __future__ import annotations

import pytest

from core.ui_inspection_models import UIElementBounds, UIElementRequest
from core.ui_inspection_security import (
    UIInspectionLimitExceededError,
    UIInspectionSecurityError,
    UIInspectionSecurityManager,
)


def test_ui_security_manager_validates_correct_request() -> None:
    sec = UIInspectionSecurityManager()
    req = UIElementRequest(window_title="Main App", max_depth=10, max_elements=500)

    validated = sec.validate_request(req)
    assert validated.max_depth == 10


def test_ui_security_manager_rejects_negative_depth_or_elements() -> None:
    sec = UIInspectionSecurityManager()

    with pytest.raises(UIInspectionSecurityError):
        sec.validate_request(UIElementRequest(max_depth=-1))

    with pytest.raises(UIInspectionSecurityError):
        sec.validate_request(UIElementRequest(max_elements=0))


def test_ui_security_manager_rejects_excessive_depth_or_elements() -> None:
    sec = UIInspectionSecurityManager()
    sec.max_tree_depth = 20
    sec.max_elements = 1000

    with pytest.raises(UIInspectionLimitExceededError):
        sec.validate_request(UIElementRequest(max_depth=25))

    with pytest.raises(UIInspectionLimitExceededError):
        sec.validate_request(UIElementRequest(max_elements=1500))


def test_ui_security_manager_bounds_validation() -> None:
    sec = UIInspectionSecurityManager()

    valid_bounds = UIElementBounds(x=0, y=0, width=100, height=50)
    sec.validate_bounds(valid_bounds)

    invalid_bounds = UIElementBounds(x=-1, y=0, width=100, height=50)
    with pytest.raises(UIInspectionSecurityError):
        sec.validate_bounds(invalid_bounds)
