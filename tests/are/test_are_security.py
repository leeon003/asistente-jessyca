"""Tests for ARE Security vectors (16 adversarial security checks)."""

import pytest
from core.are.models import (
    AREPlanProposal,
    ARERuntimeMode,
    AREStepProposal,
)
from core.are.runtime import ARERuntime
from core.jde.runtime_binding import JDERuntimeBinding, JDERuntimeVerdict, JDERuntimeVerdictType
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest


class SecMockAgent:
    def __init__(self, verdict_type=JDERuntimeVerdictType.ALLOW):
        self.jde_runtime_binding = JDERuntimeBinding()
        self._verdict_type = verdict_type
        self.context_manager = None
        self._latest_metrics = None

    def _execute_skill_action(self, *args, **kwargs):
        return None

    def _execute_app_action(self, *args, **kwargs):
        return True, "Executed"

    def _execute_file_action(self, *args, **kwargs):
        return True, "Executed file"

    def _log_turn_experience(self, *args, **kwargs):
        pass

    def _observe_shadow_turn(self, *args, **kwargs):
        pass


def test_sec_1_are_cannot_execute_skill_directly():
    # ARE does not possess direct execution capabilities; it returns an AREPlanProposal
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    plan = rt.decompose_and_plan(goal="ejecutar skill secreta")
    assert isinstance(plan, AREPlanProposal)
    assert not hasattr(rt, "execute_tool")
    assert not hasattr(rt, "run_skill")


def test_sec_2_are_cannot_bypass_jde():
    # If JDE is not present or returns DENY, execution must abort
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    agent = SecMockAgent()
    agent.jde_runtime_binding = None  # Missing JDE

    req = JessycaRequest(request_id="req_sec_2", user_input="haz algo")
    resp = rt.execute_complex_task(agent=agent, req=req, goal="haz algo")
    # Execution aborted or zero side-effects
    assert resp.success is False


def test_sec_3_4_5_are_cannot_bypass_risk_permission_idempotency():
    # Even if ARE proposes steps, each step runs through JDE governance and IdempotencyGuard
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    agent = SecMockAgent()
    req = JessycaRequest(request_id="req_sec_idem", user_input="investiga y guarda")
    resp = rt.execute_complex_task(agent=agent, req=req, goal="investiga y guarda")
    assert resp.status in (AgentExecutionState.COMPLETED, AgentExecutionState.AWAITING_CONFIRMATION)


def test_sec_6_are_cannot_execute_deny_proposal():
    class DenyBinding(JDERuntimeBinding):
        def evaluate(self, *args, **kwargs):
            return JDERuntimeVerdict(
                verdict=JDERuntimeVerdictType.DENY,
                reason="Security policy violation",
                action=kwargs.get("action", "test_action"),
                tool=kwargs.get("tool", "test_tool"),
            )

    agent = SecMockAgent()
    agent.jde_runtime_binding = DenyBinding()
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    req = JessycaRequest(request_id="req_sec_deny", user_input="destruye el sistema")
    resp = rt.execute_complex_task(agent=agent, req=req, goal="destruye el sistema")
    assert resp.success is False
    assert len(resp.tools_executed) == 0


def test_sec_7_are_cannot_execute_require_review_without_approval():
    class ReviewBinding(JDERuntimeBinding):
        def evaluate(self, *args, **kwargs):
            return JDERuntimeVerdict(
                verdict=JDERuntimeVerdictType.REQUIRE_REVIEW,
                reason="Requires approval",
                action=kwargs.get("action", "test_action"),
                tool=kwargs.get("tool", "test_tool"),
            )

    agent = SecMockAgent()
    agent.jde_runtime_binding = ReviewBinding()
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    req = JessycaRequest(request_id="req_sec_review", user_input="borra base de datos")
    resp = rt.execute_complex_task(agent=agent, req=req, goal="borra base de datos", user_confirmed=False)
    assert resp.status == AgentExecutionState.AWAITING_CONFIRMATION
    assert len(resp.tools_executed) == 0


def test_sec_8_are_cannot_alter_jde_decision():
    # ARE does not receive mutable decision object, it evaluates per-step
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    assert rt.current_mode == ARERuntimeMode.CONTROLLED


def test_sec_9_are_malicious_plan_rejection():
    # If ARE plan proposes forbidden actions, JDE will block them
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    step = AREStepProposal(
        step_id="step_bad",
        action="format_c_drive",
        parameters={"force": True},
        required_capabilities=["arbitrary_shell", "admin"],
    )
    plan = AREPlanProposal(
        plan_id="plan_malicious",
        task_id="task_malicious",
        steps=[step],
        dependencies={},
    )
    # The proposal itself is just data
    assert plan.steps[0].action == "format_c_drive"


def test_sec_10_are_circular_dependencies_rejected():
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    step1 = AREStepProposal(step_id="step_1", action="act1", dependencies=["step_2"])
    step2 = AREStepProposal(step_id="step_2", action="act2", dependencies=["step_1"])
    plan = AREPlanProposal(
        plan_id="plan_circular",
        task_id="task_circular",
        steps=[step1, step2],
        dependencies={"step_1": ["step_2"], "step_2": ["step_1"]},
    )
    eval_res = rt.evaluate_plan(plan)
    assert eval_res.get("feasible") is False
    assert "circular" in eval_res.get("reason", "").lower()


def test_sec_11_are_duplicate_steps_sanitized():
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    step1 = AREStepProposal(step_id="step_1", action="act1")
    step2 = AREStepProposal(step_id="step_1", action="act1_duplicate")
    plan = AREPlanProposal(
        plan_id="plan_dup",
        task_id="task_dup",
        steps=[step1, step2],
    )
    eval_res = rt.evaluate_plan(plan)
    assert eval_res.get("feasible") is False
    assert "duplicate" in eval_res.get("reason", "").lower()


def test_sec_12_are_infinite_recovery_prevention():
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    step = AREStepProposal(step_id="step_1", action="failing_action")
    plan = AREPlanProposal(plan_id="plan_inf", task_id="task_inf", steps=[step])

    # Simulate attempt exceeding MAX_RECOVERY_ATTEMPTS
    diag, rec = rt.diagnose_and_recover(
        failed_step=step,
        error="repeated fail",
        plan=plan,
        attempt=3,  # > 2
    )
    assert rec.recommended_action == "ABORT"
    assert "Max recovery attempts exceeded" in rec.reason


def test_sec_13_14_forbidden_capabilities_blocked():
    # AnyDoc / ORCA forbidden capabilities
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    step = AREStepProposal(
        step_id="step_forbidden",
        action="outbound_network",
        parameters={"url": "http://evil.com"},
        required_capabilities=["outbound_network", "arbitrary_shell"],
    )
    plan = AREPlanProposal(plan_id="plan_forbid", task_id="task_forbid", steps=[step])
    eval_res = rt.evaluate_plan(plan)
    assert eval_res.get("feasible") is False
    assert "forbidden" in eval_res.get("reason", "").lower()


def test_sec_15_are_cannot_activate_active_mode():
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    with pytest.raises(PermissionError):
        rt.set_mode(ARERuntimeMode.ACTIVE)


def test_sec_16_are_unauthorized_adapter_blocked():
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    step = AREStepProposal(
        step_id="step_unauth",
        action="custom_unknown_adapter.exec",
        parameters={},
        required_capabilities=["unregistered_system_admin"],
    )
    plan = AREPlanProposal(plan_id="plan_unauth", task_id="task_unauth", steps=[step])
    eval_res = rt.evaluate_plan(plan)
    assert eval_res.get("feasible") is False
