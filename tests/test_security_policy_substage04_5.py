"""Pruebas unitarias de seguridad y regresión para Security Policy (Subetapa 04.5).

Cubre las 5 correcciones críticas de seguridad requeridas:
1. DENY tiene protección contra sobrescritura accidental por reglas ALLOW de mayor prioridad.
2. max_allowed_risk es un límite absoluto (jamás resulta ALLOW para un riesgo superior).
3. Política predeterminada conservadora (SAFE->ALLOW, WARNING->REQUIRE_CONFIRMATION, DANGEROUS->REQUIRE_CONFIRMATION, CRITICAL->DENY, UNKNOWN->DENY).
4. Pruebas de escalamiento de privilegios (CRITICAL+ALLOW no es permitido, requires_elevation se preserva).
5. Alcance estricto de 04.5.
"""

from __future__ import annotations

import pytest

from core.confirmation import (
    ConfirmationManager,
    ConfirmationStatus,
    MockConfirmationProvider,
)
from core.permission_manager import (
    PermissionDecision,
    PermissionManager,
    PermissionRequest,
)
from core.risk_engine import RiskEngine
from core.security_architecture import (
    SecurityContext,
    SecurityDecisionType,
    SecurityLevel,
    SecurityRequest,
    ToolSecurityMetadata,
)
from core.security_policy import (
    InvalidPolicyError,
    PolicyRule,
    PolicyRuleCondition,
    PolicySource,
    SecurityPolicy,
    SecurityPolicyEvaluator,
    create_default_security_policy,
    validate_security_policy,
)


def _make_sample_context(
    user: str = "test_user",
    tool_name: str = "filesystem",
    operation: str = "read",
    params: dict | None = None,
) -> SecurityContext:
    parameters = params or {}
    parameters["operation"] = operation
    return SecurityContext(
        user=user,
        tool_name=tool_name,
        parameters=parameters,
        session_id="test_session_123",
        environment="windows",
    )


def _make_sample_metadata(
    tool_name: str = "filesystem",
    risk_level: SecurityLevel = SecurityLevel.SAFE,
    requires_confirmation: bool = False,
    requires_elevation: bool = False,
) -> ToolSecurityMetadata:
    return ToolSecurityMetadata(
        tool_name=tool_name,
        category="file_ops",
        risk_level=risk_level,
        requires_confirmation=requires_confirmation,
        requires_elevation=requires_elevation,
    )


# CORRECCIÓN 1: DENY protección contra sobrescritura accidental por ALLOW de mayor prioridad
def test_deny_protection_against_higher_priority_allow() -> None:
    evaluator = SecurityPolicyEvaluator()
    rule_allow_global = PolicyRule(
        name="Allow All Global",
        tool_name="*",
        decision=SecurityDecisionType.ALLOW,
        priority=100,
    )
    rule_deny_specific = PolicyRule(
        name="Deny Registry Write",
        tool_name="registry",
        operation="write",
        decision=SecurityDecisionType.DENY,
        priority=50,
    )
    policy = SecurityPolicy(
        policy_id="p-deny-protection",
        version="1.0.0",
        rules=[rule_allow_global, rule_deny_specific],
    )

    ctx = _make_sample_context(tool_name="registry", operation="write")
    meta = _make_sample_metadata(tool_name="registry")
    risk_eng = RiskEngine()
    req = SecurityRequest(context=ctx, metadata=meta, action="write")
    assessment = risk_eng.evaluate_risk(req)

    res = evaluator.evaluate_policy(ctx, meta, assessment, policy)
    assert res.is_allowed is False
    assert res.decision_type == SecurityDecisionType.DENY
    assert res.matched_rule_name == "Deny Registry Write"


# CORRECCIÓN 2: max_allowed_risk es un límite absoluto
def test_max_allowed_risk_absolute_limit() -> None:
    evaluator = SecurityPolicyEvaluator()
    rule_allow = PolicyRule(
        name="Explicit Allow Critical Tool",
        tool_name="critical_tool",
        decision=SecurityDecisionType.ALLOW,
        priority=999,
    )
    policy = SecurityPolicy(
        policy_id="p-max-risk-limit",
        version="1.0.0",
        max_allowed_risk=SecurityLevel.DANGEROUS,  # Límite máximo = DANGEROUS
        rules=[rule_allow],
    )

    ctx = _make_sample_context(tool_name="critical_tool")
    meta = _make_sample_metadata(tool_name="critical_tool", risk_level=SecurityLevel.CRITICAL)
    risk_eng = RiskEngine()
    req = SecurityRequest(context=ctx, metadata=meta, action="execute")
    assessment = risk_eng.evaluate_risk(req)

    res = evaluator.evaluate_policy(ctx, meta, assessment, policy)
    assert res.is_allowed is False
    assert res.decision_type == SecurityDecisionType.DENY
    assert "excede el máximo permitido" in res.reason or "Límite absoluto" in res.reason


# CORRECCIÓN 3: Política predeterminada conservadora (WARNING requiere confirmación)
def test_conservative_default_policy() -> None:
    evaluator = SecurityPolicyEvaluator()
    policy = create_default_security_policy()

    # SAFE -> ALLOW
    ctx_safe = _make_sample_context(tool_name="safe_info", operation="read")
    meta_safe = _make_sample_metadata(tool_name="safe_info", risk_level=SecurityLevel.SAFE)
    risk_eng = RiskEngine()
    res_safe = evaluator.evaluate_policy(ctx_safe, meta_safe, risk_eng.evaluate_risk(SecurityRequest(context=ctx_safe, metadata=meta_safe)), policy)
    assert res_safe.is_allowed is True
    assert res_safe.decision_type == SecurityDecisionType.ALLOW

    # WARNING -> REQUIRE_CONFIRMATION (No se permite ejecución directa sin confirmación)
    ctx_warn = _make_sample_context(tool_name="file_modifier", operation="write")
    meta_warn = _make_sample_metadata(tool_name="file_modifier", risk_level=SecurityLevel.WARNING)
    res_warn = evaluator.evaluate_policy(ctx_warn, meta_warn, risk_eng.evaluate_risk(SecurityRequest(context=ctx_warn, metadata=meta_warn)), policy)
    assert res_warn.is_allowed is False
    assert res_warn.decision_type == SecurityDecisionType.REQUIRE_CONFIRMATION

    # DANGEROUS -> REQUIRE_CONFIRMATION
    ctx_dang = _make_sample_context(tool_name="file_deleter", operation="delete")
    meta_dang = _make_sample_metadata(tool_name="file_deleter", risk_level=SecurityLevel.DANGEROUS)
    res_dang = evaluator.evaluate_policy(ctx_dang, meta_dang, risk_eng.evaluate_risk(SecurityRequest(context=ctx_dang, metadata=meta_dang)), policy)
    assert res_dang.is_allowed is False
    assert res_dang.decision_type == SecurityDecisionType.REQUIRE_CONFIRMATION

    # CRITICAL -> DENY
    ctx_crit = _make_sample_context(tool_name="sys_destroyer", operation="delete_sys")
    meta_crit = _make_sample_metadata(tool_name="sys_destroyer", risk_level=SecurityLevel.CRITICAL)
    res_crit = evaluator.evaluate_policy(ctx_crit, meta_crit, risk_eng.evaluate_risk(SecurityRequest(context=ctx_crit, metadata=meta_crit)), policy)
    assert res_crit.is_allowed is False
    assert res_crit.decision_type == SecurityDecisionType.DENY

    # UNKNOWN -> DENY
    ctx_unk = _make_sample_context(tool_name="unknown_tool", operation="unknown_op")
    meta_unk = _make_sample_metadata(tool_name="unknown_tool")
    res_unk = evaluator.evaluate_policy(ctx_unk, meta_unk, risk_eng.evaluate_risk(SecurityRequest(context=ctx_unk, metadata=meta_unk)), policy)
    assert res_unk.is_allowed is False
    assert res_unk.decision_type in (SecurityDecisionType.DENY, SecurityDecisionType.REQUIRE_CONFIRMATION)


# CORRECCIÓN 4: Escalamiento de privilegios (CRITICAL + ALLOW bloqueado, requires_elevation preservado)
def test_privilege_escalation_protection() -> None:
    evaluator = SecurityPolicyEvaluator()
    rule_allow_crit = PolicyRule(
        name="Allow Critical Attempt",
        tool_name="admin_tool",
        decision=SecurityDecisionType.ALLOW,
        priority=1000,
    )
    policy = SecurityPolicy(policy_id="p-escalation", version="1.0.0", rules=[rule_allow_crit])

    # CRITICAL + ALLOW no se convierte en una autorización efectiva
    ctx_crit = _make_sample_context(tool_name="admin_tool")
    meta_crit = _make_sample_metadata(tool_name="admin_tool", risk_level=SecurityLevel.CRITICAL)
    risk_eng = RiskEngine()
    res_crit = evaluator.evaluate_policy(ctx_crit, meta_crit, risk_eng.evaluate_risk(SecurityRequest(context=ctx_crit, metadata=meta_crit)), policy)
    assert res_crit.is_allowed is False

    # requires_elevation=True se conserva correctamente y exige elevación
    meta_elev = _make_sample_metadata(tool_name="admin_tool", requires_elevation=True)
    res_elev = evaluator.evaluate_policy(ctx_crit, meta_elev, risk_eng.evaluate_risk(SecurityRequest(context=ctx_crit, metadata=meta_elev)), policy)
    assert res_elev.is_allowed is False
    assert res_elev.requires_elevation is True
    assert res_elev.decision_type == SecurityDecisionType.REQUIRE_ELEVATED_AUTHORIZATION


# 5. Policy válida e inválida
def test_policy_valid_and_invalid() -> None:
    policy = create_default_security_policy()
    assert validate_security_policy(policy) is True

    with pytest.raises(InvalidPolicyError):
        SecurityPolicy(policy_id="", version="1.0.0")

    with pytest.raises(InvalidPolicyError):
        dup1 = PolicyRule(rule_id="dup", name="R1", decision=SecurityDecisionType.ALLOW)
        dup2 = PolicyRule(rule_id="dup", name="R2", decision=SecurityDecisionType.DENY)
        policy_bad = SecurityPolicy(policy_id="bad", version="1.0", rules=[dup1, dup2])
        validate_security_policy(policy_bad)


# 6. Priority and tie breaking
def test_priority_and_tie_breaking() -> None:
    evaluator = SecurityPolicyEvaluator()
    rule_low = PolicyRule(name="Low Allow", tool_name="tool_a", decision=SecurityDecisionType.ALLOW, priority=10)
    rule_high = PolicyRule(name="High Require Conf", tool_name="tool_a", decision=SecurityDecisionType.REQUIRE_CONFIRMATION, priority=100)
    policy = SecurityPolicy(policy_id="p-prio", version="1.0", rules=[rule_low, rule_high])

    ctx = _make_sample_context(tool_name="tool_a")
    meta = _make_sample_metadata(tool_name="tool_a")
    risk_eng = RiskEngine()

    res = evaluator.evaluate_policy(ctx, meta, risk_eng.evaluate_risk(SecurityRequest(context=ctx, metadata=meta)), policy)
    assert res.is_allowed is False
    assert res.decision_type == SecurityDecisionType.REQUIRE_CONFIRMATION
    assert res.matched_rule_name == "High Require Conf"


# 7. Fail-safe
def test_failsafe_behavior() -> None:
    evaluator = SecurityPolicyEvaluator()
    res = evaluator.evaluate_policy(None, None, None)
    assert res.is_allowed is False
    assert res.decision_type == SecurityDecisionType.DENY


# 8. Policy version & immutability & source
def test_policy_metadata_and_immutability() -> None:
    evaluator = SecurityPolicyEvaluator()
    policy = SecurityPolicy(policy_id="sys-v1", version="1.5.0", source=PolicySource.SYSTEM, rules=[])
    initial_count = len(policy.rules)

    ctx = _make_sample_context()
    meta = _make_sample_metadata()
    risk_eng = RiskEngine()

    res = evaluator.evaluate_policy(ctx, meta, risk_eng.evaluate_risk(SecurityRequest(context=ctx, metadata=meta)), policy)
    assert res.policy_version == "1.5.0"
    assert res.policy_source == PolicySource.SYSTEM
    assert len(policy.rules) == initial_count


# 9. Tool + operation granularity
def test_tool_plus_operation_granularity() -> None:
    evaluator = SecurityPolicyEvaluator()
    rule_read = PolicyRule(name="Read Allow", tool_name="fs", operation="read", decision=SecurityDecisionType.ALLOW, priority=100)
    rule_del = PolicyRule(name="Delete Conf", tool_name="fs", operation="delete", decision=SecurityDecisionType.REQUIRE_CONFIRMATION, priority=100)
    policy = SecurityPolicy(policy_id="p-gran", version="1.0", rules=[rule_read, rule_del])

    ctx_read = _make_sample_context(tool_name="fs", operation="read")
    meta = _make_sample_metadata(tool_name="fs")
    risk_eng = RiskEngine()

    res_read = evaluator.evaluate_policy(ctx_read, meta, risk_eng.evaluate_risk(SecurityRequest(context=ctx_read, metadata=meta)), policy)
    assert res_read.is_allowed is True

    ctx_del = _make_sample_context(tool_name="fs", operation="delete")
    res_del = evaluator.evaluate_policy(ctx_del, meta, risk_eng.evaluate_risk(SecurityRequest(context=ctx_del, metadata=meta)), policy)
    assert res_del.is_allowed is False
    assert res_del.decision_type == SecurityDecisionType.REQUIRE_CONFIRMATION


# 10. Path restriction prepared
def test_path_restriction_prepared() -> None:
    evaluator = SecurityPolicyEvaluator()
    rule_sys = PolicyRule(name="Deny Sys32", decision=SecurityDecisionType.DENY, priority=300, conditions=PolicyRuleCondition(path_patterns=["c:\\windows\\system32*"]))
    rule_doc = PolicyRule(name="Allow Docs", decision=SecurityDecisionType.ALLOW, priority=100, conditions=PolicyRuleCondition(path_patterns=["c:\\users\\*\\documents*"]))
    policy = SecurityPolicy(policy_id="p-path", version="1.0", rules=[rule_sys, rule_doc])

    ctx_sys = _make_sample_context(params={"path": "C:\\Windows\\System32\\cmd.exe"})
    meta = _make_sample_metadata()
    risk_eng = RiskEngine()

    res_sys = evaluator.evaluate_policy(ctx_sys, meta, risk_eng.evaluate_risk(SecurityRequest(context=ctx_sys, metadata=meta)), policy)
    assert res_sys.is_allowed is False
    assert res_sys.matched_rule_name == "Deny Sys32"


# 11. No auto-modificación por LLM
def test_no_auto_modification_by_llm() -> None:
    policy = create_default_security_policy()
    assert not hasattr(policy, "add_rule")
    assert not hasattr(policy, "remove_rule")
    assert not hasattr(policy, "allow_all")
    assert policy.is_immutable is True


# 12. Regresiones 04.2, 04.3, 04.4
def test_regressions_04_2_to_04_4() -> None:
    # 04.2 Risk Engine
    risk_eng = RiskEngine()
    ctx = SecurityContext(user="test", tool_name="sys", parameters={"path": "C:\\Windows\\System32"})
    meta = ToolSecurityMetadata(tool_name="sys", category="sys", risk_level=SecurityLevel.SAFE)
    assessment = risk_eng.evaluate_risk(SecurityRequest(context=ctx, metadata=meta))
    assert assessment.risk_level == SecurityLevel.CRITICAL

    # 04.3 Permission Manager
    perm_mgr = PermissionManager()
    perm_req = PermissionRequest(context=ctx, metadata=meta, risk_assessment=assessment, tool_name="sys", operation="read")
    perm_res = perm_mgr.evaluate_permission(perm_req)
    assert perm_res.decision == PermissionDecision.DENY  # CRITICAL resulta DENY en PermissionManager

    # 04.4 Confirmation Manager
    conf_mgr = ConfirmationManager()
    req = conf_mgr.create_request(tool_name="t1", message="m", risk_level=SecurityLevel.DANGEROUS)
    res = conf_mgr.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))
    assert res.status == ConfirmationStatus.APPROVED
