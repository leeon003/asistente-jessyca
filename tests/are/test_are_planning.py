"""Tests for ARE Task Decomposition and Planning."""

import pytest
from core.are.models import ARERuntimeMode
from core.are.runtime import ARERuntime


def test_decompose_and_plan_structure():
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    plan = rt.decompose_and_plan(
        goal="investiga el mercado y después resume los hallazgos",
        context={"domain": "tech"},
    )

    assert plan.plan_id.startswith("plan")
    assert plan.task_id.startswith("task")
    assert len(plan.steps) >= 2
    assert "ARE" in plan.provenance
    assert plan.integrity_hash != ""

    # Verify steps have proper attributes
    for step in plan.steps:
        assert step.step_id
        assert step.action
        assert isinstance(step.dependencies, list)
        assert isinstance(step.required_capabilities, list)


def test_evaluate_plan_feasibility():
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    plan = rt.decompose_and_plan(
        goal="convierte documento y analiza",
        context={},
    )
    eval_res = rt.evaluate_plan(plan)
    assert eval_res.get("feasible") is True
    assert eval_res.get("plan_id") == plan.plan_id
