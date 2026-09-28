"""Tests for ARE Failure Diagnosis and Plan Recovery."""

import pytest
from core.are.models import (
    AREPlanProposal,
    ARERuntimeMode,
    AREStepProposal,
)
from core.are.runtime import ARERuntime


def test_failure_diagnosis_and_recovery_proposal():
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    step = AREStepProposal(
        step_id="step_fail",
        action="network_fetch",
        parameters={"url": "http://localhost/test"},
        retry_count=0,
    )
    plan = AREPlanProposal(
        plan_id="plan_test_rec",
        task_id="task_test_rec",
        steps=[step],
    )

    diag, rec = rt.diagnose_and_recover(
        failed_step=step,
        error="ConnectionRefusedError: port 80",
        plan=plan,
        attempt=1,
    )

    assert diag.failure_step_id == "step_fail"
    assert "ConnectionRefusedError" in diag.raw_error or "EXECUTION" in diag.root_cause
    assert diag.confidence > 0.0
    assert rec.plan_id == plan.plan_id
    assert rec.recommended_action in ("RETRY", "ALTERNATIVE_BRANCH", "ASK_USER")


def test_recovery_max_attempts_cap():
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    step = AREStepProposal(
        step_id="step_fail_repeat",
        action="some_action",
        retry_count=2,
    )
    plan = AREPlanProposal(
        plan_id="plan_test_repeat",
        task_id="task_test_repeat",
        steps=[step],
    )

    diag, rec = rt.diagnose_and_recover(
        failed_step=step,
        error="Persistent error",
        plan=plan,
        attempt=3,
    )

    assert rec.recommended_action == "ABORT"
    assert "exceeded" in rec.reason.lower()
