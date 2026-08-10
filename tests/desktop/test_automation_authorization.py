"""Pruebas de integridad de huella criptográfica SHA-256 y autorización (Subetapa 08.4)."""

from __future__ import annotations

import pytest

from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionTarget,
    DesktopActionType,
    generate_action_fingerprint,
)
from core.desktop_automation_security import (
    DesktopAutomationSecurityError,
    DesktopAutomationSecurityManager,
)


def test_fingerprint_verification_rejects_tampered_request() -> None:
    sec = DesktopAutomationSecurityManager()
    target = DesktopActionTarget(automation_id="Btn1", x=10, y=20)
    req = DesktopActionRequest(action_type=DesktopActionType.CLICK_ELEMENT, target=target)

    # Generar huella legítima para request_id="req-legit"
    legit_fp = generate_action_fingerprint("windows.desktop", "click_element", target.to_dict(), {}, "req-legit")

    # 1. Mismo request -> Pasa verificación
    assert sec.verify_fingerprint(req, legit_fp, "req-legit") is True

    # 2. Alteración de request_id -> Lanza DesktopAutomationSecurityError
    with pytest.raises(DesktopAutomationSecurityError):
        sec.verify_fingerprint(req, legit_fp, "req-tampered")

    # 3. Alteración de huella esperada -> Lanza DesktopAutomationSecurityError
    with pytest.raises(DesktopAutomationSecurityError):
        sec.verify_fingerprint(req, "invalid_fp_hash_12345", "req-legit")
