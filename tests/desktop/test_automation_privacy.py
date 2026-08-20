"""Prueba de privacidad e inmutable no filtración de secretos en automatización (Subetapa 08.4)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.audit_logger import MemoryAuditSink
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


def test_type_text_confidentiality_in_events_and_sinks() -> None:
    mem_sink = MemoryAuditSink()
    service = DesktopAutomationService(backend=FakeDesktopAutomationBackend())
    service.audit_logger.add_sink(mem_sink)
    service.emergency_stop.deactivate()

    sensitive_payload = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.SecretToken123"
    target = DesktopActionTarget(automation_id="AuthTokenField", x=50, y=50)
    req = DesktopActionRequest(
        action_type=DesktopActionType.TYPE_TEXT,
        target=target,
        text=sensitive_payload,
    )

    args_dict = {"text_len": len(sensitive_payload)}
    fp = generate_action_fingerprint("windows.desktop", "type_text", target.to_dict(), args_dict, "req-priv-2")

    evidence = AuthorizationEvidence(
        evidence_id="ev-priv-2",
        request_id="req-priv-2",
        decision=PermissionDecision.ALLOW,
        policy_rules_evaluated=("rule-priv",),
        user_confirmed=True,
        evaluation_timestamp=datetime.now(UTC),
        risk_level=SecurityLevel.DANGEROUS,
        action_fingerprint=fp,
        is_valid=True,
    )

    service.execute_action(req, evidence, request_id="req-priv-2")

    events = mem_sink.get_events(tool_name="windows.desktop")
    assert len(events) >= 1

    audit_event = events[0]
    metadata_str = str(audit_event.metadata)

    # INVARIANTE CRÍTICO: CERO TEXTO DE TYPE_TEXT EN AUDITORÍA
    assert sensitive_payload not in metadata_str
    assert "SecretToken123" not in metadata_str
    assert audit_event.metadata["text_redacted"] is True
