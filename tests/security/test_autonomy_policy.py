"""Pruebas dedicadas para AutonomyPolicy y AutonomyLevel (Subetapa 16.2)."""

from __future__ import annotations

from core.autonomy.autonomy_decision import AutonomyDecisionValue
from core.autonomy.autonomy_level import AutonomyLevel
from core.autonomy.autonomy_policy import AutonomyEvaluationContext, AutonomyPolicy


def test_autonomy_level_0_observe_denies_all() -> None:
    policy = AutonomyPolicy()
    ctx = AutonomyEvaluationContext(
        task_id="t-1",
        tool_name="windows.files",
        operation="write",
    )
    decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_0_OBSERVE)
    assert decision.decision == AutonomyDecisionValue.DENY


def test_autonomy_level_1_suggest_requires_review() -> None:
    policy = AutonomyPolicy()
    ctx = AutonomyEvaluationContext(
        task_id="t-2",
        tool_name="windows.files",
        operation="read_file",
    )
    decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_1_SUGGEST)
    assert decision.decision == AutonomyDecisionValue.REQUIRE_REVIEW


def test_autonomy_level_2_allows_safe_actions() -> None:
    policy = AutonomyPolicy()
    ctx = AutonomyEvaluationContext(
        task_id="t-3",
        tool_name="windows.files",
        operation="read_file",
    )
    decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION)
    assert decision.decision == AutonomyDecisionValue.ALLOW


def test_dangerous_action_requires_confirmation() -> None:
    policy = AutonomyPolicy()
    ctx = AutonomyEvaluationContext(
        task_id="t-4",
        tool_name="windows.process",
        operation="kill",
    )
    decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED)
    assert decision.decision == AutonomyDecisionValue.REQUIRE_CONFIRMATION


def test_unregistered_capability_denied() -> None:
    policy = AutonomyPolicy()
    ctx = AutonomyEvaluationContext(
        task_id="t-5",
        tool_name="windows.shell",
        operation="powershell",
    )
    decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY)
    assert decision.decision == AutonomyDecisionValue.REQUIRE_CONFIRMATION
