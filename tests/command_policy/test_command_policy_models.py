"""Pruebas de los modelos inmutables de políticas de comandos (Subetapa 07.1)."""

from __future__ import annotations

import pytest

from core.command_policy import CommandAllowlistRule, CommandPolicyEvaluation
from core.permission_manager import PermissionDecision
from core.security_architecture import SecurityLevel


def test_command_allowlist_rule_immutability_and_dict() -> None:
    rule = CommandAllowlistRule(
        rule_id="rule-git-status",
        executable="git",
        allowed_arguments_patterns=("status",),
        risk_level=SecurityLevel.SAFE,
        decision=PermissionDecision.ALLOW,
        description="Regla git status",
        immutable=True,
    )

    assert rule.executable == "git"
    assert rule.allowed_arguments_patterns == ("status",)

    with pytest.raises(AttributeError):
        rule.executable = "cmd"  # type: ignore

    d = rule.to_dict()
    assert d["rule_id"] == "rule-git-status"
    assert d["risk_level"] == "SAFE"


def test_command_policy_evaluation_immutability() -> None:
    ev = CommandPolicyEvaluation(
        executable="git",
        arguments=("status",),
        decision=PermissionDecision.ALLOW,
        risk_level=SecurityLevel.SAFE,
        reason="Comando autorizado por regla",
        rule_id="rule-git-status",
    )

    assert ev.decision == PermissionDecision.ALLOW
    assert ev.to_dict()["rule_id"] == "rule-git-status"

    with pytest.raises(AttributeError):
        ev.decision = PermissionDecision.DENY  # type: ignore
