"""Pruebas formales de las 10 Invariantes de Seguridad de Jessyca Windows MCP (Subetapa 04.7)."""

from __future__ import annotations

import pytest

from core.audit_logger import AuditEvent, AuditEventType, AuditLogger, MemoryAuditSink
from core.confirmation import ConfirmationManager, ConfirmationStatus, MockConfirmationProvider
from core.permission_manager import PermissionDecision, PermissionManager, PermissionRequest
from core.risk_engine import RiskEngine
from core.security_architecture import SecurityContext, SecurityDecisionType, SecurityLevel, ToolSecurityMetadata
from core.security_policy import PolicyRule, SecurityPolicy, SecurityPolicyEvaluator, create_default_security_policy


# INVARIANTE 1: CRITICAL nunca puede convertirse en ALLOW
def test_invariant_1_critical_never_allow() -> None:
    evaluator = SecurityPolicyEvaluator()
    rule_allow_crit = PolicyRule(
        name="Attempt Critical Allow",
        tool_name="critical_tool",
        decision=SecurityDecisionType.ALLOW,
        priority=9999,
    )
    policy = SecurityPolicy(policy_id="p-inv-1", rules=[rule_allow_crit])

    ctx = SecurityContext(user="admin", tool_name="critical_tool")
    meta = ToolSecurityMetadata(tool_name="critical_tool", risk_level=SecurityLevel.CRITICAL)
    risk_eng = RiskEngine()
    assessment = risk_eng.evaluate_risk(ctx, {})

    decision = evaluator.evaluate_policy(ctx, meta, assessment, policy)
    assert decision.is_allowed is False
    assert decision.decision_type in (SecurityDecisionType.DENY, SecurityDecisionType.REQUIRE_ELEVATED_AUTHORIZATION)


# INVARIANTE 2: UNKNOWN nunca puede convertirse en ALLOW
def test_invariant_2_unknown_never_allow() -> None:
    evaluator = SecurityPolicyEvaluator()
    policy = create_default_security_policy()

    ctx = SecurityContext(user="unknown_user", tool_name="unknown_tool", parameters={"operation": "unknown_op"})
    meta = ToolSecurityMetadata(tool_name="unknown_tool", risk_level=SecurityLevel.SAFE)
    risk_eng = RiskEngine()
    assessment = risk_eng.evaluate_risk(ctx, {"operation": "unknown_op"})

    # Fail-safe predeterminado bloquea operaciones no clasificadas
    decision = evaluator.evaluate_policy(ctx, meta, assessment, policy)
    assert decision.is_allowed is False or decision.decision_type in (SecurityDecisionType.DENY, SecurityDecisionType.REQUIRE_CONFIRMATION)


# INVARIANTE 3: requires_elevation=True nunca puede producir ALLOW directo
def test_invariant_3_elevation_never_direct_allow() -> None:
    evaluator = SecurityPolicyEvaluator()
    rule_allow = PolicyRule(name="Allow Elevation Tool", tool_name="uac_tool", decision=SecurityDecisionType.ALLOW, priority=1000)
    policy = SecurityPolicy(policy_id="p-inv-3", rules=[rule_allow])

    ctx = SecurityContext(user="user", tool_name="uac_tool")
    meta = ToolSecurityMetadata(tool_name="uac_tool", requires_elevation=True)
    risk_eng = RiskEngine()
    assessment = risk_eng.evaluate_risk(ctx, {})

    decision = evaluator.evaluate_policy(ctx, meta, assessment, policy)
    assert decision.is_allowed is False
    assert decision.decision_type == SecurityDecisionType.REQUIRE_ELEVATED_AUTHORIZATION
    assert decision.requires_elevation is True


# INVARIANTE 4: DENY no puede ser sobrescrito por ALLOW
def test_invariant_4_deny_never_overridden_by_allow() -> None:
    evaluator = SecurityPolicyEvaluator()
    rule_allow_high = PolicyRule(name="Global Allow", tool_name="*", decision=SecurityDecisionType.ALLOW, priority=1000)
    rule_deny_low = PolicyRule(name="Specific Deny", tool_name="bad_tool", decision=SecurityDecisionType.DENY, priority=1)
    policy = SecurityPolicy(policy_id="p-inv-4", rules=[rule_allow_high, rule_deny_low])

    ctx = SecurityContext(user="user", tool_name="bad_tool")
    meta = ToolSecurityMetadata(tool_name="bad_tool")
    risk_eng = RiskEngine()
    assessment = risk_eng.evaluate_risk(ctx, {})

    decision = evaluator.evaluate_policy(ctx, meta, assessment, policy)
    assert decision.is_allowed is False
    assert decision.decision_type == SecurityDecisionType.DENY


# INVARIANTE 5: Una confirmación ALLOW_ONCE no puede reutilizarse
def test_invariant_5_allow_once_single_use() -> None:
    conf_mgr = ConfirmationManager()
    req = conf_mgr.create_request(
        tool_name="delete_tool",
        operation="delete",
        parameters={"path": "file.txt"},
        risk_level=SecurityLevel.DANGEROUS,
    )

    provider = MockConfirmationProvider(ConfirmationStatus.APPROVED)
    conf_mgr.submit_request(req, provider=provider)

    # Primer consumo -> Exitoso
    c1 = conf_mgr.consume_confirmation(req.request_id, "delete_tool", "delete", {"path": "file.txt"})
    assert c1 is True

    # Segundo consumo -> Replay Attack Bloqueado
    c2 = conf_mgr.consume_confirmation(req.request_id, "delete_tool", "delete", {"path": "file.txt"})
    assert c2 is False


# INVARIANTE 6: Una confirmación corresponde exactamente a su ActionFingerprint (SHA-256)
def test_invariant_6_confirmation_fingerprint_strict() -> None:
    conf_mgr = ConfirmationManager()
    req = conf_mgr.create_request(
        tool_name="file_tool",
        operation="delete",
        parameters={"path": "C:\\target.txt"},
    )
    conf_mgr.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

    # Intento de consumo modificando la ruta objetivo
    tampered_consume = conf_mgr.consume_confirmation(req.request_id, "file_tool", "delete", {"path": "C:\\other.txt"})
    assert tampered_consume is False


# INVARIANTE 7: El LLM no puede modificar SecurityPolicy ni sus reglas
def test_invariant_7_llm_cannot_modify_policy() -> None:
    policy = create_default_security_policy()
    assert not hasattr(policy, "add_rule")
    assert not hasattr(policy, "remove_rule")
    assert not hasattr(policy, "disable_confirmations")
    assert policy.is_immutable is True

    with pytest.raises(Exception):
        policy.rules = []  # type: ignore[misc]


# INVARIANTE 8: Audit Logger nunca decide permisos
def test_invariant_8_audit_logger_never_decides_permissions() -> None:
    mem_sink = MemoryAuditSink()
    logger = AuditLogger(sinks=[mem_sink])
    assert not hasattr(logger, "evaluate_permission")
    assert not hasattr(logger, "grant_permission")
    assert not hasattr(logger, "revoke_permission")


# INVARIANTE 9: Audit Logger nunca ejecuta herramientas
def test_invariant_9_audit_logger_never_executes_tools() -> None:
    logger = AuditLogger(sinks=[MemoryAuditSink()])
    assert not hasattr(logger, "execute")
    assert not hasattr(logger, "execute_tool")
    assert not hasattr(logger, "run_command")


# INVARIANTE 10: Secretos nunca se persisten en auditoría
def test_invariant_10_secrets_never_persisted_in_audit() -> None:
    mem_sink = MemoryAuditSink()
    logger = AuditLogger(sinks=[mem_sink])

    event = AuditEvent(
        event_type=AuditEventType.REQUEST_RECEIVED,
        parameters={"user": "admin", "password": "MySecretPassword123!", "api_key": "sk-12345"},
        metadata={"token": "bearer_token_xyz"},
    )
    logger.log_audit_event(event)

    recorded = mem_sink.get_events()[0]
    rec_dict = recorded.to_dict()

    assert rec_dict["parameters"]["password"] == "[REDACTED]"
    assert rec_dict["parameters"]["api_key"] == "[REDACTED]"
    assert rec_dict["metadata"]["token"] == "[REDACTED]"
