"""Tests de Fase 3C: Normalización de Contratos, Invariantes, Trazabilidad y Consolidación.

Cubre:
1. Matriz de Estados Canónicos:
   - executor success + verification true -> SUCCESS
   - executor success + verification false -> UNKNOWN
   - executor success + verification unavailable -> UNKNOWN
   - executor failure + verification false -> FAILED
   - executor failure + verification true -> FAILED
   - no execution -> NOT_EXECUTED
   - LLM confidence 1.0 + verification false -> UNKNOWN
   - input dispatched + verification false -> UNKNOWN
   - input dispatched + verification true -> SUCCESS
2. Invariante Transversal:
   claims_success <= is_verified
   claims_success == True ONLY IF is_verified == True and status == SUCCESS/SUCCEEDED
3. Cobertura Transversal de Anti-Falso Éxito:
   executor=OK + verifier=FALSE + confidence=1.0 -> UNKNOWN, claims_success=False
   (la respuesta final no debe contener afirmaciones de éxito falso).
4. Evidence Receipts:
   ActionReceipt inmutable con fingerprint SHA-256 verificado.
5. Clasificación Shadow:
   Distinción formal entre UNKNOWN concordante (CONCORDANT_UNKNOWN) y FALSE_SUCCESS.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock, patch
import pytest

from core.execution.action_execution_bridge import (
    ActionExecutionReport,
    build_execution_report,
    build_post_action_feedback,
)
from core.execution.execution_verifier import ExecutionEvidence, get_execution_verifier
from core.integration.adapters.computer_use_adapter import ComputerUseAdapter
from core.integration.models import ExecutionStatus as IntegrationStatus, IntegrationContext
from core.jde.models import DecisionRequest, DecisionResult
from core.jde.receipts import ActionReceipt, JDEEvidence
from core.jde.shadow import (
    JDEShadowMode,
    ShadowClassification,
    ShadowEvaluation,
)
from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType
from core.local_agent import AgentExecutionState, JessycaLocalAgent, JessycaRequest
from server.boundary import ExecutionResult, ExecutionStatus as BoundaryStatus


# ═══════════════════════════════════════════════════════════════
# 1. MATRIZ DE ESTADOS CANÓNICOS (TEST MATRIX)
# ═══════════════════════════════════════════════════════════════

class TestCanonicalStateMatrix:
    """Valida la matriz canónica de normalización a través de las capas."""

    def test_matrix_executor_success_verification_true_yields_success(self) -> None:
        """executor=success + verification=true -> SUCCESS."""
        exec_res = ExecutionResult(
            status=BoundaryStatus.SUCCESS,
            request_id="req-m1",
            tool_name="windows.files",
            operation="write_file",
            is_verified=True,
            evidence={"verified": True, "size": 100},
        )
        assert exec_res.claims_success is True

        report = build_execution_report(execution_result=exec_res)
        assert report is not None
        assert report.execution_status == "success"
        assert report.is_verified is True
        assert report.claims_success is True

    def test_matrix_executor_success_verification_false_yields_unknown(self) -> None:
        """executor=success + verification=false -> UNKNOWN."""
        exec_res = ExecutionResult(
            status=BoundaryStatus.SUCCESS,
            request_id="req-m2",
            tool_name="windows.files",
            operation="write_file",
            is_verified=False,
            evidence={"verified": False, "error": "File not found"},
        )
        assert exec_res.claims_success is False

        report = build_execution_report(execution_result=exec_res)
        assert report is not None
        assert report.execution_status == "unknown"
        assert report.is_verified is False
        assert report.claims_success is False

    def test_matrix_executor_success_verification_unavailable_yields_unknown(self) -> None:
        """executor=success + verification=unavailable -> UNKNOWN."""
        exec_res = ExecutionResult(
            status=BoundaryStatus.UNKNOWN,
            request_id="req-m3",
            tool_name="windows.system",
            operation="broadcast_event",
            is_verified=False,
            evidence=None,
        )
        assert exec_res.claims_success is False

        report = build_execution_report(execution_result=exec_res)
        assert report is not None
        assert report.execution_status == "unknown"
        assert report.claims_success is False

    def test_matrix_executor_failure_verification_false_yields_failed(self) -> None:
        """executor=failure + verification=false -> FAILED."""
        exec_res = ExecutionResult(
            status=BoundaryStatus.FAILED,
            request_id="req-m4",
            tool_name="windows.files",
            operation="delete_file",
            is_verified=False,
            evidence={"error": "Access denied"},
        )
        assert exec_res.claims_success is False

        report = build_execution_report(execution_result=exec_res)
        assert report is not None
        assert report.execution_status == "failed"
        assert report.claims_success is False

    def test_matrix_executor_failure_verification_true_yields_failed(self) -> None:
        """executor=failure + verification=true (anomalía) -> FAILED."""
        exec_res = ExecutionResult(
            status=BoundaryStatus.FAILED,
            request_id="req-m5",
            tool_name="windows.files",
            operation="write_file",
            is_verified=True,  # Supuesta presencia pero executor reportó FAILED
            evidence={"error": "Disk error after write"},
        )
        # La invariante exige: status==SUCCESS y is_verified==True para claims_success
        assert exec_res.claims_success is False

        report = build_execution_report(execution_result=exec_res)
        assert report is not None
        assert report.execution_status == "failed"
        assert report.claims_success is False

    def test_matrix_no_execution_yields_not_executed(self) -> None:
        """no execution -> None o reporte no ejecutado."""
        report = build_execution_report(execution_result=None, sys_resp=None)
        assert report is None

    def test_matrix_llm_confidence_1_with_verification_false_yields_unknown(self) -> None:
        """LLM confidence 1.0 + verification false -> UNKNOWN."""
        shadow = JDEShadowMode(persist_to_file=False)
        req = DecisionRequest(
            request_id="req-conf-1",
            user_request="abre la calculadora",
            intent="open_application",
            proposed_action="open",
            tool="windows.apps",
            confidence=1.0,
        )
        eval_res = shadow.evaluate_shadow(
            request=req,
            current_system_success=False,
            current_system_message="No pude confirmar la apertura de la calculadora.",
            current_system_verified=False,
            execution_status="OK",
            verification_status="UNVERIFIABLE",
        )
        assert eval_res.jde_predicted_state == DecisionState.UNKNOWN
        assert eval_res.classification == ShadowClassification.CONCORDANT_UNKNOWN
        assert eval_res.is_divergent is False

    def test_matrix_input_dispatched_without_ui_change_yields_unknown(self) -> None:
        """Computer Use: input dispatched=True, state_change_verified=False -> UNKNOWN."""
        import asyncio

        async def _run():
            adapter = ComputerUseAdapter()
            await adapter.initialize()
            ctx = IntegrationContext(session_id="cu-m1", parameters={"action": "click", "x": 100, "y": 100})
            return await adapter.execute("computer_use.mouse_interact", ctx)

        res = asyncio.run(_run())
        assert res.executed is True
        assert res.output.get("input_dispatched") is True
        assert res.output.get("state_change_verified") is False
        assert res.verified is False
        assert res.claims_success is False

    def test_matrix_input_dispatched_with_real_ui_change_yields_success(self) -> None:
        """Computer Use: input dispatched=True, state_change_verified=True -> SUCCESS."""
        import asyncio

        async def _run():
            adapter = ComputerUseAdapter()
            await adapter.initialize()
            ctx = IntegrationContext(session_id="cu-m2", parameters={"action": "click", "x": 100, "y": 100})
            return await adapter.execute("computer_use.mouse_interact", ctx)

        res = asyncio.run(_run())
        # Si un sensor o verifier externo confirma el cambio observable
        res_with_sensor = type(res)(
            executed=res.executed,
            status=IntegrationStatus.SUCCEEDED,
            verified=True,
            verification_required=False,
            output={**res.output, "state_change_verified": True},
            duration_ms=res.duration_ms,
        )
        assert res_with_sensor.claims_success is True


# ═══════════════════════════════════════════════════════════════
# 2. TEST DE INVARIANTE TRANSVERSAL
# ═══════════════════════════════════════════════════════════════

class TestTransversalInvariant:
    """Verifica claims_success <= is_verified de forma estricta en todas las capas."""

    def test_invariant_in_server_boundary(self) -> None:
        """server/boundary.py: ExecutionResult."""
        for status in (BoundaryStatus.SUCCESS, BoundaryStatus.FAILED, BoundaryStatus.DENIED, BoundaryStatus.UNKNOWN):
            for is_verif in (True, False):
                res = ExecutionResult(
                    status=status,
                    request_id="req-inv-1",
                    tool_name="test_tool",
                    operation="test_op",
                    is_verified=is_verif,
                )
                assert not res.claims_success or res.is_verified
                if res.claims_success:
                    assert res.status == BoundaryStatus.SUCCESS
                    assert res.is_verified is True

    def test_invariant_in_action_execution_report(self) -> None:
        """action_execution_bridge.py: ActionExecutionReport."""
        for status_str in ("success", "failed", "unknown", "denied"):
            for is_verif in (True, False):
                report = ActionExecutionReport(
                    skill_id="test_skill",
                    tool_name="test_tool",
                    execution_status=status_str,
                    is_verified=is_verif,
                    claims_success=(status_str == "success" and is_verif),
                )
                assert not report.claims_success or report.is_verified

    def test_invariant_in_jde_decision_result(self) -> None:
        """core/jde/models.py: DecisionResult."""
        # Estado FAILED con claims_success=True debe lanzar ValueError
        with pytest.raises(ValueError, match="Anti-False Success"):
            DecisionResult(
                request_id="req-inv-jde-1",
                state=DecisionState.FAILED,
                success=False,
                claims_success=True,  # Violación flagrante
                message="Error",
                executed_action="test",
                tool_used="test",
                executor_status=ExecutionStatusType.ERROR,
                verification_status=VerificationStatusType.VERIFIED_FALSE,
            )

        # Estado UNKNOWN con claims_success=True debe lanzar ValueError
        with pytest.raises(ValueError, match="Anti-False Success"):
            DecisionResult(
                request_id="req-inv-jde-2",
                state=DecisionState.UNKNOWN,
                success=False,
                claims_success=True,  # Violación flagrante
                message="Unknown",
                executed_action="test",
                tool_used="test",
                executor_status=ExecutionStatusType.OK,
                verification_status=VerificationStatusType.UNVERIFIABLE,
            )


# ═══════════════════════════════════════════════════════════════
# 3. TEST DE FALSE SUCCESS RESIDUAL Y RESPUESTA FINAL
# ═══════════════════════════════════════════════════════════════

class TestTransversalFalseSuccessPrevention:
    """Verifica que un intento con LLM confidence 1.0 y sin verificación no afirme éxito."""

    def test_unverified_action_never_says_listo(self) -> None:
        agent = JessycaLocalAgent()
        req = JessycaRequest(request_id="req-test-say-listo", user_input="abre el bloc de notas")

        # Simulamos ejecución donde el executor reporta OK pero verifier dice False
        unverified_exec = ExecutionResult(
            status=BoundaryStatus.UNKNOWN,
            request_id=req.request_id,
            tool_name="windows.apps",
            operation="open",
            is_verified=False,
            message="No se encontró ventana visible interactiva.",
        )

        resp_text = agent._format_response_text(
            intent="open_application",
            sys_resp=Mock(success=False, output={"evidence": {"is_verified": False}}, error="Unverified"),
            params={"app_name": "notepad"},
            execution_result=unverified_exec,
            session_id=req.session_id,
        )

        assert "Listo" not in resp_text
        assert "no pude confirmar" in resp_text.lower() or "no confirmó" in resp_text.lower()


# ═══════════════════════════════════════════════════════════════
# 4. TEST DE EVIDENCE RECEIPTS Y FINGERPRINTS
# ═══════════════════════════════════════════════════════════════

class TestEvidenceReceiptIntegrity:
    """Valida la generación de ActionReceipt y la verificación criptográfica del fingerprint."""

    def test_action_receipt_creation_and_fingerprint(self) -> None:
        receipt = ActionReceipt.create(
            request_id="req-rcpt-01",
            user_request="crea el archivo nota.txt",
            action="create_file",
            tool="windows.files",
            parameters={"path": "nota.txt", "content": "hola"},
            executor="windows_fs_executor",
            verifier="fs_verifier",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            execution_status=ExecutionStatusType.OK,
            verification_status=VerificationStatusType.VERIFIED_TRUE,
            verified=True,
            final_status=DecisionState.SUCCESS,
            evidence=[
                JDEEvidence(
                    verification_type="file_exists",
                    target="nota.txt",
                    is_verified=True,
                    details={"size_bytes": 4},
                )
            ],
        )

        assert receipt.receipt_id is not None
        assert len(receipt.fingerprint) == 64  # SHA-256 hex
        assert receipt.verify_integrity() is True

    def test_action_receipt_detects_tampering(self) -> None:
        receipt = ActionReceipt.create(
            request_id="req-rcpt-02",
            user_request="borra archivo.txt",
            action="delete_file",
            tool="windows.files",
            parameters={"path": "archivo.txt"},
            executor="windows_fs_executor",
            verifier="fs_verifier",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            execution_status=ExecutionStatusType.OK,
            verification_status=VerificationStatusType.VERIFIED_FALSE,
            verified=False,
            final_status=DecisionState.UNKNOWN,
        )

        assert receipt.verify_integrity() is True

        # Forzar manipulación de atributos
        tampered_receipt = receipt.model_copy(update={"verified": True, "final_status": DecisionState.SUCCESS})
        assert tampered_receipt.verify_integrity() is False

    def test_shadow_mode_generates_and_stores_receipt(self) -> None:
        """Verifica que el evaluador Shadow cree y almacene el ActionReceipt con su ID."""
        shadow = JDEShadowMode(persist_to_file=False)
        req = DecisionRequest(
            request_id="req-rcpt-shadow-01",
            user_request="guarda reporte.pdf",
            intent="save_file",
            proposed_action="write",
            tool="windows.files",
        )
        eval_res = shadow.evaluate_shadow(
            request=req,
            current_system_success=True,
            current_system_message="Guardado",
            current_system_verified=True,
            execution_status="OK",
            verification_status="VERIFIED_TRUE",
            raw_evidence={"verification_type": "file_exists", "target": "reporte.pdf", "is_verified": True},
        )

        assert eval_res.receipt_id is not None
        stored_rcpt = shadow.get_receipt(req.request_id)
        assert stored_rcpt is not None
        assert stored_rcpt.receipt_id == eval_res.receipt_id
        assert stored_rcpt.verify_integrity() is True
        assert stored_rcpt.final_status == DecisionState.SUCCESS


# ═══════════════════════════════════════════════════════════════
# 5. TEST DE CLASIFICACIÓN SHADOW CONCORDANT_UNKNOWN
# ═══════════════════════════════════════════════════════════════

class TestShadowConcordantUnknown:
    """Verifica la distinción entre CONCORDANT_UNKNOWN y FALSE_SUCCESS."""

    def test_both_systems_unknown_yields_concordant_unknown(self) -> None:
        shadow = JDEShadowMode(persist_to_file=False)
        req = DecisionRequest(
            request_id="req-unk-01",
            user_request="busca tutoriales en edge",
            intent="browser_search",
            proposed_action="browser_search",
            tool="browser.search",
        )
        eval_res = shadow.evaluate_shadow(
            request=req,
            current_system_success=False,
            current_system_message="Intenté buscar, pero no pude confirmar el resultado observable.",
            current_system_verified=False,
            execution_status="OK",
            verification_status="UNVERIFIABLE",
        )

        assert eval_res.jde_predicted_state == DecisionState.UNKNOWN
        assert eval_res.classification == ShadowClassification.CONCORDANT_UNKNOWN
        assert eval_res.is_divergent is False

    def test_legacy_claiming_success_without_evidence_yields_false_success(self) -> None:
        shadow = JDEShadowMode(persist_to_file=False)
        req = DecisionRequest(
            request_id="req-unk-02",
            user_request="busca tutoriales en edge",
            intent="browser_search",
            proposed_action="browser_search",
            tool="browser.search",
        )
        eval_res = shadow.evaluate_shadow(
            request=req,
            current_system_success=True,  # El sistema legado afirmó éxito
            current_system_message="Listo, busqué tutoriales.",
            current_system_verified=False,  # Pero no se verificó
            execution_status="OK",
            verification_status="UNVERIFIABLE",
        )

        assert eval_res.jde_predicted_state == DecisionState.UNKNOWN
        assert eval_res.classification == ShadowClassification.FALSE_SUCCESS
        assert eval_res.is_divergent is True
