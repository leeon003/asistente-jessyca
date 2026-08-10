"""Pruebas del servicio DesktopAutomationService y verificación de evidencias (Subetapa 08.4)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionTarget,
    DesktopActionType,
    generate_action_fingerprint,
)
from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel
from server.evidence import AuthorizationEvidence
from tools.desktop.automation_backend import FakeDesktopAutomationBackend
from tools.desktop.automation_service import DesktopAutomationService


def test_desktop_automation_service_executes_authorized_action() -> None:
    backend = FakeDesktopAutomationBackend()
    service = DesktopAutomationService(backend=backend)
    service.emergency_stop.deactivate()

    target = DesktopActionTarget(automation_id="BtnOk", x=10, y=20)
    req = DesktopActionRequest(action_type=DesktopActionType.CLICK_ELEMENT, target=target)

    fp = generate_action_fingerprint("windows.desktop", "click_element", target.to_dict(), {}, "aut-test-1")

    evidence = AuthorizationEvidence(
        evidence_id="ev-aut-1",
        request_id="aut-test-1",
        decision=PermissionDecision.ALLOW,
        policy_rules_evaluated=("rule-1",),
        user_confirmed=True,
        evaluation_timestamp=datetime.now(UTC),
        risk_level=SecurityLevel.DANGEROUS,
        action_fingerprint=fp,
        is_valid=True,
    )

    res = service.execute_action(req, evidence, request_id="aut-test-1")

    assert res.success is True
    assert res.metadata.action_fingerprint == fp
