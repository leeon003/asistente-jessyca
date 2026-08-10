"""Pruebas de detección de alteración post-autorización (Subetapa 07.6)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.command_audit import CommandAuditManager
from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel
from server.evidence import AuthorizationEvidence


def test_e2e_authorization_tampering_detection() -> None:
    audit_mgr = CommandAuditManager()
    req_id = "req-tamper-101"

    # Generar fingerprint canónico
    valid_fp = audit_mgr.calculate_action_fingerprint(
        "windows.shell", "execute_command", "powershell", "git", ("status",), req_id
    )

    evidence = AuthorizationEvidence(
        evidence_id="ev-123",
        request_id=req_id,
        decision=PermissionDecision.ALLOW,
        policy_rules_evaluated=("rule-git",),
        user_confirmed=False,
        evaluation_timestamp=datetime.now(UTC),
        risk_level=SecurityLevel.LOW,
        action_fingerprint=valid_fp,
        is_valid=True,
    )

    # 1. Verificación exitosa con parámetros originales
    assert (
        audit_mgr.verify_authorization_integrity(
            evidence, "windows.shell", "execute_command", "powershell", "git", ("status",), req_id
        )
        is True
    )

    # 2. Tampering: cambiar ejecutable 'git' por 'powershell'
    assert (
        audit_mgr.verify_authorization_integrity(
            evidence, "windows.shell", "execute_command", "powershell", "powershell", ("status",), req_id
        )
        is False
    )

    # 3. Tampering: alterar argumentos
    assert (
        audit_mgr.verify_authorization_integrity(
            evidence, "windows.shell", "execute_command", "powershell", "git", ("status", "--exec-path"), req_id
        )
        is False
    )
