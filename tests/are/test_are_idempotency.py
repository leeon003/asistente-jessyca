"""Tests for ARE Idempotency Guard Integration."""

import pytest
from core.are.models import (
    AREPlanProposal,
    ARERuntimeMode,
    AREStepProposal,
)
from core.are.runtime import ARERuntime
from core.execution.idempotency_guard import ExecutionFingerprint, get_idempotency_guard
from core.jde.runtime_binding import JDERuntimeBinding
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest


class IdemMockAgent:
    def __init__(self):
        self.jde_runtime_binding = JDERuntimeBinding()
        self.context_manager = None
        self._latest_metrics = None
        self.exec_counts = 0

    def _execute_skill_action(self, *args, **kwargs):
        return None

    def _execute_app_action(self, *args, **kwargs):
        self.exec_counts += 1
        return True, "Executed"

    def _execute_file_action(self, *args, **kwargs):
        self.exec_counts += 1
        return True, "Executed file"

    def _log_turn_experience(self, *args, **kwargs):
        pass

    def _observe_shadow_turn(self, *args, **kwargs):
        pass


def test_are_step_idempotency_cached():
    agent = IdemMockAgent()
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    guard = get_idempotency_guard()

    # Pre-register step execution with status SUCCEEDED in guard
    fp = ExecutionFingerprint(
        session_id="task_idem_1",
        request_id="task_idem_1_step_1_prep",
        intent="system.check",
        skill="system.check",
        action="system.check",
        target="abre notepad y prepara notas",
    )
    acquired, rec = guard.acquire_execution(fp)
    assert acquired is True
    guard.record_verification_completed(rec.execution_id, "SUCCEEDED", "Pre-executed")

    req = JessycaRequest(request_id="task_idem_1", user_input="abre notepad y prepara notas")

    # When executing via ARE, it must detect idempotency hit
    resp = rt.execute_complex_task(agent=agent, req=req, goal="abre notepad y prepara notas")
    assert resp.success is True
    # The actual execution was not called for app action
    assert agent.exec_counts == 0
