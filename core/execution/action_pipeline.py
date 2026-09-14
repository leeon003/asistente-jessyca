"""Action Pipeline End-to-End para JESSYCA 3.0 (Fase 64.2.6).

Orquestador ligero e integrador del pipeline unificado de acciones:
    Usuario / Petición
          ↓
    Action Planner (Fase 64.2.1)
          ↓
    ActionIntentContract (Fase 64.1)
          ↓
    Execution Gate & Confirmation Bridge (Fase 64.2.2)
          ↓
    Execution Dispatcher (Fase 64.2.3)
          ↓
    Skill Execution
          ↓
    Post-Execution Verification (Fase 64.2.4)
          ↓
    Feedback Builder & Natural Response (Fase 64.2.5)
          ↓
    TTS / UI

REGLAS FUNDAMENTALES:
1. "Execution success" != "Real-world success".
2. Cada etapa puede detener el flujo (Gate, Confirmation, Dispatcher, Verifier).
3. ASK_CONFIRMATION pausa la ejecución; sólo avanza con confirmación explícita.
4. Idempotencia y protección estricta contra doble ejecución.
5. Los errores no derriban el proceso global ni generan falsos éxitos.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.action_intent_contract import (
    ActionIntentContract,
    PostActionFeedback,
)
from core.dialogue.action_planner import (
    ActionPlanner,
    ActionPlanningValidationError,
)
from core.dialogue.feedback_builder import (
    FeedbackBuilder,
    FeedbackStatus,
    NaturalFeedbackResponse,
    get_feedback_builder,
)
from core.execution.execution_dispatcher import (
    DispatchResult,
    ExecutionDispatcher,
)
from core.execution.execution_gate_bridge import (
    ExecutionDecision,
    ExecutionGateBridge,
    GateDecisionType,
)
from core.execution.idempotency_guard import (
    ExecutionFingerprint,
    ExecutionIdempotencyGuard,
    get_idempotency_guard,
)
from core.execution.post_execution_verifier import (
    PostExecutionVerifier,
    VerificationReport,
    VerificationReportStatus,
)
from core.logger import get_logger

logger = get_logger("jessyca.execution.action_pipeline")


class ActionPipelineStatus(StrEnum):
    """Estados canónicos del ciclo de vida integral del pipeline de acción."""

    ACTION_REQUESTED = "ACTION_REQUESTED"
    PLANNED = "PLANNED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    AUTHORIZED = "AUTHORIZED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"


@dataclass(frozen=True)
class ActionPipelineResult:
    """Resultado formal, inmutable y completo del pipeline de acción."""

    action_id: str
    session_id: str
    status: ActionPipelineStatus
    contract: ActionIntentContract | None
    decision: ExecutionDecision | None
    dispatch_result: DispatchResult | None
    verification_report: VerificationReport | None
    feedback_response: NaturalFeedbackResponse | None
    spoken_response: str
    response_text: str
    is_terminal: bool
    duration_ms: float
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_post_action_feedback(self) -> PostActionFeedback:
        """Convierte el resultado en PostActionFeedback para consumo directo."""
        return PostActionFeedback(
            spoken_response=self.spoken_response,
            response_text=self.response_text,
        )


class ActionPipeline:
    """Orquestador central e integrador del pipeline unificado de acciones de JESSYCA."""

    _instance: ActionPipeline | None = None
    _lock = threading.RLock()

    def __init__(
        self,
        planner: ActionPlanner | None = None,
        gate_bridge: ExecutionGateBridge | None = None,
        dispatcher: ExecutionDispatcher | None = None,
        verifier: PostExecutionVerifier | None = None,
        feedback_builder: FeedbackBuilder | None = None,
        idempotency_guard: ExecutionIdempotencyGuard | None = None,
    ) -> None:
        self.planner = planner or ActionPlanner()
        self.gate_bridge = gate_bridge or ExecutionGateBridge()
        self.dispatcher = dispatcher or ExecutionDispatcher()
        self.verifier = verifier or PostExecutionVerifier()
        self.feedback_builder = feedback_builder or get_feedback_builder()
        self.idempotency_guard = idempotency_guard or get_idempotency_guard()

        # Almacenamiento concurrente seguro de acciones en pausa (WAITING_CONFIRMATION)
        self._pending_actions: dict[str, tuple[ActionIntentContract, ExecutionDecision]] = {}
        self._action_records: dict[str, ActionPipelineResult] = {}
        self._mutex = threading.Lock()

    @classmethod
    def get_instance(cls) -> ActionPipeline:
        """Acceso singleton al pipeline de acción."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = ActionPipeline()
            return cls._instance

    def execute(
        self,
        user_input: str,
        intent: str | None = None,
        parameters: dict[str, Any] | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        contract: ActionIntentContract | None = None,
        user_confirmed: bool | None = None,
        risk_level: str | None = None,
        confidence: float | None = None,
        custom_verifier: Any | None = None,
        timeout_seconds: float = 30.0,
    ) -> ActionPipelineResult:
        """Ejecuta una acción a través de todas las fases del pipeline garantizando gobernanza estricta."""
        t_start = time.perf_counter()
        action_id = request_id or (contract.request_id if contract else f"act_{int(time.time() * 1000)}")
        sess_id = session_id or (contract.session_id if contract else "default_session")

        logger.info(
            f"[PIPELINE START] action_id={action_id} session_id={sess_id} "
            f"intent={intent} input='{user_input}'"
        )

        # ── 1. PROTECCIÓN DE IDEMPOTENCIA (DUPLICATE CHECK) ──
        with self._mutex:
            if action_id in self._action_records:
                existing_res = self._action_records[action_id]
                # Si está en WAITING_CONFIRMATION y user_confirmed IS NOT None,
                # se trata de la resolución de la confirmación previa (no un duplicado accidental)
                is_resolving_confirmation = (
                    existing_res.status == ActionPipelineStatus.WAITING_CONFIRMATION
                    and user_confirmed is not None
                )
                if not is_resolving_confirmation and existing_res.status in (
                    ActionPipelineStatus.WAITING_CONFIRMATION,
                    ActionPipelineStatus.EXECUTING,
                    ActionPipelineStatus.COMPLETED,
                ):
                    logger.warning(
                        f"[PIPELINE IDEMPOTENCY BLOCKED] Acción duplicada ignorada: "
                        f"action_id={action_id} status={existing_res.status}"
                    )
                    return existing_res

        # ── 2. PLANIFICACIÓN (ACTION_REQUESTED -> PLANNED) ──
        current_contract = contract
        if current_contract is None:
            try:
                current_contract = self.planner.plan_action(
                    intent=intent or "open_application",
                    user_input=user_input,
                    params=parameters,
                    session_id=sess_id,
                    request_id=action_id,
                    risk_level=risk_level,
                    confidence=confidence if confidence is not None else 1.0,
                )
            except ActionPlanningValidationError as pve:
                logger.warning(f"[PIPELINE CLARIFY REQUIRED] Fallo de validación en planner: {pve}")
                elapsed = (time.perf_counter() - t_start) * 1000.0
                feedback = self.feedback_builder.build_feedback(
                    status=FeedbackStatus.CLARIFY,
                    operation=intent or "accion",
                    reason=str(pve),
                )
                return self._finalize_result(
                    action_id=action_id,
                    session_id=sess_id,
                    status=ActionPipelineStatus.CLARIFICATION_REQUIRED,
                    contract=None,
                    decision=None,
                    dispatch_result=None,
                    verification_report=None,
                    feedback=feedback,
                    duration_ms=elapsed,
                    is_terminal=False,
                    error=str(pve),
                )
            except Exception as exc:
                logger.error(f"[PIPELINE PLANNER ERROR] Error en ActionPlanner: {exc}", exc_info=True)
                elapsed = (time.perf_counter() - t_start) * 1000.0
                feedback = self.feedback_builder.build_feedback(
                    status=FeedbackStatus.VERIFIED_FAILURE,
                    reason=f"Error interno al planificar la acción: {exc}",
                )
                return self._finalize_result(
                    action_id=action_id,
                    session_id=sess_id,
                    status=ActionPipelineStatus.FAILED,
                    contract=None,
                    decision=None,
                    dispatch_result=None,
                    verification_report=None,
                    feedback=feedback,
                    duration_ms=elapsed,
                    is_terminal=True,
                    error=str(exc),
                )

        logger.info(f"[PIPELINE TRANSITION] action_id={action_id} -> PLANNED")

        # ── 3. EVALUACIÓN DE COMPUERTA (EXECUTION GATE & CONFIRMATION BRIDGE) ──
        try:
            decision = self.gate_bridge.evaluate_gate(
                contract=current_contract,
                user_confirmed=user_confirmed,
            )
        except Exception as exc:
            logger.error(f"[PIPELINE GATE ERROR] Error en ExecutionGateBridge: {exc}", exc_info=True)
            elapsed = (time.perf_counter() - t_start) * 1000.0
            feedback = self.feedback_builder.build_feedback(
                status=FeedbackStatus.VERIFIED_FAILURE,
                reason=f"Error en compuerta de ejecución: {exc}",
            )
            return self._finalize_result(
                action_id=action_id,
                session_id=sess_id,
                status=ActionPipelineStatus.FAILED,
                contract=current_contract,
                decision=None,
                dispatch_result=None,
                verification_report=None,
                feedback=feedback,
                duration_ms=elapsed,
                is_terminal=True,
                error=str(exc),
            )

        # 3.1 Caso: Requiere Aclaración (CLARIFY)
        if decision.decision_type == GateDecisionType.CLARIFY:
            logger.info(f"[PIPELINE TRANSITION] action_id={action_id} -> CLARIFICATION_REQUIRED")
            elapsed = (time.perf_counter() - t_start) * 1000.0
            feedback = self.feedback_builder.build_feedback(
                intent=current_contract,
                status=FeedbackStatus.CLARIFY,
                reason=decision.reason,
            )
            return self._finalize_result(
                action_id=action_id,
                session_id=sess_id,
                status=ActionPipelineStatus.CLARIFICATION_REQUIRED,
                contract=decision.contract,
                decision=decision,
                dispatch_result=None,
                verification_report=None,
                feedback=feedback,
                duration_ms=elapsed,
                is_terminal=False,
                error=decision.reason,
            )

        # 3.2 Caso: Requiere Confirmación Humana (ASK_CONFIRMATION / WAITING_CONFIRMATION)
        if decision.decision_type == GateDecisionType.ASK_CONFIRMATION and not decision.can_proceed_to_execution:
            logger.info(f"[PIPELINE TRANSITION] action_id={action_id} -> WAITING_CONFIRMATION")
            elapsed = (time.perf_counter() - t_start) * 1000.0

            # Pausar y guardar estado para confirmación posterior
            with self._mutex:
                self._pending_actions[action_id] = (decision.contract, decision)

            feedback = self.feedback_builder.build_feedback(
                intent=decision.contract,
                status=FeedbackStatus.ASK_CONFIRMATION,
                reason=decision.reason,
            )
            return self._finalize_result(
                action_id=action_id,
                session_id=sess_id,
                status=ActionPipelineStatus.WAITING_CONFIRMATION,
                contract=decision.contract,
                decision=decision,
                dispatch_result=None,
                verification_report=None,
                feedback=feedback,
                duration_ms=elapsed,
                is_terminal=False,
                error=None,
            )

        # 3.3 Caso: Rechazado por Seguridad o Política (REJECTED)
        if decision.decision_type == GateDecisionType.REJECT or not decision.can_proceed_to_execution:
            logger.warning(f"[PIPELINE TRANSITION] action_id={action_id} -> REJECTED: {decision.reason}")
            elapsed = (time.perf_counter() - t_start) * 1000.0
            feedback = self.feedback_builder.build_feedback(
                intent=decision.contract,
                status=FeedbackStatus.REJECTED,
                reason=decision.reason,
            )
            return self._finalize_result(
                action_id=action_id,
                session_id=sess_id,
                status=ActionPipelineStatus.REJECTED,
                contract=decision.contract,
                decision=decision,
                dispatch_result=None,
                verification_report=None,
                feedback=feedback,
                duration_ms=elapsed,
                is_terminal=True,
                error=decision.reason,
            )

        # ── 4. AUTORIZACIÓN Y DESPACHO (AUTHORIZED -> EXECUTING -> EXECUTED) ──
        logger.info(f"[PIPELINE TRANSITION] action_id={action_id} -> AUTHORIZED")

        # Registro formal en guardián de idempotencia
        target_name = (
            decision.action_intent.parameters.get("nombre_app")
            or decision.action_intent.parameters.get("target")
            or decision.action_intent.target
            or ""
        )
        fp = ExecutionFingerprint(
            session_id=sess_id,
            request_id=action_id,
            intent=decision.action_intent.intent_name,
            skill=decision.skill_id or "unspecified",
            action=decision.operation or "unspecified",
            target=str(target_name),
        )
        acquired, _ = self.idempotency_guard.acquire_execution(fp)
        if not acquired:
            logger.warning(f"[PIPELINE DUPLICATE EXECUTION BLOCKED] action_id={action_id}")
            elapsed = (time.perf_counter() - t_start) * 1000.0
            feedback = self.feedback_builder.build_feedback(
                intent=decision.contract,
                status=FeedbackStatus.VERIFIED_FAILURE,
                reason="La acción ya fue ejecutada previamente.",
            )
            return self._finalize_result(
                action_id=action_id,
                session_id=sess_id,
                status=ActionPipelineStatus.REJECTED,
                contract=decision.contract,
                decision=decision,
                dispatch_result=None,
                verification_report=None,
                feedback=feedback,
                duration_ms=elapsed,
                is_terminal=True,
                error="Duplicado bloqueado por idempotencia",
            )

        logger.info(f"[PIPELINE TRANSITION] action_id={action_id} -> EXECUTING")

        try:
            dispatch_res = self.dispatcher.dispatch(
                decision=decision,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            logger.error(f"[PIPELINE DISPATCH EXCEPTION] action_id={action_id}: {exc}", exc_info=True)
            elapsed = (time.perf_counter() - t_start) * 1000.0
            feedback = self.feedback_builder.build_feedback(
                intent=decision.contract,
                status=FeedbackStatus.VERIFICATION_ERROR,
                reason=f"Excepción en el despacho de la acción: {exc}",
            )
            return self._finalize_result(
                action_id=action_id,
                session_id=sess_id,
                status=ActionPipelineStatus.FAILED,
                contract=decision.contract,
                decision=decision,
                dispatch_result=None,
                verification_report=None,
                feedback=feedback,
                duration_ms=elapsed,
                is_terminal=True,
                error=str(exc),
            )

        logger.info(
            f"[PIPELINE TRANSITION] action_id={action_id} -> EXECUTED "
            f"(dispatch_status={dispatch_res.status}, is_success={dispatch_res.is_success})"
        )

        # ── 5. VERIFICACIÓN POST-EJECUCIÓN (VERIFYING -> COMPLETED / FAILED) ──
        logger.info(f"[PIPELINE TRANSITION] action_id={action_id} -> VERIFYING")

        try:
            if (
                custom_verifier is not None
                and hasattr(custom_verifier, "verify")
                and callable(custom_verifier.verify)
            ):
                verif_rep = custom_verifier.verify(
                    intent=dispatch_res.contract,
                    execution=dispatch_res,
                )
            else:
                verif_rep = self.verifier.verify(
                    intent=dispatch_res.contract,
                    execution=dispatch_res,
                    custom_verifier=custom_verifier,
                    timeout_seconds=min(timeout_seconds, 2.5),
                )
        except Exception as exc:
            logger.error(f"[PIPELINE VERIFIER EXCEPTION] action_id={action_id}: {exc}", exc_info=True)
            elapsed = (time.perf_counter() - t_start) * 1000.0
            feedback = self.feedback_builder.build_feedback(
                intent=dispatch_res.contract,
                status=FeedbackStatus.VERIFICATION_ERROR,
                reason=f"Excepción en verificación: {exc}",
            )
            return self._finalize_result(
                action_id=action_id,
                session_id=sess_id,
                status=ActionPipelineStatus.FAILED,
                contract=dispatch_res.contract,
                decision=decision,
                dispatch_result=dispatch_res,
                verification_report=None,
                feedback=feedback,
                duration_ms=elapsed,
                is_terminal=True,
                error=str(exc),
            )

        # Determinar estado final del pipeline aplicando Anti-False Success
        final_pipeline_status = ActionPipelineStatus.FAILED

        if verif_rep.verification_status == VerificationReportStatus.VERIFIED_SUCCESS:
            final_pipeline_status = ActionPipelineStatus.COMPLETED
        elif verif_rep.verification_status == VerificationReportStatus.UNVERIFIED:
            # Acción completó su despacho pero no tiene sensor de verificación determinista
            # Se conserva la diferencia entre ejecutado y verificado (no afirma falso éxito)
            final_pipeline_status = ActionPipelineStatus.EXECUTED if dispatch_res.is_success else ActionPipelineStatus.FAILED
        elif verif_rep.verification_status in (
            VerificationReportStatus.VERIFIED_FAILURE,
            VerificationReportStatus.VERIFICATION_ERROR,
            VerificationReportStatus.PARTIAL_SUCCESS,
        ):
            final_pipeline_status = ActionPipelineStatus.FAILED

        logger.info(
            f"[PIPELINE TRANSITION] action_id={action_id} -> {final_pipeline_status} "
            f"(verif_status={verif_rep.verification_status}, claims_success={verif_rep.claims_success})"
        )

        # ── 6. FEEDBACK AL USUARIO Y SÍNTESIS NATURAL (FASE 64.2.5) ──
        feedback = self.feedback_builder.build_feedback(
            verification_report=verif_rep,
            intent=dispatch_res.contract,
            execution_report=dispatch_res.execution_report,
            target=str(target_name),
            operation=decision.operation,
        )

        # Actualizar contrato inmutablemente con el resultado verificado y feedback
        final_contract = verif_rep.attach_to_contract(dispatch_res.contract)
        final_contract = final_contract.model_copy(
            update={"post_action_feedback": feedback.to_post_action_feedback()}
        )

        elapsed = (time.perf_counter() - t_start) * 1000.0

        return self._finalize_result(
            action_id=action_id,
            session_id=sess_id,
            status=final_pipeline_status,
            contract=final_contract,
            decision=decision,
            dispatch_result=dispatch_res,
            verification_report=verif_rep,
            feedback=feedback,
            duration_ms=elapsed,
            is_terminal=True,
            error=verif_rep.error or dispatch_res.error,
        )

    def confirm_action(
        self,
        action_id: str,
        user_confirmed: bool,
        custom_verifier: Any | None = None,
        timeout_seconds: float = 30.0,
    ) -> ActionPipelineResult:
        """Reanuda la ejecución de una acción que estaba en espera de confirmación (WAITING_CONFIRMATION)."""
        logger.info(f"[PIPELINE CONFIRMATION RESUMED] action_id={action_id} user_confirmed={user_confirmed}")

        with self._mutex:
            pending = self._pending_actions.pop(action_id, None)

        if pending is None:
            logger.warning(f"[PIPELINE CONFIRMATION FAILED] No existe acción pendiente con action_id={action_id}")
            feedback = self.feedback_builder.build_feedback(
                status=FeedbackStatus.VERIFIED_FAILURE,
                reason="No se encontró ninguna acción pendiente de confirmación.",
            )
            return ActionPipelineResult(
                action_id=action_id,
                session_id="unspecified",
                status=ActionPipelineStatus.REJECTED,
                contract=None,
                decision=None,
                dispatch_result=None,
                verification_report=None,
                feedback_response=feedback,
                spoken_response=feedback.spoken_response,
                response_text=feedback.response_text,
                is_terminal=True,
                duration_ms=0.0,
                error="Acción pendiente no encontrada",
            )

        contract, _ = pending

        # Continuar la ejecución evaluando la compuerta con la decisión del usuario
        return self.execute(
            user_input=contract.action_intent.intent_name,
            contract=contract,
            user_confirmed=user_confirmed,
            custom_verifier=custom_verifier,
            timeout_seconds=timeout_seconds,
        )

    def get_action_result(self, action_id: str) -> ActionPipelineResult | None:
        """Consulta el resultado histórico o en curso de una acción por su action_id."""
        with self._mutex:
            return self._action_records.get(action_id)

    def reset(self) -> None:
        """Reinicia el estado en memoria para pruebas unitarias."""
        with self._mutex:
            self._pending_actions.clear()
            self._action_records.clear()
        self.idempotency_guard.reset()

    def _finalize_result(
        self,
        action_id: str,
        session_id: str,
        status: ActionPipelineStatus,
        contract: ActionIntentContract | None,
        decision: ExecutionDecision | None,
        dispatch_result: DispatchResult | None,
        verification_report: VerificationReport | None,
        feedback: NaturalFeedbackResponse,
        duration_ms: float,
        is_terminal: bool,
        error: str | None = None,
    ) -> ActionPipelineResult:
        """Empaqueta y registra el ActionPipelineResult."""
        res = ActionPipelineResult(
            action_id=action_id,
            session_id=session_id,
            status=status,
            contract=contract,
            decision=decision,
            dispatch_result=dispatch_result,
            verification_report=verification_report,
            feedback_response=feedback,
            spoken_response=feedback.spoken_response,
            response_text=feedback.response_text,
            is_terminal=is_terminal,
            duration_ms=duration_ms,
            error=error,
            details={
                "completed_at": datetime.now(UTC).isoformat(),
                "has_decision": decision is not None,
                "has_dispatch": dispatch_result is not None,
                "has_verification": verification_report is not None,
            },
        )
        with self._mutex:
            self._action_records[action_id] = res
        return res


# Singleton global
_default_action_pipeline = ActionPipeline()


def get_action_pipeline() -> ActionPipeline:
    """Acceso singleton al pipeline de acción de JESSYCA."""
    return _default_action_pipeline
