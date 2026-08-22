"""Suite de Pruebas de Interacción Confiable y Human-in-the-Loop (test_trusted_interaction.py - Fase 41).

Cubre los 12 escenarios formales:
1. clear intent
2. ambiguous intent
3. incomplete intent
4. confirmation
5. cancellation
6. pause
7. resume
8. rejection
9. wrong confirmation
10. confirmation expiration
11. multi-step confirmation
12. security denial
"""

from __future__ import annotations

import time

from core.autonomy.autonomy_level import AutonomyLevel
from core.emergency_stop import get_emergency_stop_manager
from core.interaction.interaction_models import (
    ConfirmationPrompt,
    InteractionAction,
    InteractionState,
    UserInteractionResponse,
    UserResponseType,
)
from core.interaction.interaction_policy import InteractionPolicy
from core.interaction.trusted_interaction_engine import TrustedInteractionEngine
from core.security_architecture import SecurityLevel


class TestTrustedInteractionSuite:
    """Suite de validación formal para decisiones Human-in-the-Loop y control de usuario."""

    def setup_method(self) -> None:
        self.emergency_stop = get_emergency_stop_manager()
        self.emergency_stop.reset("test_setup_cleanup")
        self.engine = TrustedInteractionEngine(emergency_stop=self.emergency_stop)

    def teardown_method(self) -> None:
        self.emergency_stop.reset("test_teardown_cleanup")

    # ── 1. CLEAR INTENT ──

    def test_01_clear_intent_direct_execution(self) -> None:
        """Verifica que una intención clara con riesgo SAFE y autonomía total se ejecuta directamente."""
        decision = InteractionPolicy.evaluate_interaction(
            intent="¿Qué hora es?",
            clarity_score=1.0,
            risk_level=SecurityLevel.SAFE,
            autonomy_level=AutonomyLevel.LEVEL_1_FULL_AUTONOMY,
        )
        assert decision.action == InteractionAction.ACTS
        assert decision.state == InteractionState.EXECUTE
        assert decision.execution_authorized is True

    # ── 2. AMBIGUOUS INTENT ──

    def test_02_ambiguous_intent_clarification(self) -> None:
        """Verifica que ante opciones ambiguas múltiples, el sistema pregunta en lugar de suponer."""
        decision = InteractionPolicy.evaluate_interaction(
            intent="Abre el archivo de reporte.",
            clarity_score=0.4,
            candidate_options=["reporte_enero.pdf", "reporte_febrero.pdf", "reporte_anual.docx"],
            risk_level=SecurityLevel.LOW,
        )
        assert decision.action == InteractionAction.ASKS
        assert decision.state == InteractionState.ASK_CLARIFICATION
        assert decision.execution_authorized is False
        assert decision.clarification is not None
        assert len(decision.clarification.candidate_options) == 3

    # ── 3. INCOMPLETE INTENT ──

    def test_03_incomplete_intent_missing_parameters(self) -> None:
        """Verifica que si faltan parámetros requeridos, el sistema solicita aclaración estructurada."""
        decision = InteractionPolicy.evaluate_interaction(
            intent="Mueve el archivo al directorio de destino.",
            clarity_score=0.9,
            missing_fields=["source_file", "target_directory"],
            risk_level=SecurityLevel.LOW,
        )
        assert decision.action == InteractionAction.CLARIFIES
        assert decision.state == InteractionState.ASK_CLARIFICATION
        assert "source_file" in decision.clarification.missing_fields

    # ── 4. CONFIRMATION REQUIRED ──

    def test_04_confirmation_required_for_high_risk(self) -> None:
        """Verifica que acciones de riesgo elevado generen solicitud explícita de confirmación."""
        decision = InteractionPolicy.evaluate_interaction(
            intent="Eliminar base de datos temporal.",
            action_name="db_drop_table",
            target_resource="temp_db",
            risk_level=SecurityLevel.DANGEROUS,
            autonomy_level=AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED,
            parameters={"table": "temp_records"},
        )
        assert decision.action == InteractionAction.CONFIRMS
        assert decision.state == InteractionState.REQUEST_CONFIRMATION
        assert decision.execution_authorized is False
        assert decision.confirmation is not None
        assert decision.confirmation.action_name == "db_drop_table"

    # ── 5. CANCELLATION FLOW ──

    def test_05_user_cancellation_flow(self) -> None:
        """Verifica que el usuario puede cancelar una tarea en curso."""
        resp = UserInteractionResponse(response_type=UserResponseType.CANCEL)
        res = self.engine.process_user_response(resp)
        assert res["success"] is True
        assert res["state"] == InteractionState.CANCELLED.value
        assert res["authorized"] is False

    # ── 6. PAUSE FLOW ──

    def test_06_user_pause_flow(self) -> None:
        """Verifica que el usuario puede pausar una tarea en ejecución."""
        resp = UserInteractionResponse(response_type=UserResponseType.PAUSE)
        res = self.engine.process_user_response(resp)
        assert res["success"] is True
        assert res["state"] == InteractionState.PAUSED.value
        assert res["authorized"] is False

    # ── 7. RESUME FLOW ──

    def test_07_user_resume_flow(self) -> None:
        """Verifica que el usuario puede reanudar una tarea pausada."""
        resp = UserInteractionResponse(response_type=UserResponseType.RESUME)
        res = self.engine.process_user_response(resp)
        assert res["success"] is True
        assert res["state"] == InteractionState.EXECUTE.value
        assert res["authorized"] is True

    # ── 8. REJECTION FLOW ──

    def test_08_user_rejection_flow(self) -> None:
        """Verifica que el rechazo explícito del usuario deniega la acción y libera la confirmación."""
        prompt = ConfirmationPrompt(
            task_id="task-reject-01",
            action_name="modify_registry",
            relevant_parameters={"key": "HKCU/Test"},
        )
        cid = self.engine.register_confirmation(prompt)

        resp = UserInteractionResponse(
            response_type=UserResponseType.REJECT,
            confirmation_id=cid,
            comment="No deseo modificar el registro",
        )
        res = self.engine.process_user_response(resp)
        assert res["success"] is False
        assert res["state"] == InteractionState.DENIED.value
        assert res["authorized"] is False

    # ── 9. WRONG CONFIRMATION SCOPE ──

    def test_09_wrong_confirmation_scope_rejected(self) -> None:
        """Verifica que una confirmación aprobada para la acción A no puede ser usada para ejecutar la acción B."""
        prompt = ConfirmationPrompt(
            task_id="task-scope-01",
            action_name="read_file",
            relevant_parameters={"path": "/sandbox/data.txt"},
        )
        cid = self.engine.register_confirmation(prompt)

        # El atacante intenta usar el confirmation_id de read_file para ejecutar delete_file
        resp = UserInteractionResponse(
            response_type=UserResponseType.CONFIRM,
            confirmation_id=cid,
        )
        res = self.engine.process_user_response(resp, expected_action="delete_file")
        assert res["success"] is False
        assert res["state"] == InteractionState.DENIED.value
        assert "Scope Mismatch" in res["reason"]
        assert res["authorized"] is False

    # ── 10. CONFIRMATION EXPIRATION (TTL) ──

    def test_10_confirmation_expiration_ttl(self) -> None:
        """Verifica que una solicitud de confirmación caducada es rechazada por TTL."""
        prompt = ConfirmationPrompt(
            task_id="task-ttl-01",
            action_name="format_disk",
            ttl_seconds=0.01,  # TTL muy breve
        )
        cid = self.engine.register_confirmation(prompt)
        time.sleep(0.05)  # Dejar expirar

        resp = UserInteractionResponse(
            response_type=UserResponseType.CONFIRM,
            confirmation_id=cid,
        )
        res = self.engine.process_user_response(resp)
        assert res["success"] is False
        assert res["state"] == InteractionState.FAILED.value
        assert "expirado por tiempo límite" in res["reason"]
        assert res["authorized"] is False

    # ── 11. MULTI-STEP CONFIRMATION ──

    def test_11_multi_step_scoped_confirmation(self) -> None:
        """Verifica que confirmar el paso 1 no autoriza automáticamente el paso 2."""
        p1 = ConfirmationPrompt(task_id="task-multi", action_name="step_1_create_backup")
        p2 = ConfirmationPrompt(task_id="task-multi", action_name="step_2_overwrite_data")

        cid1 = self.engine.register_confirmation(p1)
        cid2 = self.engine.register_confirmation(p2)

        # Confirmar paso 1
        res1 = self.engine.process_user_response(
            UserInteractionResponse(response_type=UserResponseType.CONFIRM, confirmation_id=cid1),
            expected_action="step_1_create_backup",
        )
        assert res1["success"] is True
        assert res1["authorized"] is True

        # Paso 2 aún no está autorizado hasta que se confirme explícitamente con cid2
        res2_unconfirmed = self.engine.process_user_response(
            UserInteractionResponse(response_type=UserResponseType.CONFIRM, confirmation_id=cid1),  # Reutilizar cid1
            expected_action="step_2_overwrite_data",
        )
        assert res2_unconfirmed["success"] is False
        assert res2_unconfirmed["authorized"] is False

        # Confirmar paso 2 con cid2
        res2_confirmed = self.engine.process_user_response(
            UserInteractionResponse(response_type=UserResponseType.CONFIRM, confirmation_id=cid2),
            expected_action="step_2_overwrite_data",
        )
        assert res2_confirmed["success"] is True
        assert res2_confirmed["authorized"] is True

    # ── 12. SECURITY DENIAL UNBYPASSABLE ──

    def test_12_security_denial_unbypassable(self) -> None:
        """Verifica que operaciones prohibidas por política son denegadas incondicionalmente sin opción a confirmar."""
        decision = InteractionPolicy.evaluate_interaction(
            intent="Formatea el disco C:",
            action_name="format_disk",
            risk_level=SecurityLevel.CRITICAL,
        )
        assert decision.action == InteractionAction.DENIES
        assert decision.state == InteractionState.DENIED
        assert decision.execution_authorized is False
        assert "denegada por SecurityPipeline" in decision.reason
