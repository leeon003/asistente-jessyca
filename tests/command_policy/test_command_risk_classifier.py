"""Pruebas del CommandRiskClassifier (Subetapa 07.1)."""

from __future__ import annotations

from core.command_policy import CommandAllowlistRule, CommandRiskClassifier
from core.security_architecture import SecurityLevel


def test_command_risk_classifier_rules() -> None:
    safe_rule = CommandAllowlistRule(
        rule_id="r1",
        executable="git",
        risk_level=SecurityLevel.SAFE,
    )
    assert CommandRiskClassifier.classify("git", ("status",), safe_rule) == SecurityLevel.SAFE

    warning_rule = CommandAllowlistRule(
        rule_id="r2",
        executable="git",
        risk_level=SecurityLevel.WARNING,
    )
    assert CommandRiskClassifier.classify("git", ("commit",), warning_rule) == SecurityLevel.WARNING

    # Sin regla (UNKNOWN) debe ser CRITICAL
    assert CommandRiskClassifier.classify("unknown", (), None) == SecurityLevel.CRITICAL
