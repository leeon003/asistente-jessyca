"""Pruebas unitarias de políticas configurables por usuario, herramienta, categoría, riesgo, acción y ruta en PolicyManager."""

from __future__ import annotations

from core.policy_rules import ConfigurablePolicyRule, PolicyManager
from core.security import (
    PermissionAction,
    RiskLevel,
    SecurityManager,
    SecurityPolicy,
    SecurityStatus,
    ToolSecurityProfile,
)


def test_policy_rule_by_user() -> None:
    policy_mgr = PolicyManager()
    # Denegar al usuario "guest"
    policy_mgr.add_rule(
        ConfigurablePolicyRule(
            name="BlockGuestUser",
            effect=PermissionAction.DENY,
            users={"guest"},
        )
    )

    sec = SecurityManager(policy_manager=policy_mgr)
    profile = ToolSecurityProfile(name="read_file", category="filesystem", risk_level=RiskLevel.SAFE)

    # Usuario "guest" -> Denegado
    d1 = sec.evaluate(profile, user="guest")
    assert d1.is_allowed is False
    assert d1.status == SecurityStatus.BLOCKED_BY_DOMAIN_POLICY

    # Usuario "admin" -> Permitido
    d2 = sec.evaluate(profile, user="admin")
    assert d2.is_allowed is True
    assert d2.status == SecurityStatus.ALLOWED


def test_policy_rule_by_tool() -> None:
    policy_mgr = PolicyManager()
    # Exigir confirmación (ASK) para la herramienta "delete_database"
    policy_mgr.add_rule(
        ConfigurablePolicyRule(
            name="AskOnDatabaseDelete",
            effect=PermissionAction.ASK,
            tools={"delete_database"},
        )
    )

    sec = SecurityManager(policy_manager=policy_mgr)
    profile = ToolSecurityProfile(name="delete_database", category="system", risk_level=RiskLevel.SAFE)

    decision = sec.evaluate(profile)
    assert decision.is_allowed is False
    assert decision.status == SecurityStatus.REQUIRES_CONFIRMATION
    assert decision.action == PermissionAction.ASK


def test_policy_rule_by_category() -> None:
    policy_mgr = PolicyManager()
    # Denegar categoría "powershell"
    policy_mgr.add_rule(
        ConfigurablePolicyRule(
            name="BlockPowerShellCategory",
            effect=PermissionAction.DENY,
            categories={"powershell"},
        )
    )

    sec = SecurityManager(policy_manager=policy_mgr)
    ps_profile = ToolSecurityProfile(name="run_ps_script", category="powershell", risk_level=RiskLevel.SAFE)
    fs_profile = ToolSecurityProfile(name="read_text", category="filesystem", risk_level=RiskLevel.SAFE)

    assert sec.evaluate(ps_profile).is_allowed is False
    assert sec.evaluate(fs_profile).is_allowed is True


def test_policy_rule_by_risk() -> None:
    policy_mgr = PolicyManager()
    # Bloquear herramientas cuyo riesgo sea WARNING o superior (min_risk_level=WARNING)
    policy_mgr.add_rule(
        ConfigurablePolicyRule(
            name="LimitRiskToSafe",
            effect=PermissionAction.DENY,
            min_risk_level=RiskLevel.WARNING,
        )
    )

    sec = SecurityManager(policy_manager=policy_mgr)
    warning_profile = ToolSecurityProfile(name="warn_cmd", category="general", risk_level=RiskLevel.WARNING)
    safe_profile = ToolSecurityProfile(name="safe_cmd", category="general", risk_level=RiskLevel.SAFE)

    decision_warn = sec.evaluate(warning_profile)
    assert decision_warn.is_allowed is False

    decision_safe = sec.evaluate(safe_profile)
    assert decision_safe.is_allowed is True


def test_policy_rule_by_action() -> None:
    policy_mgr = PolicyManager()
    # Exigir permiso temporal ALLOW_ONCE para acciones de tipo "delete"
    policy_mgr.add_rule(
        ConfigurablePolicyRule(
            name="RequireAllowOnceOnDelete",
            effect=PermissionAction.ALLOW_ONCE,
            actions={"delete"},
        )
    )

    sec = SecurityManager(policy_manager=policy_mgr)
    profile = ToolSecurityProfile(name="remove_item", category="filesystem", risk_level=RiskLevel.SAFE)

    # Invocación con acción "delete" -> Retorna ALLOW_ONCE
    decision = sec.evaluate(profile, action="delete")
    assert decision.is_allowed is True
    assert decision.action == PermissionAction.ALLOW_ONCE


def test_policy_rule_by_path_pattern() -> None:
    policy_mgr = PolicyManager()
    # Denegar cualquier ejecución que intente operar en rutas C:\Windows\*
    policy_mgr.add_rule(
        ConfigurablePolicyRule(
            name="ProtectSystemPath",
            effect=PermissionAction.DENY,
            path_patterns={"C:\\Windows\\*"},
        )
    )

    sec = SecurityManager(policy=SecurityPolicy(require_admin_for_critical=False), policy_manager=policy_mgr)
    profile = ToolSecurityProfile(name="inspect_path", category="filesystem", risk_level=RiskLevel.SAFE)

    # Argumentos dentro de C:\Temp -> Permitido
    d1 = sec.evaluate(profile, arguments={"path": "C:\\Temp\\test.log"})
    assert d1.is_allowed is True

    # Argumentos dentro de C:\Windows\System32 -> Denegado por regla de ruta
    d2 = sec.evaluate(profile, arguments={"path": "C:\\Windows\\System32\\cmd.exe"})
    assert d2.is_allowed is False
    assert d2.status == SecurityStatus.BLOCKED_BY_DOMAIN_POLICY
