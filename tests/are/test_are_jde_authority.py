"""Tests for JDE Authority over ARE proposals."""

import pytest
from core.are.models import ARERuntimeMode
from core.are.runtime import ARERuntime
from core.jde.runtime_binding import JDERuntimeBinding, JDERuntimeVerdict, JDERuntimeVerdictType
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest


class MockAgent:
    def __init__(self, jde_binding=None):
        self.jde_runtime_binding = jde_binding or JDERuntimeBinding()
        self.context_manager = None
        self._latest_metrics = None

    def _execute_skill_action(self, *args, **kwargs):
        return None

    def _execute_app_action(self, *args, **kwargs):
        return True, "Executed app"

    def _execute_file_action(self, *args, **kwargs):
        return True, "Executed file"

    def _log_turn_experience(self, *args, **kwargs):
        pass

    def _observe_shadow_turn(self, *args, **kwargs):
        pass


def test_jde_authority_deny_stops_are_plan():
    # Setup mock JDE that returns DENY
    class DenyJDE(JDERuntimeBinding):
        def evaluate(self, *args, **kwargs):
            return JDERuntimeVerdict(
                verdict=JDERuntimeVerdictType.DENY,
                reason="Policy violation detected by JDE",
                action=kwargs.get("action", "test_action"),
                tool=kwargs.get("tool", "test_tool"),
            )

    agent = MockAgent(jde_binding=DenyJDE())
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)

    req = JessycaRequest(request_id="req_test_deny", user_input="investiga y borra archivos")
    resp = rt.execute_complex_task(
        agent=agent,
        req=req,
        goal="investiga y borra archivos",
    )

    assert resp.success is False
    assert resp.status == AgentExecutionState.FAILED
    assert "DENY" in resp.response_text or "denegad" in resp.response_text.lower()
    assert len(resp.tools_executed) == 0


def test_jde_authority_require_review_blocks_execution():
    class ReviewJDE(JDERuntimeBinding):
        def evaluate(self, *args, **kwargs):
            return JDERuntimeVerdict(
                verdict=JDERuntimeVerdictType.REQUIRE_REVIEW,
                reason="Sensitive action requires confirmation",
                action=kwargs.get("action", "test_action"),
                tool=kwargs.get("tool", "test_tool"),
            )

    agent = MockAgent(jde_binding=ReviewJDE())
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)

    req = JessycaRequest(request_id="req_test_review", user_input="investiga y modifica sistema")
    resp = rt.execute_complex_task(
        agent=agent,
        req=req,
        goal="investiga y modifica sistema",
        user_confirmed=False,
    )

    assert resp.success is True
    assert resp.status == AgentExecutionState.AWAITING_CONFIRMATION
    assert resp.requires_confirmation is True
    assert len(resp.tools_executed) == 0
