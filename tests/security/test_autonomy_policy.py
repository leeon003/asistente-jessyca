"""Pruebas dedicadas para AutonomyPolicy y AutonomyLevel (Subetapa 16.1)."""

from __future__ import annotations

from core.autonomy_policy import (
    AutonomyDecision,
    AutonomyLevel,
    AutonomyPolicy,
)
from core.risk_engine import SecurityLevel


def test_autonomy_level_0_observe_denies_all() -> None:
    policy = AutonomyPolicy()
    decision = policy.evaluate_autonomy(
        capability="windows.files.read",
        current_autonomy_level=AutonomyLevel.LEVEL_0_OBSERVE,
    )
    assert decision == AutonomyDecision.DENY


def test_autonomy_level_1_suggest_requires_review() -> None:
    policy = AutonomyPolicy()
    decision = policy.evaluate_autonomy(
        capability="windows.files.read",
        current_autonomy_level=AutonomyLevel.LEVEL_1_SUGGEST,
    )
    assert decision == AutonomyDecision.REQUIRE_REVIEW


def test_autonomy_level_2_allows_safe_actions() -> None:
    policy = AutonomyPolicy()
    decision = policy.evaluate_autonomy(
        capability="windows.files.read",
        current_autonomy_level=AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION,
        risk_level=SecurityLevel.SAFE,
    )
    assert decision == AutonomyDecision.ALLOW


def test_dangerous_action_requires_confirmation() -> None:
    policy = AutonomyPolicy()
    decision = policy.evaluate_autonomy(
        capability="windows.files.delete",
        current_autonomy_level=AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED,
        risk_level=SecurityLevel.DANGEROUS,
    )
    assert decision == AutonomyDecision.REQUIRE_CONFIRMATION


def test_unregistered_capability_denied() -> None:
    policy = AutonomyPolicy()
    decision = policy.evaluate_autonomy(
        capability="unregistered.dangerous.tool",
        current_autonomy_level=AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY,
    )
    assert decision == AutonomyDecision.DENY
