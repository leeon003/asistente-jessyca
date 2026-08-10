"""Pruebas de fuzzing controlado para la frontera de seguridad de inspección UI (Subetapa 08.3)."""

from __future__ import annotations

import pytest

from core.ui_inspection_models import UIElementBounds, UIElementRequest
from core.ui_inspection_security import (
    UIInspectionLimitExceededError,
    UIInspectionSecurityError,
    UIInspectionSecurityManager,
)


def test_controlled_ui_fuzzing() -> None:
    sec = UIInspectionSecurityManager()

    invalid_requests = [
        UIElementRequest(max_depth=-999),
        UIElementRequest(max_depth=0),
        UIElementRequest(max_elements=-50),
        UIElementRequest(max_elements=0),
    ]

    for req in invalid_requests:
        with pytest.raises(UIInspectionSecurityError):
            sec.validate_request(req)

    # Test Bounding Box inválidos
    invalid_bounds = [
        UIElementBounds(x=-500, y=0, width=10, height=10),
        UIElementBounds(x=0, y=-500, width=10, height=10),
        UIElementBounds(x=0, y=0, width=0, height=10),
        UIElementBounds(x=0, y=0, width=10, height=0),
        UIElementBounds(x=0, y=0, width=-10, height=10),
    ]

    for bounds in invalid_bounds:
        with pytest.raises(UIInspectionSecurityError):
            sec.validate_bounds(bounds)
