"""Pruebas unitarias completas de los estados de respuesta y consentimiento PermissionAction (ALLOW, DENY, ASK, ALLOW_ONCE, ALWAYS_ALLOW)."""

from __future__ import annotations

from core.security import (
    PermissionAction,
    RiskLevel,
    SecurityManager,
    SecurityPolicy,
    SecurityStatus,
    ToolSecurityProfile,
)


def test_permission_action_allow() -> None:
    sec = SecurityManager()
    profile = ToolSecurityProfile(name="safe_tool", category="general", risk_level=RiskLevel.SAFE)

    decision = sec.process_user_action(profile, PermissionAction.ALLOW)
    assert decision.is_allowed is True
    assert decision.status == SecurityStatus.ALLOWED
    assert decision.action == PermissionAction.ALLOW


def test_permission_action_deny() -> None:
    sec = SecurityManager()
    profile = ToolSecurityProfile(name="blocked_tool", category="general", risk_level=RiskLevel.SAFE)

    decision = sec.process_user_action(profile, PermissionAction.DENY)
    assert decision.is_allowed is False
    assert decision.status == SecurityStatus.BLOCKED_BY_BLACKLIST
    assert decision.action == PermissionAction.DENY


def test_permission_action_ask() -> None:
    sec = SecurityManager()
    profile = ToolSecurityProfile(name="ask_tool", category="general", risk_level=RiskLevel.WARNING)

    decision = sec.process_user_action(profile, PermissionAction.ASK)
    assert decision.is_allowed is False
    assert decision.status == SecurityStatus.REQUIRES_CONFIRMATION
    assert decision.requires_user_confirmation is True
    assert decision.action == PermissionAction.ASK


def test_permission_action_allow_once() -> None:
    sec = SecurityManager(policy=SecurityPolicy(require_admin_for_critical=False))
    profile = ToolSecurityProfile(name="one_time_tool", category="filesystem", risk_level=RiskLevel.DANGEROUS)

    # 1. Otorgar permiso temporal ALLOW_ONCE
    decision1 = sec.process_user_action(profile, PermissionAction.ALLOW_ONCE)
    assert decision1.is_allowed is True
    assert decision1.action == PermissionAction.ALLOW_ONCE

    # 2. Primera llamada -> Se consume el permiso temporal y se aprueba
    eval1 = sec.evaluate(profile)
    assert eval1.is_allowed is True
    assert eval1.action == PermissionAction.ALLOW_ONCE

    # 3. Segunda llamada -> El permiso temporal expiró, vuelve a requerir confirmación
    eval2 = sec.evaluate(profile)
    assert eval2.is_allowed is False
    assert eval2.status == SecurityStatus.REQUIRES_CONFIRMATION


def test_permission_action_always_allow() -> None:
    sec = SecurityManager(strict_whitelist_mode=True)
    profile = ToolSecurityProfile(
        name="permanent_tool",
        category="filesystem",
        risk_level=RiskLevel.SAFE,
        required_permissions=["filesystem.read"],
    )

    # Inicialmente bloqueado en modo estricto
    eval_initial = sec.evaluate(profile)
    assert eval_initial.is_allowed is False

    # Procesar ALWAYS_ALLOW
    decision = sec.process_user_action(profile, PermissionAction.ALWAYS_ALLOW)
    assert decision.is_allowed is True
    assert decision.action == PermissionAction.ALWAYS_ALLOW

    # Primera y segunda llamada autorizadas permanentemente
    eval1 = sec.evaluate(profile)
    eval2 = sec.evaluate(profile)
    assert eval1.is_allowed is True
    assert eval2.is_allowed is True
