"""Pruebas adversariales para Security Policy, prioridades e inmutabilidad (Subetapa 04.7)."""

from __future__ import annotations

import pytest

from core.risk_engine import RiskEngine
from core.security_architecture import SecurityContext, SecurityDecisionType, SecurityLevel, ToolSecurityMetadata
from core.security_policy import InvalidPolicyError, PolicyRule, PolicySource, SecurityPolicy, SecurityPolicyEvaluator, create_default_security_policy, validate_security_policy


def test_policy_max_allowed_risk_absolute_enforcement() -> None:
    evaluator = SecurityPolicyEvaluator()
    rule_allow_all = PolicyRule(
        name="Allow All Tools",
        tool_name="*",
        decision=SecurityDecisionType.ALLOW,
        priority=1000,
    )
    # Límite máximo = WARNING
    strict_policy = SecurityPolicy(
        policy_id="p-strict-max",
        version="1.0.0",
        max_allowed_risk=SecurityLevel.WARNING,
        rules=[rule_allow_all],
    )

    ctx = SecurityContext(user="admin", tool_name="dangerous_tool")
    meta = ToolSecurityMetadata(tool_name="dangerous_tool", risk_level=SecurityLevel.DANGEROUS)
    risk_eng = RiskEngine()
    assessment = risk_eng.evaluate_risk(ctx, {})

    # Operación DANGEROUS excede max_allowed_risk=WARNING -> DENY
    decision = evaluator.evaluate_policy(ctx, meta, assessment, strict_policy)
    assert decision.is_allowed is False
    assert decision.decision_type == SecurityDecisionType.DENY


def test_deny_overriding_multi_priority_matrix() -> None:
    evaluator = SecurityPolicyEvaluator()

    rule_allow_high = PolicyRule(name="Allow High Prio", tool_name="cmd", decision=SecurityDecisionType.ALLOW, priority=500)
    rule_deny_low = PolicyRule(name="Deny Low Prio", tool_name="cmd", decision=SecurityDecisionType.DENY, priority=10)
    policy = SecurityPolicy(policy_id="p-deny-matrix", rules=[rule_allow_high, rule_deny_low])

    ctx = SecurityContext(user="user", tool_name="cmd")
    meta = ToolSecurityMetadata(tool_name="cmd", risk_level=SecurityLevel.SAFE)
    risk_eng = RiskEngine()
    assessment = risk_eng.evaluate_risk(ctx, {})

    decision = evaluator.evaluate_policy(ctx, meta, assessment, policy)
    assert decision.is_allowed is False
    assert decision.decision_type == SecurityDecisionType.DENY


def test_duplicate_rule_id_policy_rejection() -> None:
    r1 = PolicyRule(rule_id="same-id", name="Rule 1", decision=SecurityDecisionType.ALLOW)
    r2 = PolicyRule(rule_id="same-id", name="Rule 2", decision=SecurityDecisionType.DENY)

    with pytest.raises(InvalidPolicyError):
        policy = SecurityPolicy(policy_id="p-dup", version="1.0", rules=[r1, r2])
        validate_security_policy(policy)


def test_llm_prompt_injection_policy_modification_immunity() -> None:
    policy = create_default_security_policy()

    # Intentos de inyección de propiedades o llamadas no autorizadas
    assert not hasattr(policy, "disable_security")
    assert not hasattr(policy, "grant_all_permissions")

    with pytest.raises(Exception):
        policy.max_allowed_risk = SecurityLevel.SAFE  # dataclass frozen/protected
