"""Pruebas dedicadas para la frontera de la acción type_text y la privacidad de secretos (Subetapa 08.4)."""

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


def test_type_text_privacy_secret_never_leaks_in_audit_or_metadata() -> None:
    sink = MemoryAuditSink()
    service = DesktopAutomationService(backend=FakeDesktopAutomationBackend())
    service.audit_logger.add_sink(sink)
    service.emergency_stop.deactivate()

    secret_str = "SuperSecretPasswordToken12345"
    target = DesktopActionTarget(automation_id="PasswordField", x=100, y=100)
    req = DesktopActionRequest(
        action_type=DesktopActionType.TYPE_TEXT,
        target=target,
        text=secret_str,
    )

    args_dict = {"text_len": len(secret_str)}
    fp = generate_action_fingerprint("windows.desktop", "type_text", target.to_dict(), args_dict, "req-type-priv-1")

    evidence = AuthorizationEvidence(
        evidence_id="ev-type-1",
        request_id="req-type-priv-1",
        decision=PermissionDecision.ALLOW,
        policy_rules_evaluated=("rule-type",),
        user_confirmed=True,
        evaluation_timestamp=datetime.now(UTC),
        risk_level=SecurityLevel.DANGEROUS,
        action_fingerprint=fp,
        is_valid=True,
    )

    res = service.execute_action(req, evidence, request_id="req-type-priv-1")

    # 1. El dict de resultado NUNCA debe contener el texto secreto crudo
    res_dict_str = str(res.to_dict())
    assert secret_str not in res_dict_str

    # 2. Los eventos de auditoría NUNCA deben contener el texto secreto crudo
    events = sink.get_events(tool_name="windows.desktop")
    assert len(events) >= 1

    audit_event = events[0]
    metadata_str = str(audit_event.metadata)
    assert secret_str not in metadata_str
    assert audit_event.metadata.get("text_redacted") is True
    assert audit_event.metadata.get("text_length") == len(secret_str)
