"""Pruebas unitarias completas del Security Manager independiente."""

from __future__ import annotations

from core.security import (
    RiskLevel,
    SecurityManager,
    SecurityStatus,
    ToolSecurityProfile,
)


def test_read_only_and_safe_tools_allowed() -> None:
    sec = SecurityManager()
    profile = ToolSecurityProfile(
        name="read_file",
        category="file",
        risk_level=RiskLevel.READ_ONLY,
    )
    decision = sec.evaluate(profile)
    assert decision.is_allowed is True
    assert decision.status == SecurityStatus.ALLOWED


def test_dangerous_and_critical_tools_require_confirmation() -> None:
    sec = SecurityManager()
    profile = ToolSecurityProfile(
        name="delete_database",
        category="system",
        risk_level=RiskLevel.CRITICAL,
    )
    decision = sec.evaluate(profile)
    assert decision.is_allowed is False
    assert decision.status == SecurityStatus.REQUIRES_CONFIRMATION


def test_blacklist_blocking() -> None:
    sec = SecurityManager()
    profile = ToolSecurityProfile(name="dangerous_cmd", category="system")

    sec.add_to_blacklist("dangerous_cmd")
    decision = sec.evaluate(profile)
    assert decision.is_allowed is False
    assert decision.status == SecurityStatus.BLOCKED_BY_BLACKLIST

    sec.remove_from_blacklist("dangerous_cmd")
    decision = sec.evaluate(profile)
    assert decision.is_allowed is True


def test_strict_whitelist_mode() -> None:
    sec = SecurityManager(strict_whitelist_mode=True)
    profile1 = ToolSecurityProfile(name="allowed_tool", category="system")
    profile2 = ToolSecurityProfile(name="unknown_tool", category="system")

    sec.add_to_whitelist("allowed_tool")

    d1 = sec.evaluate(profile1)
    assert d1.is_allowed is True

    d2 = sec.evaluate(profile2)
    assert d2.is_allowed is False
    assert d2.status == SecurityStatus.BLOCKED_NOT_IN_WHITELIST


def test_dynamic_blocking() -> None:
    sec = SecurityManager()
    profile = ToolSecurityProfile(name="dynamic_tool", category="automation")

    sec.block_tool("dynamic_tool")
    d1 = sec.evaluate(profile)
    assert d1.is_allowed is False
    assert d1.status == SecurityStatus.BLOCKED_DYNAMICALLY

    sec.unblock_tool("dynamic_tool")
    d2 = sec.evaluate(profile)
    assert d2.is_allowed is True


def test_missing_permissions() -> None:
    sec = SecurityManager()
    profile = ToolSecurityProfile(
        name="admin_tool",
        category="system",
        required_permissions=["system.admin", "registry.write"],
    )

    # Inicialmente faltan permisos
    d1 = sec.evaluate(profile)
    assert d1.is_allowed is False
    assert d1.status == SecurityStatus.DENIED_MISSING_PERMISSIONS

    # Otorgar permisos
    sec.grant_permission("system.admin")
    sec.grant_permission("registry.write")

    d2 = sec.evaluate(profile)
    assert d2.is_allowed is True
    assert d2.status == SecurityStatus.ALLOWED


def test_user_confirmation_flow() -> None:
    sec = SecurityManager()
    profile = ToolSecurityProfile(
        name="format_disk",
        category="system",
        risk_level=RiskLevel.CRITICAL,
    )

    # Evaluación previa
    d1 = sec.evaluate(profile)
    assert d1.status == SecurityStatus.REQUIRES_CONFIRMATION

    # Usuario aprueba
    d2 = sec.confirm_execution(profile, user_approved=True)
    assert d2.is_allowed is True
    assert d2.status == SecurityStatus.ALLOWED

    # Usuario rechaza
    d3 = sec.confirm_execution(profile, user_approved=False)
    assert d3.is_allowed is False


def test_audit_log_tracking() -> None:
    sec = SecurityManager()
    p1 = ToolSecurityProfile(name="t1", category="cat1")
    p2 = ToolSecurityProfile(name="t2", category="cat2", risk_level=RiskLevel.DANGEROUS)

    sec.evaluate(p1)
    sec.evaluate(p2)

    log = sec.get_audit_log()
    assert len(log) == 2
    assert log[0].tool_name == "t1"
    assert log[0].status == SecurityStatus.ALLOWED
    assert log[1].tool_name == "t2"
    assert log[1].status == SecurityStatus.REQUIRES_CONFIRMATION
