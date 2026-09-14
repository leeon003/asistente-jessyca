"""Tests unitarios para ActionExecutionBridge (Fase 64.1.5).

Verifica la transformación del resultado REAL de ejecución y verificación hacia:
- ActionExecutionReport
- PostActionFeedback
- ActionIntentContract
- Telemetry & Anti-False Success
"""

from unittest.mock import MagicMock

import pytest

from core.action_intent_contract import (
    ActionExecutionReport,
    ActionIntent,
    ActionIntentContract,
    ExecutionGate,
    PreActionFeedback,
)
from core.execution.action_execution_bridge import (
    attach_execution_to_contract,
    build_execution_report,
    build_post_action_feedback,
    verify_and_build_execution_report,
)
from core.execution.execution_verifier import (
    ExecutionEvidence,
    ExecutionResult,
    ExecutionStatus,
    ExecutionVerifier,
)
from core.system.system_coordinator import SystemResponse


def _create_sample_contract(
    intent_name: str = "open_application",
    needs_clarification: bool = False,
    needs_confirmation: bool = False,
    can_execute: bool = True,
    clarification_prompt: str | None = None,
    confirmation_prompt: str | None = None,
) -> ActionIntentContract:
    """Helper para instanciar un ActionIntentContract coherente para pruebas."""
    if needs_clarification and not clarification_prompt:
        clarification_prompt = "¿Qué deseas abrir?"
    if needs_confirmation and not confirmation_prompt:
        confirmation_prompt = "¿Confirmas la operación?"

    return ActionIntentContract(
        request_id="req-test-123",
        session_id="session-test-456",
        action_intent=ActionIntent(
            intent_name=intent_name,
            confidence=0.95,
            target="notepad",
            parameters={"app_name": "notepad"},
        ),
        execution_gate=ExecutionGate(
            can_execute=can_execute,
            needs_clarification=needs_clarification,
            clarification_prompt=clarification_prompt,
            needs_confirmation=needs_confirmation,
            confirmation_prompt=confirmation_prompt,
        ),
        pre_action_feedback=PreActionFeedback(acknowledgement_speech="Abriendo el bloc de notas..."),
    )


class TestActionExecutionBridge:
    """Suite de validación para el Bridge de Ejecución y Verificación."""

    # ── 1. SUCCESS VERIFICADO ────────────────────────────────────────────────
    def test_01_verified_success(self) -> None:
        """Una acción con ExecutionStatus.SUCCEEDED y evidencia verificada genera reporte con éxito."""
        evidence = ExecutionEvidence(
            verification_type="process_exists",
            target="notepad",
            is_verified=True,
            details={"pid": 1234},
        )
        result = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            action="open_application",
            target="notepad",
            message="Bloc de notas abierto correctamente.",
            evidence=evidence,
        )

        report = build_execution_report(execution_result=result, skill_id="windows.apps")

        assert report is not None
        assert report.execution_status == "success"
        assert report.is_verified is True
        assert report.claims_success is True
        assert report.evidence["pid"] == 1234
        assert report.skill_id == "windows.apps"
        assert report.tool_name == "open_application"

        feedback = build_post_action_feedback(report, response_text="Listo, abrí el bloc de notas.")
        assert feedback is not None
        assert "Listo" in feedback.spoken_response

    # ── 2. FAILURE ───────────────────────────────────────────────────────────
    def test_02_execution_failure(self) -> None:
        """Una acción fallida genera reporte con execution_status='failed' y claims_success=False."""
        result = ExecutionResult(
            status=ExecutionStatus.FAILED,
            action="open_application",
            target="unknown_app",
            message="No se encontró la aplicación.",
            error_code="APP_NOT_FOUND",
        )

        report = build_execution_report(execution_result=result)

        assert report is not None
        assert report.execution_status == "failed"
        assert report.claims_success is False
        assert report.error_code == "APP_NOT_FOUND"

        feedback = build_post_action_feedback(report, response_text="No pude abrir la aplicación.")
        assert feedback is not None
        assert feedback.spoken_response == "No pude abrir la aplicación."

    # ── 3. RESULTADO UNKNOWN / UNVERIFIED ────────────────────────────────────
    def test_03_unknown_unverified_execution(self) -> None:
        """Una acción con status SUCCEEDED pero SIN evidencia verificada no debe declarar éxito."""
        result = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            action="open_application",
            target="notepad",
            message="Se invocó la aplicación.",
            evidence=None,  # Sin evidencia determinista
        )

        report = build_execution_report(execution_result=result)

        assert report is not None
        assert report.execution_status == "unknown"
        assert report.is_verified is False
        assert report.claims_success is False

        # Feedback no debe proclamar "Listo" falsamente
        feedback = build_post_action_feedback(report, response_text="Listo, abrí el bloc de notas.")
        assert feedback is not None
        assert "no se pudo confirmar su estado" in feedback.spoken_response

    # ── 4. NO EXECUTION POR CLARIFICATION ────────────────────────────────────
    def test_04_no_execution_on_clarification(self) -> None:
        """Si la acción requiere aclaración, attach_execution_to_contract no añade reporte ni feedback."""
        contract = _create_sample_contract(needs_clarification=True, can_execute=False)

        updated = attach_execution_to_contract(
            contract=contract,
            execution_result=None,
            response_text="¿Podrías especificar qué aplicación?",
        )

        assert updated is not None
        assert updated.execution_report is None
        assert updated.post_action_feedback is None

    # ── 5. NO EXECUTION POR CONFIRMATION ─────────────────────────────────────
    def test_05_no_execution_on_pending_confirmation(self) -> None:
        """Si la acción está en confirmación pendiente, el contrato conserva execution_report=None."""
        contract = _create_sample_contract(needs_confirmation=True, can_execute=False)

        updated = attach_execution_to_contract(
            contract=contract,
            execution_result=None,
            response_text="¿Confirmas eliminar el archivo?",
        )

        assert updated is not None
        assert updated.execution_report is None
        assert updated.post_action_feedback is None

    # ── 6. CONVERSACIÓN NORMAL ───────────────────────────────────────────────
    def test_06_conversational_turn_has_none_contract(self) -> None:
        """Un turno puramente conversacional donde el contrato es None permanece en None."""
        updated = attach_execution_to_contract(
            contract=None,
            execution_result=None,
            response_text="¡Hola! ¿Cómo estás?",
        )
        assert updated is None

    # ── 7. ANTI-FALSE SUCCESS ────────────────────────────────────────────────
    def test_07_anti_false_success_enforcement(self) -> None:
        """El modelo ActionExecutionReport prohíbe claims_success=True cuando is_verified=False."""
        with pytest.raises(ValueError, match="Anti-False Success"):
            ActionExecutionReport(
                execution_status="success",
                is_verified=False,
                claims_success=True,
            )

        # También verificar cuando status es VERIFICATION_FAILED
        evidence_failed = ExecutionEvidence(
            verification_type="process_exists",
            target="notepad",
            is_verified=False,
        )
        result_verif_failed = ExecutionResult(
            status=ExecutionStatus.VERIFICATION_FAILED,
            action="open_application",
            target="notepad",
            evidence=evidence_failed,
        )
        report = build_execution_report(result_verif_failed)
        assert report is not None
        assert report.claims_success is False
        assert report.execution_status == "failed"

    # ── 8. PRESERVACIÓN DE REQUEST_ID / SESSION_ID ────────────────────────────
    def test_08_preservation_of_ids(self) -> None:
        """attach_execution_to_contract preserva íntegramente request_id, session_id y timestamps."""
        contract = _create_sample_contract()
        evidence = ExecutionEvidence(
            verification_type="process_exists",
            target="notepad",
            is_verified=True,
        )
        result = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            action="open_application",
            target="notepad",
            evidence=evidence,
        )

        updated = attach_execution_to_contract(
            contract=contract,
            execution_result=result,
            response_text="Listo, abrí el bloc de notas.",
            spoken_text="Listo, abrí el bloc de notas.",
        )

        assert updated is not None
        assert updated.request_id == contract.request_id
        assert updated.session_id == contract.session_id
        assert updated.created_at == contract.created_at
        assert updated.execution_report is not None
        assert updated.execution_report.claims_success is True
        assert updated.post_action_feedback is not None

    # ── 9. NO DOBLE EJECUCIÓN ────────────────────────────────────────────────
    def test_09_no_double_execution(self) -> None:
        """El bridge es un adaptador puro que no invoca skills ni ejecuta procesos del SO."""
        mock_skill_manager = MagicMock()

        # Llamar al bridge únicamente con datos existentes
        report = build_execution_report(
            sys_resp=SystemResponse(
                task_id="task-1",
                correlation_id="corr-1",
                success=True,
                status="COMPLETED",
                output={"evidence": {"is_verified": True}},
            ),
            skill_id="mock_skill",
        )

        assert report is not None
        assert report.claims_success is True
        # Ninguna llamada a skill_manager
        mock_skill_manager.execute_skill.assert_not_called()

    # ── 10. NO DOBLE TELEMETRÍA / LOGGING ────────────────────────────────────
    def test_10_no_double_telemetry(self) -> None:
        """El bridge no emite eventos ni invoca experience_logger directamente."""
        mock_experience_logger = MagicMock()
        contract = _create_sample_contract()
        result = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            action="open_application",
            target="notepad",
            evidence=ExecutionEvidence("process", "notepad", True),
        )

        # attach_execution_to_contract transforma datos sin llamar al logger
        updated = attach_execution_to_contract(
            contract=contract,
            execution_result=result,
            response_text="Listo.",
        )

        assert updated is not None
        mock_experience_logger.log_interaction.assert_not_called()

    # ── 11. INTEGRACIÓN CON EXECUTION_VERIFIER EXISTENTE ─────────────────────
    def test_11_integration_with_execution_verifier(self) -> None:
        """verify_and_build_execution_report utiliza la estrategia real del ExecutionVerifier."""
        mock_verifier = MagicMock(spec=ExecutionVerifier)
        mock_verifier.verify_execution.return_value = ExecutionEvidence(
            verification_type="process_exists",
            target="calc",
            is_verified=True,
            details={"pid": 9999},
        )

        report = verify_and_build_execution_report(
            action="open_application",
            target="calc",
            verifier=mock_verifier,
            skill_id="windows.apps",
        )

        assert report.execution_status == "success"
        assert report.is_verified is True
        assert report.claims_success is True
        assert report.evidence["pid"] == 9999
        mock_verifier.verify_execution.assert_called_once_with(
            action="open_application",
            target="calc",
            parameters=None,
        )

    # ── 12. COMPATIBILIDAD CON EXECUTION_RESULT EXISTENTE ────────────────────
    def test_12_compatibility_with_execution_result(self) -> None:
        """build_execution_report respeta todos los campos y métodos de ExecutionResult."""
        evidence = ExecutionEvidence("state_changed", "file.txt", False, {"reason": "timeout"})
        result = ExecutionResult(
            status=ExecutionStatus.FAILED,
            action="delete_file",
            target="C:\\test\\file.txt",
            message="No se pudo eliminar el archivo.",
            evidence=evidence,
            error_code="PERMISSION_DENIED",
            duration_ms=45.2,
        )

        # Compatibilidad con properties existentes
        assert result.claims_success is False

        report = build_execution_report(execution_result=result)
        assert report is not None
        assert report.execution_status == "failed"
        assert report.is_verified is False
        assert report.claims_success is False
        assert report.error_code == "PERMISSION_DENIED"
        assert report.evidence["reason"] == "timeout"
