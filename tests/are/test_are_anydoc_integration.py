"""Tests for ARE Subordinated AnyDoc Integration."""

import pytest
from core.are.models import (
    AREPlanProposal,
    ARERuntimeMode,
    AREStepProposal,
)
from core.are.runtime import ARERuntime
from core.jde.runtime_binding import JDERuntimeBinding, JDERuntimeVerdict, JDERuntimeVerdictType
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest


class AnyDocMockAgent:
    def __init__(self):
        self.jde_runtime_binding = JDERuntimeBinding()
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


def test_are_anydoc_allowed_proposal_governed_by_jde():
    agent = AnyDocMockAgent()
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)

    req = JessycaRequest(request_id="req_anydoc_1", user_input="convierte documento a markdown y luego analiza texto")
    resp = rt.execute_complex_task(
        agent=agent,
        req=req,
        goal="convierte documento a markdown y luego analiza texto",
    )
    assert resp.status in (AgentExecutionState.COMPLETED, AgentExecutionState.AWAITING_CONFIRMATION)


def test_are_anydoc_forbidden_capabilities_rejected():
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)

    # ARE proposal trying forbidden external OCR or upload
    for forbidden_cap in ["external_ocr", "external_upload", "arbitrary_shell", "admin", "outbound_network"]:
        step = AREStepProposal(
            step_id=f"step_{forbidden_cap}",
            action="anydoc.custom_action",
            parameters={"cap": forbidden_cap},
            required_capabilities=[forbidden_cap],
        )
        plan = AREPlanProposal(
            plan_id=f"plan_{forbidden_cap}",
            task_id=f"task_{forbidden_cap}",
            steps=[step],
        )
        eval_res = rt.evaluate_plan(plan)
        assert eval_res.get("feasible") is False
        assert "forbidden" in eval_res.get("reason", "").lower()
