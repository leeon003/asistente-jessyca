"""Tests for End-to-End ARE Integration Scenarios (Cases A through G)."""

import pytest
from core.are.models import ARERuntimeMode
from core.are.runtime import ARERuntime
from core.jde.runtime_binding import JDERuntimeBinding, JDERuntimeVerdict, JDERuntimeVerdictType
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest


class E2EMockAgent(JessycaLocalAgent):
    def __init__(self, jde_binding=None):
        super().__init__(jde_runtime_binding=jde_binding)

    def _execute_app_action(self, *args, **kwargs):
        return True, "App executed successfully"

    def _execute_file_action(self, *args, **kwargs):
        return True, "File executed successfully"


def test_case_a_simple_task_bypasses_are():
    # CASO A — TAREA SIMPLE: ARE no debe intervenir innecesariamente
    from unittest.mock import patch
    from core.execution.execution_verifier import ExecutionEvidence

    agent = E2EMockAgent()
    mock_ev = ExecutionEvidence(
        verification_type="gui_application_visible",
        target="notepad",
        is_verified=True,
        details={"hwnd": 1234, "is_visible": True, "title": "Bloc de notas"},
    )
    with patch("core.execution.execution_verifier.ExecutionVerifier.verify_execution", return_value=mock_ev), \
         patch("skills.apps_skill.WindowsAppsSkill.ejecutar", return_value={"exito": True, "verified": True, "mensaje": "Notepad abierto", "evidence": {"is_verified": True, "verification_type": "gui_application_visible", "target": "notepad"}}):
        resp = agent.interact("abre notepad")

    # Verified: handled via standard single-step flow, ARE not used for planning complex task
    assert resp.status in (AgentExecutionState.COMPLETED, AgentExecutionState.AWAITING_CONFIRMATION)
    # Output does not have ARE governance metadata since ARE was bypassed
    assert resp.output_data is None or resp.output_data.get("governance") != "JDE"


def test_case_b_complex_task_orchestrated_by_are():
    # CASO B — TAREA COMPLEJA: User -> Agent -> ARE -> JDE -> Skills -> Verifier -> Receipt
    agent = E2EMockAgent()
    resp = agent.interact("organiza los archivos de descarga y después resume el contenido")
    assert resp.status in (AgentExecutionState.COMPLETED, AgentExecutionState.AWAITING_CONFIRMATION, AgentExecutionState.AWAITING_CLARIFICATION), resp.error
    if resp.status == AgentExecutionState.COMPLETED:
        assert resp.output_data.get("governance") == "JDE"
    elif resp.status == AgentExecutionState.AWAITING_CLARIFICATION:
        assert resp.requires_clarification
        assert resp.clarification_question
        assert set(resp.tools_executed) <= {"files.search"}


def test_case_c_orca_ade_flow():
    # CASO C — ORCA/ADE
    agent = E2EMockAgent()
    resp = agent.interact("ejecuta tareas paralelas con agentes en worktree aislado")
    assert resp.status in (AgentExecutionState.COMPLETED, AgentExecutionState.AWAITING_CONFIRMATION)


def test_case_d_anydoc_flow():
    # CASO D — ANYDOC
    agent = E2EMockAgent()
    resp = agent.interact("convierte el informe a markdown y después analiza los párrafos")
    assert resp.status in (AgentExecutionState.COMPLETED, AgentExecutionState.AWAITING_CONFIRMATION)


def test_case_e_failure_recovery_flow():
    # CASO E — FAILURE RECOVERY
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    plan = rt.decompose_and_plan("tarea con posible fallo")
    diag, rec = rt.diagnose_and_recover(
        failed_step=plan.steps[0],
        error="Simulated network glitch",
        plan=plan,
        attempt=1,
    )
    assert diag.failure_step_id == plan.steps[0].step_id
    assert rec.recommended_action in ("RETRY", "ALTERNATIVE_BRANCH", "ASK_USER")


def test_case_f_deny_zero_side_effects():
    # CASO F — DENY: ARE -> JDE DENY -> ZERO SIDE EFFECT
    class DenyBinding(JDERuntimeBinding):
        def evaluate(self, *args, **kwargs):
            return JDERuntimeVerdict(
                verdict=JDERuntimeVerdictType.DENY,
                reason="Security rule DENY",
                action=kwargs.get("action", "test_action"),
                tool=kwargs.get("tool", "test_tool"),
            )

    agent = E2EMockAgent(jde_binding=DenyBinding())
    resp = agent.interact("organiza el sistema y después borra la partición")
    assert resp.success is False
    assert len(resp.tools_executed) == 0


def test_case_g_require_review_awaiting_confirmation():
    # CASO G — REQUIRE_REVIEW: ARE -> JDE REQUIRE_REVIEW -> ZERO SIDE EFFECT -> AWAITING_CONFIRMATION
    class ReviewBinding(JDERuntimeBinding):
        def evaluate(self, *args, **kwargs):
            return JDERuntimeVerdict(
                verdict=JDERuntimeVerdictType.REQUIRE_REVIEW,
                reason="Requires manual confirmation",
                action=kwargs.get("action", "test_action"),
                tool=kwargs.get("tool", "test_tool"),
            )

    agent = E2EMockAgent(jde_binding=ReviewBinding())
    resp = agent.interact("investiga los registros y luego actualiza la configuración")
    assert resp.status == AgentExecutionState.AWAITING_CONFIRMATION
    assert resp.requires_confirmation is True
    assert len(resp.tools_executed) == 0
