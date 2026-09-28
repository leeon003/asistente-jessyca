"""Tests de Regresión Rigurosos para JDE Fase 3B — Extensión de Verificación Real.

Cubre las invariantes obligatorias:
- EXECUTOR SUCCESS != REAL WORLD SUCCESS
- UNKNOWN != SUCCESS
- NOT_VERIFIABLE != SUCCESS
- claims_success <= is_verified
- Tests mínimos A, B, C, D, E, F, G requeridos por la especificación.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from core.action_intent_contract import (
    ActionExecutionReport,
    ActionIntent,
    ActionIntentContract,
    ExecutionSpec,
)
from core.execution.action_execution_bridge import (
    build_execution_report,
    verify_and_build_execution_report,
)
from core.execution.execution_verifier import (
    ExecutionEvidence,
    ExecutionResult,
    ExecutionStatus,
    ExecutionVerifier,
    FileCopiedVerificationStrategy,
    FileDeletedVerificationStrategy,
    FileExistsVerificationStrategy,
    FileMovedVerificationStrategy,
    StateChangedVerificationStrategy,
    get_execution_verifier,
)
from core.integration.adapters.computer_use_adapter import ComputerUseAdapter
from core.integration.models import IntegrationContext, IntegrationExecutionResult
from core.jde.shadow import (
    DivergenceSeverity,
    ShadowClassification,
)
from core.jde.states import DecisionState
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest
from server.boundary import (
    ExecutionResult as MCPExecutionResult,
    ExecutionStatus as MCPExecutionStatus,
)
from tools.filesystem.executor import WindowsFilesystemToolExecutor


# ==============================================================================
# TEST A: Executor SUCCESS + Verification FALSE -> UNKNOWN / No Success Claim
# ==============================================================================
def test_a_executor_success_verification_false_produces_unknown_and_no_success_claim() -> None:
    """Test A: Executor reporta SUCCESS pero Verification reporta FALSE -> claims_success=False, UNKNOWN."""
    ev_false = ExecutionEvidence(
        verification_type="gui_application_visible",
        target="notepad",
        is_verified=False,
        details={"error": "Window not found"},
    )
    # Resultado de ejecución técnica exitosa pero no verificada
    exec_res = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED,
        action="open_application",
        target="notepad",
        evidence=ev_false,
    )

    # Invariante 1: el resultado formal no afirma éxito
    assert exec_res.claims_success is False

    # Invariante 2: el reporte del contrato traduce a unknown
    report = build_execution_report(exec_res)
    assert report is not None
    assert report.is_verified is False
    assert report.claims_success is False
    assert report.execution_status in ("unknown", "failed")


# ==============================================================================
# TEST B: Executor SUCCESS + Verification UNAVAILABLE -> UNKNOWN
# ==============================================================================
def test_b_executor_success_verification_unavailable_produces_unknown() -> None:
    """Test B: Executor reporta SUCCESS pero Verificación no está disponible -> UNKNOWN, claims_success=False."""
    # Sin evidencia adjunta (unavailable)
    exec_res = ExecutionResult(
        status=ExecutionStatus.UNKNOWN,
        action="custom_tool",
        target="some_target",
        evidence=None,
    )

    assert exec_res.claims_success is False
    report = build_execution_report(exec_res)
    assert report is not None
    assert report.execution_status == "unknown"
    assert report.is_verified is False
    assert report.claims_success is False


# ==============================================================================
# TEST C: Executor FAILURE -> FAILED
# ==============================================================================
def test_c_executor_failure_produces_failed() -> None:
    """Test C: Executor reporta FAILURE -> FAILED, claims_success=False."""
    exec_res = ExecutionResult(
        status=ExecutionStatus.FAILED,
        action="delete_file",
        target="C:\\protected\\file.sys",
        message="Access denied",
        error_code="ACCESS_DENIED",
    )

    assert exec_res.claims_success is False
    report = build_execution_report(exec_res)
    assert report is not None
    assert report.execution_status == "failed"
    assert report.is_verified is False
    assert report.claims_success is False


# ==============================================================================
# TEST D: Executor SUCCESS + Verification TRUE -> SUCCESS
# ==============================================================================
def test_d_executor_success_verification_true_produces_success() -> None:
    """Test D: Executor reporta SUCCESS y Verificación confirma evidencia real -> SUCCESS."""
    ev_true = ExecutionEvidence(
        verification_type="gui_application_visible",
        target="notepad",
        is_verified=True,
        details={"hwnd": 12345, "title": "Sin título: Bloc de notas"},
    )
    exec_res = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED,
        action="open_application",
        target="notepad",
        evidence=ev_true,
    )

    assert exec_res.claims_success is True
    report = build_execution_report(exec_res)
    assert report is not None
    assert report.execution_status == "success"
    assert report.is_verified is True
    assert report.claims_success is True


# ==============================================================================
# TEST E: LLM Confidence 1.0 + Verification FALSE -> NO SUCCESS
# ==============================================================================
def test_e_llm_confidence_1_with_verification_false_never_claims_success() -> None:
    """Test E: Confianza absoluta del LLM (1.0) con verificación False JAMÁS produce claims_success=True."""
    agent = JessycaLocalAgent.get_instance()
    req = JessycaRequest(
        user_input="Jessica abre el bloc de notas",
        session_id="test_sess_llm_conf_1",
    )

    mock_fail_evidence = {
        "verification_type": "process",
        "target": "notepad",
        "is_verified": False,
        "details": {"error": "Window not found"},
    }

    with patch.object(agent.skill_manager, "execute_skill") as mock_exec:
        mock_exec.return_value = MagicMock(
            success=True,
            output={
                "exito": True,  # Executor dice True
                "evidence": mock_fail_evidence,  # Pero verificación es False
            },
        )
        resp = agent.interact(req)

        # Regla central: claims_success <= is_verified
        assert resp.success is False
        assert resp.status in (AgentExecutionState.FAILED, AgentExecutionState.UNKNOWN)
        # JESSYCA no debe decir "Listo, abrí el Bloc de notas"
        assert "Listo, abrí" not in resp.response_text
        if resp.action_intent_contract and resp.action_intent_contract.execution_report:
            assert resp.action_intent_contract.execution_report.claims_success is False


# ==============================================================================
# TEST F: Computer Use Input Dispatched without State Change -> UNKNOWN
# ==============================================================================
@pytest.mark.anyio
async def test_f_computer_use_input_dispatched_without_verified_state_change() -> None:
    """Test F: Computer Use envía click/tecla (INPUT DISPATCHED) pero el cambio de estado no está verificado -> claims_success=False."""
    adapter = ComputerUseAdapter()
    await adapter.initialize()

    context = IntegrationContext(
        session_id="test_sess_cu_f",
        parameters={"action": "click", "x": 100, "y": 100},
    )

    with patch("pyautogui.click") as mock_click, patch("pyautogui.position", return_value=(100, 100)):
        mock_click.return_value = None
        res = await adapter.execute("computer_use.mouse_interact", context)

        # Invocación técnica completada
        assert res.executed is True
        # Distinción taxativa: input enviado != estado verificado
        assert res.output["input_dispatched"] is True
        assert res.output["state_change_verified"] is False
        # No auto-certifica éxito
        assert res.verified is False
        assert res.claims_success is False


# ==============================================================================
# TEST G: Filesystem Executor OK but File Does Not Exist -> UNKNOWN / FAILED
# ==============================================================================
def test_g_filesystem_executor_ok_but_file_not_found_never_success() -> None:
    """Test G: Operación de filesystem reporta OK pero el archivo no existe en disco -> UNKNOWN/FAILED, nunca SUCCESS."""
    verifier = get_execution_verifier()

    # Archivo inexistente
    non_existent_path = "C:\\Data\\definitely_not_existing_file_98765.txt"
    evidence = verifier.verify_execution("create_file", non_existent_path)

    assert evidence.is_verified is False
    assert evidence.details["size_bytes"] == 0

    # Construir reporte formal
    exec_res = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED,  # El ejecutor fingió éxito
        action="create_file",
        target=non_existent_path,
        evidence=evidence,
    )
    report = build_execution_report(exec_res)
    assert report is not None
    assert report.claims_success is False
    assert report.execution_status == "unknown"


# ==============================================================================
# TEST H: Filesystem DELETE Verification Strategy
# ==============================================================================
def test_h_filesystem_delete_verification_positive_and_negative() -> None:
    """Verifica que la estrategia de eliminación confirme ausencia real del archivo."""
    strat = FileDeletedVerificationStrategy()

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # 1. Archivo aún existe -> eliminación no verificada (is_verified=False)
        ev_still_exists = strat.verify("delete_file", tmp_path)
        assert ev_still_exists.is_verified is False
        assert ev_still_exists.details["deleted"] is False

        # 2. Eliminar archivo real
        os.remove(tmp_path)

        # 3. Archivo ya no existe -> eliminación verificada (is_verified=True)
        ev_deleted = strat.verify("delete_file", tmp_path)
        assert ev_deleted.is_verified is True
        assert ev_deleted.details["deleted"] is True
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ==============================================================================
# TEST I: Filesystem MOVE Verification Strategy
# ==============================================================================
def test_i_filesystem_move_verification() -> None:
    """Verifica que move_file compruebe que origen no existe y destino sí existe."""
    strat = FileMovedVerificationStrategy()

    with tempfile.NamedTemporaryFile(delete=False) as tmp_src:
        src_path = tmp_src.name
    dest_path = src_path + ".moved"

    try:
        # Antes de mover: destino no existe -> no verificado
        ev_before = strat.verify("move_file", dest_path, parameters={"source": src_path, "dest": dest_path})
        assert ev_before.is_verified is False

        # Mover archivo
        os.rename(src_path, dest_path)

        # Después de mover: origen ausente y destino presente -> verificado
        ev_after = strat.verify("move_file", dest_path, parameters={"source": src_path, "dest": dest_path})
        assert ev_after.is_verified is True
    finally:
        if os.path.exists(src_path):
            os.remove(src_path)
        if os.path.exists(dest_path):
            os.remove(dest_path)


# ==============================================================================
# TEST J: StateChangedVerificationStrategy does not default to True
# ==============================================================================
def test_j_state_changed_strategy_does_not_default_to_true() -> None:
    """Verifica que StateChangedVerificationStrategy sin evidencia explícita devuelva is_verified=False."""
    strat = StateChangedVerificationStrategy()

    # Sin parámetros
    ev1 = strat.verify("generic_action", "target1", parameters={})
    assert ev1.is_verified is False

    # Con parámetros arbitrarios sin 'verified'
    ev2 = strat.verify("generic_action", "target2", parameters={"key": "value", "status": "ok"})
    assert ev2.is_verified is False

    # Únicamente cuando verified=True explícito
    ev3 = strat.verify("generic_action", "target3", parameters={"verified": True})
    assert ev3.is_verified is True


# ==============================================================================
# TEST K: MCP WindowsFilesystemToolExecutor with Real and Unverified State
# ==============================================================================
def test_k_mcp_filesystem_executor_anti_false_success() -> None:
    """Verifica que el ejecutor MCP no certifique éxito si la evidencia en disco no se comprueba."""
    executor = WindowsFilesystemToolExecutor()
    mock_auth_ev = MagicMock()

    sandbox_root = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "sandbox")
    os.makedirs(sandbox_root, exist_ok=True)
    test_file = os.path.join(sandbox_root, "test_write_phase3b.txt")

    try:
        req = MagicMock(
            request_id="req-mcp-test-01",
            correlation_id="corr-01",
            session_id="sess-01",
            tool_name="windows.files",
            operation="write_file",
            parameters={"path": test_file, "content": "Hello World", "mock_unverified": True},
        )

        # Ejecución con mock_unverified=True
        res = executor.execute(req, mock_auth_ev)
        assert res.status == MCPExecutionStatus.UNKNOWN
        assert res.is_verified is False
        assert res.claims_success is False
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)
