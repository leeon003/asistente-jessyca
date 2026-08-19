"""Pruebas adversariales de bypass de decisiones y falsificación de origenes de seguridad (Subetapa 04.7)."""

from __future__ import annotations

import pytest

from core.permission_manager import PermissionDecision, PermissionManager, PermissionRequest
from core.risk_engine import RiskEngine
from core.security_architecture import SecurityContext, SecurityDecision, SecurityDecisionType, SecurityLevel, ToolSecurityMetadata
from core.security_policy import PolicyDecision, PolicyRule, PolicySource, SecurityPolicy, SecurityPolicyEvaluator, create_default_security_policy


def test_bypass_deny_to_allow_mutation() -> None:
    evaluator = SecurityPolicyEvaluator()
    policy = create_default_security_policy()

    ctx = SecurityContext(user="attacker", tool_name="cmd_tool")
    meta = ToolSecurityMetadata(tool_name="cmd_tool", risk_level=SecurityLevel.CRITICAL)
    risk_eng = RiskEngine()
    assessment = risk_eng.evaluate_risk(ctx, {})

    decision = evaluator.evaluate_policy(ctx, meta, assessment, policy)
    assert decision.is_allowed is False
    assert decision.decision_type == SecurityDecisionType.DENY

    # Verificar que el objeto PolicyDecision mantiene consistencia y no permite engañar a booleanos
    assert not bool(decision)


def test_bypass_policy_source_spoofing() -> None:
    # Intentar inyectar una fuente no autorizada como LLM o USER_PROMPT en PolicySource
    assert not hasattr(PolicySource, "LLM")
    assert not hasattr(PolicySource, "USER_PROMPT")
    assert not hasattr(PolicySource, "ASSISTANT")

    # Intentar instanciar PolicySource con un string arbitrario
    with pytest.raises(ValueError):
        PolicySource("LLM_PROMPT_INJECTION")


def test_permission_request_context_tampering() -> None:
    perm_mgr = PermissionManager()
    risk_eng = RiskEngine()

    ctx = SecurityContext(user="user", tool_name="sys_read")
    meta = ToolSecurityMetadata(tool_name="sys_read", risk_level=SecurityLevel.CRITICAL)
    assessment = risk_eng.evaluate_risk(ctx, meta)

    req = PermissionRequest(
        context=ctx,
        metadata=meta,
        risk_assessment=assessment,
        tool_name="sys_read",
        operation="read",
    )
    res = perm_mgr.evaluate_permission(req)

    # Operación CRITICAL en PermissionManager debe ser denegada por Fail-Safe
    assert res.is_allowed is False
    assert res.decision == PermissionDecision.DENY


def test_post_evaluation_metadata_mutation_attempt() -> None:
    evaluator = SecurityPolicyEvaluator()
    policy = create_default_security_policy()

    ctx = SecurityContext(user="test_user", tool_name="test_tool")
    meta = ToolSecurityMetadata(tool_name="test_tool", risk_level=SecurityLevel.DANGEROUS)
    risk_eng = RiskEngine()
    assessment = risk_eng.evaluate_risk(ctx, meta)

    decision = evaluator.evaluate_policy(ctx, meta, assessment, policy)
    assert decision.is_allowed is False

    # Modificar metadatos después de la evaluación no afecta la decisión ya tomada
    meta.risk_level = SecurityLevel.SAFE
    meta.requires_confirmation = False
    assert decision.is_allowed is False
    assert decision.decision_type in (SecurityDecisionType.REQUIRE_CONFIRMATION, SecurityDecisionType.REQUIRE_ELEVATED_AUTHORIZATION)
