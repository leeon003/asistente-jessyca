"""Pruebas de CommandPolicyManager (Subetapa 07.1)."""

from __future__ import annotations

import pytest

from core.command_policy import (
    CommandAllowlistRule,
    CommandPolicyManager,
    DuplicateRuleError,
    RegistryLockedError,
)
from core.permission_manager import PermissionDecision
from core.security_architecture import SecurityLevel


def test_command_policy_manager_defaults_and_evaluation() -> None:
    mgr = CommandPolicyManager()

    # Evaluar comandos por defecto en lista blanca
    ev1 = mgr.evaluate_command("git", ["status"])
    assert ev1.decision == PermissionDecision.ALLOW
    assert ev1.rule_id == "rule-git"

    ev2 = mgr.evaluate_command("dir")
    assert ev2.decision == PermissionDecision.ALLOW

    # Evaluar comando desconocido -> DENY
    ev_unknown = mgr.evaluate_command("unknown_binary_exe")
    assert ev_unknown.decision == PermissionDecision.DENY
    assert "FAIL-SAFE DENY" in ev_unknown.reason


def test_command_policy_manager_register_and_lock() -> None:
    mgr = CommandPolicyManager()

    custom_rule = CommandAllowlistRule(
        rule_id="rule-custom",
        executable="mytool",
        risk_level=SecurityLevel.SAFE,
        decision=PermissionDecision.ALLOW,
    )

    mgr.register_rule(custom_rule)
    assert mgr.get_rule("mytool") is not None

    # Intentar sobrescribir regla inmutable debe fallar si es inmutable
    immutable_rule = CommandAllowlistRule(
        rule_id="rule-immut",
        executable="immut_tool",
        immutable=True,
    )
    mgr.register_rule(immutable_rule)

    with pytest.raises(DuplicateRuleError):
        mgr.register_rule(CommandAllowlistRule(rule_id="rule-dup", executable="immut_tool"))

    # Sellado del registro
    mgr.lock_registry()
    assert mgr.is_locked() is True

    with pytest.raises(RegistryLockedError):
        mgr.register_rule(CommandAllowlistRule(rule_id="rule-locked", executable="newtool"))
