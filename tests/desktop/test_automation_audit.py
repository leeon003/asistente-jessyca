"""Prueba del ciclo completo de auditoría para acciones de automatización de escritorio (Subetapa 08.4)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.audit_logger import AuditEventType, MemoryAuditSink
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


def test_automation_full_audit_sequence() -> None:
    sink = MemoryAuditSink()
    service = DesktopAutomationService(backend=FakeDesktopAutomationBackend())
    service.audit_logger.add_sink(sink)
    service.emergency_stop.deactivate()

    target = DesktopActionTarget(automation_id="BtnAudit", x=10, y=10)
    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=target,
    )
    fp = generate_action_fingerprint("windows.desktop", "click_element", target.to_dict(), {}, "aut-audit-seq-1")

    evidence = AuthorizationEvidence(
        evidence_id="ev-seq-1",
        request_id="aut-audit-seq-1",
        decision=PermissionDecision.ALLOW,
        policy_rules_evaluated=(),
        user_confirmed=True,
        evaluation_timestamp=datetime.now(UTC),
        risk_level=SecurityLevel.DANGEROUS,
        action_fingerprint=fp,
        is_valid=True,
    )

    res = service.execute_action(req, evidence, request_id="aut-audit-seq-1")

    assert res.success is True

    events = sink.get_events(tool_name="windows.desktop")
    event_types = [e.event_type for e in events]

    assert AuditEventType.DESKTOP_ACTION_SUCCEEDED in event_types
