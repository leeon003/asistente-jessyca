"""Pruebas unitarias de políticas de seguridad, permisos jerárquicos y comodines en SecurityManager."""

from __future__ import annotations

from core.security import (
    RiskLevel,
    SecurityManager,
    SecurityPolicy,
    SecurityStatus,
    ToolSecurityProfile,
    check_hierarchical_permission,
)


def test_hierarchical_permission_wildcards() -> None:
    granted = {"filesystem.*", "network.ping"}

    assert check_hierarchical_permission(granted, "filesystem.read") is True
    assert check_hierarchical_permission(granted, "filesystem.write") is True
    assert check_hierarchical_permission(granted, "network.ping") is True
    assert check_hierarchical_permission(granted, "network.traceroute") is False
    assert check_hierarchical_permission(granted, "system.admin") is False

    # Comodín global
    global_granted = {"*"}
    assert check_hierarchical_permission(global_granted, "system.admin") is True


def test_security_policy_max_allowed_risk() -> None:
    # Política estricta: Riesgo máximo permitido = SAFE
    strict_policy = SecurityPolicy(max_allowed_risk=RiskLevel.SAFE)
    sec = SecurityManager(policy=strict_policy)

    safe_profile = ToolSecurityProfile(name="safe_tool", category="general", risk_level=RiskLevel.SAFE)
    warning_profile = ToolSecurityProfile(name="warn_tool", category="general", risk_level=RiskLevel.WARNING)

    # SAFE permitido
    d1 = sec.evaluate(safe_profile)
    assert d1.is_allowed is True
    assert d1.status == SecurityStatus.ALLOWED

    # WARNING bloqueado por excede el riesgo máximo permitido por la política
    d2 = sec.evaluate(warning_profile)
    assert d2.is_allowed is False
    assert d2.status == SecurityStatus.BLOCKED_BY_POLICY_MAX_RISK


def test_security_policy_blocked_domains() -> None:
    policy = SecurityPolicy(blocked_domains={"powershell", "desktop"})
    sec = SecurityManager(policy=policy)

    ps_profile = ToolSecurityProfile(name="ps_exec", category="powershell", risk_level=RiskLevel.SAFE)
    fs_profile = ToolSecurityProfile(name="fs_read", category="filesystem", risk_level=RiskLevel.SAFE)

    # Dominio PowerShell bloqueado
    d1 = sec.evaluate(ps_profile)
    assert d1.is_allowed is False
    assert d1.status == SecurityStatus.BLOCKED_BY_DOMAIN_POLICY

    # Dominio Filesystem permitido
    d2 = sec.evaluate(fs_profile)
    assert d2.is_allowed is True
    assert d2.status == SecurityStatus.ALLOWED


def test_permission_grant_with_wildcards() -> None:
    sec = SecurityManager()
    profile = ToolSecurityProfile(
        name="write_file_tool",
        category="filesystem",
        risk_level=RiskLevel.SAFE,
        required_permissions=["filesystem.write"],
    )

    # Evaluación inicial sin permisos -> Denegado
    d1 = sec.evaluate(profile)
    assert d1.is_allowed is False
    assert d1.status == SecurityStatus.DENIED_MISSING_PERMISSIONS

    # Otorgar permiso con comodín de dominio
    sec.grant_permission("filesystem.*")

    # Evaluación con permiso wildcard -> Permitido
    d2 = sec.evaluate(profile)
    assert d2.is_allowed is True
    assert d2.status == SecurityStatus.ALLOWED
