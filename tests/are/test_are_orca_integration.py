"""Tests for ARE Subordinated ORCA/ADE Integration."""

import pytest
from core.are.models import (
    AREPlanProposal,
    ARERuntimeMode,
    AREStepProposal,
)
from core.are.runtime import ARERuntime
from core.jde.runtime_binding import JDERuntimeBinding, JDERuntimeVerdict, JDERuntimeVerdictType
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest


class OrcaMockAgent:
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


def test_are_orca_subordination_with_jde_allow():
    agent = OrcaMockAgent()
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)

    req = JessycaRequest(request_id="req_orca_1", user_input="ejecuta orquestación de agentes con worktree")
    resp = rt.execute_complex_task(
        agent=agent,
        req=req,
        goal="ejecuta orquestación de agentes con worktree",
    )
    assert resp.status in (AgentExecutionState.COMPLETED, AgentExecutionState.AWAITING_CONFIRMATION)


def test_are_cannot_bypass_jde_for_orca():
    class OrcaDenyJDE(JDERuntimeBinding):
        def evaluate(self, *args, **kwargs):
            return JDERuntimeVerdict(
                verdict=JDERuntimeVerdictType.DENY,
                reason="ORCA task creation denied by JDE policy",
                action=kwargs.get("action", "test_action"),
                tool=kwargs.get("tool", "test_tool"),
            )

    agent = OrcaMockAgent()
    agent.jde_runtime_binding = OrcaDenyJDE()
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)

    req = JessycaRequest(request_id="req_orca_deny", user_input="ejecuta orquestación de agentes")
    resp = rt.execute_complex_task(
        agent=agent,
        req=req,
        goal="ejecuta orquestación de agentes",
    )
    assert resp.success is False
    assert "DENY" in resp.response_text or "denegad" in resp.response_text.lower()
    assert len(resp.tools_executed) == 0
