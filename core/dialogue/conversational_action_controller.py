"""Controlador de Acciones Conversacionales (conversational_action_controller.py - Fase 64.3.1).

Integra el ActionPipeline con el flujo conversacional continuo de JESSYCA,
permitiendo que una acción que requiere confirmación (WAITING_CONFIRMATION) pueda
ser reanudada, cancelada o reemplazada de forma segura por el siguiente turno del usuario.

PRINCIPIOS FUNDAMENTALES:
1. DETECCIÓN PRIORITARIA DE CONFIRMACIÓN:
   Si existe una acción pendiente para la sesión, el turno del usuario se evalúa
   primero como posible respuesta afirmativa ("Sí", "Claro", "Adelante", "Hazlo", etc.)
   o negativa ("No", "Cancela", "Mejor no", etc.).
2. DESVÍO SEGURO ANTE NUEVA INTENCIÓN:
   Si el usuario formula una nueva orden durante la espera de confirmación ("Abre Chrome"),
   la acción pendiente se descarta/cancela limpiamente sin ejecutarla accidentalmente y se procesa
   la nueva orden.
3. PREVENCIÓN DE ACCIÓN HUÉRFANA O FANTASMA:
   Un "Sí" en frío o tras una acción completada o expirada nunca ejecutará nada.
4. PROTECCIÓN DE IDEMPOTENCIA:
   Confirmaciones duplicadas ("Sí, sí" o dos "Sí" sucesivos) solo ejecutan la acción una sola vez.
5. ANTI-FALSE SUCCESS:
   El resultado final respeta estrictamente el veredicto del ActionPipeline y su verificación real.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from core.action_intent_contract import (
    ActionIntent,
    ActionIntentContract,
)
from core.dialogue.action_recovery import (
    ActionRecoveryContext,
    ActionRecoveryState,
    RecoveryUserIntent,
    build_recovery_prompt,
    classify_failure_category,
    classify_recovery_intent,
)
from core.dialogue.action_sequence import (
    ActionSequence,
    ActionSequenceStatus,
    ActionStep,
    ActionStepStatus,
    SequenceFailurePolicy,
    StepPlanner,
    _normalize_app,
)
from core.dialogue.conversational_intent_continuity import (
    ActionContext,
    ContinuityResolutionResult,
    ConversationalIntentContinuityResolver,
    get_continuity_resolver,
)
from core.dialogue.feedback_builder import (
    FeedbackBuilder,
    get_feedback_builder,
)
from core.logger import get_logger

if TYPE_CHECKING:
    from core.execution.action_pipeline import (
        ActionPipeline,
        ActionPipelineResult,
    )

logger = get_logger("jessyca.dialogue.conversational_action_controller")


class ConversationalActionStatus(StrEnum):
    """Estados del controlador conversacional de acción (Fase 64.3.1)."""

    IDLE = "IDLE"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    REJECTED = "REJECTED"
    RECOVERY_AVAILABLE = "RECOVERY_AVAILABLE"


@dataclass
class PendingActionConfirmation:
    """Registro estructurado de una acción en espera de confirmación humana."""

    action_id: str
    session_id: str
    contract: ActionIntentContract
    prompt: str
    action_intent: ActionIntent | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + timedelta(seconds=120))
    status: ConversationalActionStatus = ConversationalActionStatus.WAITING_CONFIRMATION
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Indica si el tiempo de vida (TTL) de la confirmación ha vencido."""
        return datetime.now(UTC) > self.expires_at


@dataclass(frozen=True)
class ConversationalActionResult:
    """Resultado formal del procesamiento de un turno en el controlador conversacional."""

    status: ConversationalActionStatus
    response_text: str
    spoken_response: str
    action_id: str | None = None
    contract: ActionIntentContract | None = None
    pipeline_result: ActionPipelineResult | None = None
    is_terminal: bool = True
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    recovery_context: ActionRecoveryContext | None = None
    recovery_state: ActionRecoveryState = ActionRecoveryState.NONE
    recovery_available: bool = False


# ── VOCABULARIO DETERMINISTA DE CONFIRMACIÓN / CANCELACIÓN ────────────────────

_AFFIRMATIVE_WORDS: frozenset[str] = frozenset({
    "si",
    "sí",
    "claro",
    "adelante",
    "hazlo",
    "correcto",
    "dale",
    "confirma",
    "procede",
    "afirmativo",
    "de acuerdo",
    "por favor",
    "por supuesto",
    "autorizo",
    "confirmo",
    "seguro",
    "ejecuta",
})

_NEGATIVE_WORDS: frozenset[str] = frozenset({
    "no",
    "cancela",
    "cancelar",
    "mejor no",
    "dejalo",
    "déjalo",
    "no lo hagas",
    "no gracias",
    "detente",
    "alto",
    "no autorizo",
    "no confirmo",
    "rechaza",
    "rechazar",
    "olvidalo",
    "olvídalo",
    "para",
    "aborta",
    "abortar",
})


def classify_confirmation_intent(text: str) -> bool | None:
    """Clasifica deterministamente si el texto del usuario representa una confirmación.

    Retorna:
    - True: Intención afirmativa ("Sí", "Claro", "Adelante", "Hazlo", "Sí, hazlo", etc.)
    - False: Intención negativa / cancelación ("No", "Cancela", "Mejor no", "Déjalo", etc.)
    - None: Otra intención o comando que no es respuesta a confirmación ("Abre Chrome", "Hola", etc.)
    """
    cleaned = re.sub(r"[^\w\s]", " ", text.lower()).strip()
    tokens = cleaned.split()

    if not tokens:
        return None

    norm_phrase = " ".join(tokens)

    # 1. Verificación directa de frase completa negativa
    if norm_phrase in _NEGATIVE_WORDS:
        return False
    if any(norm_phrase == f"no {w}" for w in ("gracias", "lo hagas", "quiero", "cancela", "autorizo")):
        return False
    if any(w in tokens for w in ("cancela", "cancelar", "dejalo", "déjalo", "olvidalo", "olvídalo", "aborta", "abortar")):
        return False
    if tokens[0] == "no" and len(tokens) <= 3 and not any(w in tokens for w in ("abre", "cierra", "busca", "reproduce")):
        return False

    # 2. Verificación directa de frase completa afirmativa
    if norm_phrase in _AFFIRMATIVE_WORDS:
        return True
    if any(norm_phrase == f"si {w}" for w in ("hazlo", "por favor", "adelante", "confirma", "claro", "procede", "dale")):
        return True
    if any(norm_phrase == f"sí {w}" for w in ("hazlo", "por favor", "adelante", "confirma", "claro", "procede", "dale")):
        return True
    if any(norm_phrase == f"claro {w}" for w in ("que si", "que sí", "hazlo", "adelante", "por favor")):
        return True
    if all(t in _AFFIRMATIVE_WORDS for t in tokens) and len(tokens) <= 4:
        return True

    return None


class ConversationalActionController:
    """Controlador que vincula la conversación continua con el ActionPipeline."""

    _instance: ConversationalActionController | None = None
    _singleton_lock = threading.RLock()

    def __init__(
        self,
        pipeline: ActionPipeline | None = None,
        feedback_builder: FeedbackBuilder | None = None,
        continuity_resolver: ConversationalIntentContinuityResolver | None = None,
        step_planner: StepPlanner | None = None,
        default_ttl_seconds: float = 120.0,
    ) -> None:
        if pipeline is not None:
            self.pipeline = pipeline
        else:
            from core.execution.action_pipeline import get_action_pipeline
            self.pipeline = get_action_pipeline()
        self.feedback_builder = feedback_builder or get_feedback_builder()
        self.continuity_resolver = continuity_resolver or get_continuity_resolver()
        self.step_planner = step_planner or StepPlanner()
        self.default_ttl_seconds = default_ttl_seconds
        self._pending_confirmations: dict[str, PendingActionConfirmation] = {}
        self._action_contexts: dict[str, ActionContext] = {}
        self._last_failed_contexts: dict[str, ActionContext] = {}
        self._pending_sequences: dict[str, ActionSequence] = {}
        self._session_open_apps: dict[str, list[str]] = {}
        self._recovery_contexts: dict[str, ActionRecoveryContext] = {}
        self.max_retries: int = 2
        self._mutex = threading.RLock()

    @classmethod
    def get_instance(cls) -> ConversationalActionController:
        """Obtiene la instancia singleton thread-safe del controlador."""
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = ConversationalActionController()
            return cls._instance

    # ── GESTIÓN DE ACCIONES PENDIENTES ───────────────────────────────────────

    def get_pending(self, session_id: str = "default_session") -> PendingActionConfirmation | None:
        """Obtiene la acción pendiente de confirmación para una sesión si no ha expirado."""
        with self._mutex:
            pending = self._pending_confirmations.get(session_id)
            if pending:
                if pending.is_expired:
                    self._pending_confirmations.pop(session_id, None)
                    return None
                return pending

            # Si hay una secuencia en espera de confirmación, exponer el paso pendiente
            pending_seq = self._pending_sequences.get(session_id)
            if pending_seq and pending_seq.overall_status == ActionSequenceStatus.WAITING_CONFIRMATION:
                p_step = pending_seq.pending_step
                if p_step and p_step.contract:
                    return PendingActionConfirmation(
                        action_id=p_step.action_id,
                        session_id=session_id,
                        contract=p_step.contract,
                        prompt=f"¿Confirmas {p_step.description}?",
                        action_intent=p_step.contract.action_intent,
                        status=ConversationalActionStatus.WAITING_CONFIRMATION,
                    )
            return None

    def set_pending(
        self,
        contract: ActionIntentContract,
        prompt: str,
        session_id: str = "default_session",
        ttl_seconds: float | None = None,
    ) -> PendingActionConfirmation:
        """Registra explícitamente una acción en espera de confirmación para una sesión."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
        pending = PendingActionConfirmation(
            action_id=contract.request_id,
            session_id=session_id,
            contract=contract,
            prompt=prompt,
            action_intent=contract.action_intent,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
            status=ConversationalActionStatus.WAITING_CONFIRMATION,
        )
        with self._mutex:
            self._pending_confirmations[session_id] = pending
        return pending

    def cancel_pending(self, session_id: str = "default_session") -> bool:
        """Cancela y limpia la confirmación pendiente de una sesión."""
        with self._mutex:
            pending = self._pending_confirmations.pop(session_id, None)
            if pending:
                self.pipeline.confirm_action(action_id=pending.action_id, user_confirmed=False)
                return True
            pending_seq = self._pending_sequences.pop(session_id, None)
            if pending_seq and pending_seq.pending_step:
                self.pipeline.confirm_action(action_id=pending_seq.pending_step.action_id, user_confirmed=False)
                return True
            return False

    # ── GESTIÓN DE SECUENCIAS MULTI-PASO (FASE 64.3.3) ───────────────────────

    def get_pending_sequence(self, session_id: str = "default_session") -> ActionSequence | None:
        """Obtiene la secuencia en espera de confirmación para una sesión."""
        with self._mutex:
            seq = self._pending_sequences.get(session_id)
            if seq and seq.overall_status == ActionSequenceStatus.WAITING_CONFIRMATION:
                return seq
            return None

    def get_paused_sequence(self, session_id: str = "default_session") -> ActionSequence | None:
        """Obtiene la secuencia pausada por fallo o en recuperación para una sesión."""
        with self._mutex:
            seq = self._pending_sequences.get(session_id)
            if seq and seq.overall_status == ActionSequenceStatus.FAILED:
                return seq
            return None

    def set_pending_sequence(self, sequence: ActionSequence, session_id: str = "default_session") -> None:
        """Registra una secuencia en espera para la sesión."""
        with self._mutex:
            self._pending_sequences[session_id] = sequence

    def clear_pending_sequence(self, session_id: str = "default_session") -> None:
        """Limpia cualquier secuencia pendiente para la sesión."""
        with self._mutex:
            self._pending_sequences.pop(session_id, None)

    def get_session_open_apps(self, session_id: str = "default_session") -> list[str]:
        """Obtiene la lista de aplicaciones abiertas activas en la sesión."""
        with self._mutex:
            return list(self._session_open_apps.get(session_id, []))

    # ── GESTIÓN DE CONTEXTO DE ACCIONES COMPLETADAS (FASE 64.3.2) ─────────────

    def get_action_context(self, session_id: str = "default_session") -> ActionContext | None:
        """Obtiene el contexto de la última acción completada para una sesión si no ha expirado."""
        with self._mutex:
            ctx = self._action_contexts.get(session_id)
            if ctx and ctx.is_expired():
                self._action_contexts.pop(session_id, None)
                return None
            return ctx

    def set_action_context(self, session_id: str, context: ActionContext) -> None:
        """Establece explícitamente el contexto de acción completada para una sesión."""
        with self._mutex:
            self._action_contexts[session_id] = context

    def clear_action_context(self, session_id: str = "default_session") -> None:
        """Limpia el contexto de acción para la sesión especificada."""
        with self._mutex:
            self._action_contexts.pop(session_id, None)

    def resolve_turn_continuity(
        self,
        user_input: str,
        session_id: str = "default_session",
        ttl_seconds: float | None = None,
        current_time: float | None = None,
    ) -> ContinuityResolutionResult:
        """Analiza y resuelve deterministamente el seguimiento conversacional sin ejecutar nada."""
        ctx = self.get_action_context(session_id)
        open_apps = self.get_session_open_apps(session_id)
        return self.continuity_resolver.resolve(
            user_input=user_input,
            action_context=ctx,
            ttl_seconds=ttl_seconds,
            current_time=current_time,
            active_session_apps=open_apps,
        )

    # ── GESTIÓN DE RECUPERACIÓN CONVERSACIONAL (FASE 64.3.4) ─────────────────

    def get_recovery_context(self, session_id: str = "default_session") -> ActionRecoveryContext | None:
        """Obtiene el contexto de recuperación activo para una sesión si existe."""
        with self._mutex:
            return self._recovery_contexts.get(session_id)

    def set_recovery_context(self, session_id: str, context: ActionRecoveryContext) -> None:
        """Registra explícitamente un contexto de recuperación para una sesión."""
        with self._mutex:
            self._recovery_contexts[session_id] = context

    def clear_recovery_context(self, session_id: str = "default_session") -> None:
        """Limpia el contexto de recuperación de una sesión."""
        with self._mutex:
            self._recovery_contexts.pop(session_id, None)

    def get_last_failed_context(self, session_id: str = "default_session") -> ActionContext | None:
        """Obtiene el contexto de la última acción fallida para la sesión."""
        with self._mutex:
            return self._last_failed_contexts.get(session_id)

    def clear_all(self) -> None:
        """Limpia todo el estado en memoria (para pruebas unitarias e inicio limpio)."""
        with self._mutex:
            self._pending_confirmations.clear()
            self._action_contexts.clear()
            self._last_failed_contexts.clear()
            self._pending_sequences.clear()
            self._session_open_apps.clear()
            self._recovery_contexts.clear()
        self.pipeline.reset()

    # ── PROCESAMIENTO DE TURNO CONVERSACIONAL ────────────────────────────────

    def process_turn(
        self,
        user_input: str,
        session_id: str = "default_session",
        intent: str | None = None,
        parameters: dict[str, Any] | None = None,
        contract: ActionIntentContract | None = None,
        custom_verifier: Any | None = None,
        ttl_seconds: float | None = None,
        risk_level: str | None = None,
        confidence: float | None = None,
    ) -> ConversationalActionResult:
        """Procesa el turno conversacional respetando compuertas y confirmaciones en curso."""
        from core.execution.action_pipeline import ActionPipelineStatus

        t_start = time.perf_counter()
        logger.info(f"[CONTROLLER TURN START] session_id={session_id} input='{user_input}'")

        # ── 0. EVALUAR SI EXISTE SECUENCIA MULTI-PASO PENDIENTE EN ESTA SESIÓN (FASE 64.3.3) ──
        with self._mutex:
            pending_seq = self._pending_sequences.get(session_id)

        if pending_seq is not None and pending_seq.overall_status == ActionSequenceStatus.WAITING_CONFIRMATION:
            conf_choice = classify_confirmation_intent(user_input)

            # 0.1 CASO AFIRMATIVO: Continuar secuencia pendiente
            if conf_choice is True:
                return self._continue_sequence(
                    sequence=pending_seq,
                    session_id=session_id,
                    user_confirmed=True,
                    custom_verifier=custom_verifier,
                    ttl_seconds=ttl_seconds,
                )

            # 0.2 CASO NEGATIVO / CANCELAR: Rechazar paso y cancelar secuencia
            if conf_choice is False:
                return self._continue_sequence(
                    sequence=pending_seq,
                    session_id=session_id,
                    user_confirmed=False,
                    custom_verifier=custom_verifier,
                    ttl_seconds=ttl_seconds,
                )

            # 0.3 CASO NUEVA ORDEN DURANTE ESPERA EN SECUENCIA ("No, mejor abre Spotify" o "Abre Spotify")
            logger.info(
                f"[CONTROLLER SEQUENCE REDIRECT] Nueva orden recibida ('{user_input}'). "
                f"Descartando secuencia pendiente [{pending_seq.sequence_id}] de forma segura."
            )
            if pending_seq.pending_step and pending_seq.pending_step.action_id:
                try:
                    self.pipeline.confirm_action(action_id=pending_seq.pending_step.action_id, user_confirmed=False)
                except Exception:
                    pass
            with self._mutex:
                self._pending_sequences.pop(session_id, None)
            # Continúa hacia abajo para procesar la nueva orden con seguridad

        # ── 1. EVALUAR SI EXISTE ACCIÓN PENDIENTE EN ESTA SESIÓN ──
        with self._mutex:
            pending = self._pending_confirmations.get(session_id)

        if pending is not None:
            # Comprobar si el turno actual es respuesta a la confirmación
            conf_choice = classify_confirmation_intent(user_input)

            # 1.1 CASO: AFIRMATIVO ("Sí", "Claro", "Adelante", "Hazlo", etc.)
            if conf_choice is True:
                # Verificar expiración de tiempo (TTL)
                if pending.is_expired:
                    with self._mutex:
                        self._pending_confirmations.pop(session_id, None)
                    logger.warning(
                        f"[CONTROLLER EXPIRED] Intento de confirmar acción expirada: "
                        f"action_id={pending.action_id} session_id={session_id}"
                    )
                    expired_speech = "Ya no tengo esa acción pendiente. ¿Quieres que la vuelva a hacer?"
                    return ConversationalActionResult(
                        status=ConversationalActionStatus.EXPIRED,
                        response_text=expired_speech,
                        spoken_response=expired_speech,
                        action_id=pending.action_id,
                        contract=pending.contract,
                        is_terminal=True,
                    )

                # Consumir de inmediato para evitar doble ejecución (idempotencia)
                with self._mutex:
                    self._pending_confirmations.pop(session_id, None)

                logger.info(
                    f"[CONTROLLER CONFIRMED] Confirmación aprobada para action_id={pending.action_id}. "
                    f"Reanudando pipeline de acción."
                )

                pipe_res = self.pipeline.confirm_action(
                    action_id=pending.action_id,
                    user_confirmed=True,
                    custom_verifier=custom_verifier,
                )

                if pipe_res.status == ActionPipelineStatus.COMPLETED:
                    final_status = ConversationalActionStatus.COMPLETED
                    # Registrar contexto de la acción confirmada completada (Fase 64.3.2)
                    target_str = (
                        (pending.contract.action_intent.target if pending.contract and pending.contract.action_intent else None)
                        or (pending.action_intent.target if pending.action_intent else None)
                        or (pipe_res.contract.action_intent.target if pipe_res.contract and pipe_res.contract.action_intent else None)
                        or ""
                    )
                    action_str = (
                        (pending.contract.action_intent.intent_name if pending.contract and pending.contract.action_intent else None)
                        or "action"
                    )
                    skill_str = (
                        (pending.contract.execution_spec.skill_id if pending.contract and pending.contract.execution_spec else None)
                        or "windows.apps"
                    )
                    op_str = (
                        (pending.contract.execution_spec.tool_name if pending.contract and pending.contract.execution_spec else None)
                        or "execute"
                    )
                    act_ctx = ActionContext(
                        action_id=pending.action_id,
                        action=action_str,
                        skill=skill_str,
                        operation=op_str,
                        target=str(target_str),
                        result=pipe_res.dispatch_result.output if pipe_res.dispatch_result else None,
                        status="COMPLETED",
                        timestamp=time.time(),
                        entities=(str(target_str),) if target_str else (),
                        ttl_seconds=ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds,
                    )
                    with self._mutex:
                        self._action_contexts[session_id] = act_ctx

                        # Actualizar lista de aplicaciones abiertas activas en la sesión
                        norm_t = _normalize_app(str(target_str))
                        open_list = self._session_open_apps.setdefault(session_id, [])
                        if "open" in action_str or "launch" in action_str:
                            if norm_t not in open_list:
                                open_list.append(norm_t)
                        elif "close" in action_str or "terminate" in action_str:
                            if norm_t in open_list:
                                open_list.remove(norm_t)
                elif pipe_res.status == ActionPipelineStatus.EXECUTED:
                    final_status = ConversationalActionStatus.EXECUTING
                else:
                    final_status = ConversationalActionStatus.FAILED

                # Si falló tras confirmación, preparar recuperación conversacional (Fase 64.3.4)
                if pipe_res.status in (ActionPipelineStatus.FAILED, ActionPipelineStatus.REJECTED, ActionPipelineStatus.EXECUTED):
                    fail_cat = classify_failure_category(pipe_res)
                    target_str = (
                        (pending.contract.action_intent.target if pending.contract and pending.contract.action_intent else None)
                        or (pending.action_intent.target if pending.action_intent else None)
                        or (pipe_res.contract.action_intent.target if pipe_res.contract and pipe_res.contract.action_intent else None)
                        or ""
                    )
                    action_str = (
                        (pending.contract.action_intent.intent_name if pending.contract and pending.contract.action_intent else None)
                        or "action"
                    )
                    rec_ctx = ActionRecoveryContext(
                        action_id=pending.action_id,
                        original_action_id=pending.action_id,
                        session_id=session_id,
                        intent=action_str,
                        target=str(target_str) if target_str else None,
                        parameters=pending.contract.action_intent.parameters if pending.contract and pending.contract.action_intent else {},
                        risk_level="HIGH" if any(w in action_str for w in ("close", "delete", "terminate")) else "SAFE",
                        failure_category=fail_cat,
                        failure_reason=pipe_res.error or "Error durante la ejecución",
                        recovery_state=ActionRecoveryState.RETRY_AVAILABLE,
                        retry_count=0,
                        max_retries=self.max_retries,
                        contract=pipe_res.contract or pending.contract,
                        pipeline_result=pipe_res,
                    )
                    with self._mutex:
                        self._recovery_contexts[session_id] = rec_ctx
                        self._last_failed_contexts[session_id] = ActionContext(
                            action_id=pending.action_id,
                            action=action_str,
                            skill="windows.apps",
                            operation="execute",
                            target=str(target_str),
                            status="FAILED",
                            timestamp=time.time(),
                            entities=(str(target_str),) if target_str else (),
                            ttl_seconds=ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds,
                        )

                    recovery_speech = build_recovery_prompt(
                        category=fail_cat,
                        target=str(target_str) if target_str else None,
                        raw_error=pipe_res.error,
                    )
                    return ConversationalActionResult(
                        status=final_status,
                        response_text=recovery_speech,
                        spoken_response=recovery_speech,
                        action_id=pending.action_id,
                        contract=pipe_res.contract or pending.contract,
                        pipeline_result=pipe_res,
                        is_terminal=False,
                        error=pipe_res.error,
                        recovery_context=rec_ctx,
                        recovery_state=ActionRecoveryState.RETRY_AVAILABLE,
                        recovery_available=True,
                    )

                return ConversationalActionResult(
                    status=final_status,
                    response_text=pipe_res.spoken_response or pipe_res.response_text,
                    spoken_response=pipe_res.spoken_response or pipe_res.response_text,
                    action_id=pending.action_id,
                    contract=pipe_res.contract or pending.contract,
                    pipeline_result=pipe_res,
                    is_terminal=True,
                    error=pipe_res.error,
                )

            # 1.2 CASO: NEGATIVO ("No", "Cancela", "Mejor no", etc.)
            if conf_choice is False:
                with self._mutex:
                    self._pending_confirmations.pop(session_id, None)

                logger.info(
                    f"[CONTROLLER CANCELLED] Confirmación rechazada por usuario para action_id={pending.action_id}."
                )

                pipe_res = self.pipeline.confirm_action(
                    action_id=pending.action_id,
                    user_confirmed=False,
                )

                cancel_speech = "Entendido, operación cancelada."
                return ConversationalActionResult(
                    status=ConversationalActionStatus.CANCELLED,
                    response_text=cancel_speech,
                    spoken_response=cancel_speech,
                    action_id=pending.action_id,
                    contract=pending.contract,
                    pipeline_result=pipe_res,
                    is_terminal=True,
                )

            # 1.3 CASO: NUEVA ORDEN DURANTE LA ESPERA ("Abre Chrome")
            # Descartar limpiamente la acción pendiente sin ejecutarla y proceder con la nueva orden
            with self._mutex:
                self._pending_confirmations.pop(session_id, None)

            logger.info(
                f"[CONTROLLER REDIRECT] Nueva orden recibida ('{user_input}'). "
                f"Descartando acción pendiente [{pending.action_id}] de forma segura."
            )
            self.pipeline.confirm_action(
                action_id=pending.action_id,
                user_confirmed=False,
            )
            # Continúa hacia abajo para procesar la nueva orden

        # ── 1.5. EVALUAR SI EXISTE RECUPERACIÓN CONVERSACIONAL PENDIENTE (FASE 64.3.4) ──
        with self._mutex:
            recovery_ctx = self._recovery_contexts.get(session_id)

        if recovery_ctx is not None and recovery_ctx.recovery_state in (
            ActionRecoveryState.RETRY_AVAILABLE,
            ActionRecoveryState.SEQUENCE_PAUSED,
            ActionRecoveryState.MODIFICATION_AVAILABLE,
        ):
            rec_intent, mod_detail = classify_recovery_intent(user_input, recovery_ctx)
            logger.info(
                f"[CONTROLLER RECOVERY] session_id={session_id} rec_intent={rec_intent} "
                f"detail={mod_detail} action_id={recovery_ctx.action_id}"
            )

            # 1.5.1 CASO CANCELACIÓN ("no", "cancela", "olvídalo", "ya no", "déjalo")
            if rec_intent == RecoveryUserIntent.CANCEL:
                recovery_ctx.mark_cancelled()
                with self._mutex:
                    self._recovery_contexts.pop(session_id, None)
                    pending_seq = self._pending_sequences.pop(session_id, None)
                    if pending_seq:
                        pending_seq.overall_status = ActionSequenceStatus.CANCELLED
                        for st in pending_seq.steps:
                            if st.status in (ActionStepStatus.RUNNING, ActionStepStatus.PENDING):
                                st.status = ActionStepStatus.SKIPPED

                cancel_speech = "Está bien, lo cancelo."
                try:
                    from core.experience import get_experience_logger
                    get_experience_logger().log_interaction(
                        user_input=user_input,
                        response_text=cancel_speech,
                        session_id=session_id,
                        intent_name="action_recovery_cancelled",
                        error_message="Recovery cancelled by user",
                        metadata_extra={"action_id": recovery_ctx.action_id, "recovery_state": "CANCELLED"},
                    )
                except Exception:
                    pass

                return ConversationalActionResult(
                    status=ConversationalActionStatus.CANCELLED,
                    response_text=cancel_speech,
                    spoken_response=cancel_speech,
                    action_id=recovery_ctx.action_id,
                    is_terminal=True,
                    recovery_context=recovery_ctx,
                    recovery_state=ActionRecoveryState.CANCELLED,
                    details={"recovery_state": "CANCELLED", "action_id": recovery_ctx.action_id},
                )

            # 1.5.2 CASO REINTENTO ("intenta de nuevo", "otra vez", "hazlo otra vez", "sí")
            if rec_intent == RecoveryUserIntent.RETRY:
                if not recovery_ctx.can_retry():
                    limit_speech = "Ya lo intenté varias veces y sigue sin funcionar. ¿Quieres que hagamos otra cosa?"
                    return ConversationalActionResult(
                        status=ConversationalActionStatus.FAILED,
                        response_text=limit_speech,
                        spoken_response=limit_speech,
                        action_id=recovery_ctx.action_id,
                        is_terminal=True,
                        recovery_context=recovery_ctx,
                        recovery_state=ActionRecoveryState.LIMIT_EXCEEDED,
                        recovery_available=False,
                        details={"recovery_state": "LIMIT_EXCEEDED"},
                    )

                recovery_ctx.increment_retry()
                new_action_id = recovery_ctx.next_retry_action_id()

                # Reintento dentro de una secuencia pausada
                if recovery_ctx.sequence_id and session_id in self._pending_sequences:
                    seq = self._pending_sequences[session_id]
                    if seq.current_step_index < len(seq.steps):
                        failed_step = seq.steps[seq.current_step_index]
                        failed_step.action_id = new_action_id
                        failed_step.status = ActionStepStatus.PENDING
                        for r_step in seq.steps[seq.current_step_index + 1 :]:
                            r_step.status = ActionStepStatus.PENDING
                        seq.overall_status = ActionSequenceStatus.RUNNING
                        seq_res = self._execute_sequence(
                            sequence=seq,
                            session_id=session_id,
                            custom_verifier=custom_verifier,
                            ttl_seconds=ttl_seconds,
                        )
                        if seq_res.status == ConversationalActionStatus.COMPLETED:
                            recovery_ctx.mark_resolved()
                            with self._mutex:
                                self._recovery_contexts.pop(session_id, None)
                        return seq_res

                # Reintento de acción individual (vuelve a pasar por el pipeline completo)
                eff_retry_risk = str(recovery_ctx.risk_level) if recovery_ctx.risk_level is not None else None
                if eff_retry_risk in ("3", "4", "5") or (
                    eff_retry_risk is None and any(w in (recovery_ctx.intent or "") for w in ("close", "delete", "kill", "terminate"))
                ):
                    eff_retry_risk = "HIGH"

                pipe_res = self.pipeline.execute(
                    user_input=f"Reintentar {recovery_ctx.target or recovery_ctx.intent}",
                    intent=recovery_ctx.intent,
                    parameters=recovery_ctx.parameters,
                    session_id=session_id,
                    request_id=new_action_id,
                    risk_level=eff_retry_risk,
                    custom_verifier=custom_verifier,
                )

                if pipe_res.status == ActionPipelineStatus.WAITING_CONFIRMATION:
                    ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
                    if pipe_res.contract:
                        pending_obj = PendingActionConfirmation(
                            action_id=pipe_res.action_id,
                            session_id=session_id,
                            contract=pipe_res.contract,
                            prompt=pipe_res.spoken_response or pipe_res.response_text,
                            action_intent=pipe_res.contract.action_intent,
                            status=ConversationalActionStatus.WAITING_CONFIRMATION,
                        )
                        with self._mutex:
                            self._pending_confirmations[session_id] = pending_obj
                    return ConversationalActionResult(
                        status=ConversationalActionStatus.WAITING_CONFIRMATION,
                        response_text=pipe_res.response_text,
                        spoken_response=pipe_res.spoken_response,
                        action_id=pipe_res.action_id,
                        contract=pipe_res.contract,
                        pipeline_result=pipe_res,
                        is_terminal=False,
                    )

                if pipe_res.status == ActionPipelineStatus.COMPLETED:
                    recovery_ctx.mark_resolved()
                    with self._mutex:
                        self._recovery_contexts.pop(session_id, None)
                    success_speech = "Listo, ahora sí."
                    self._update_context_after_step(
                        session_id,
                        ActionStep(
                            step_id=f"step-{new_action_id}",
                            action_id=new_action_id,
                            step_number=1,
                            intent=recovery_ctx.intent,
                            description=f"Reintento {recovery_ctx.target}",
                            target=str(recovery_ctx.target or ""),
                            parameters=recovery_ctx.parameters,
                            contract=pipe_res.contract,
                        ),
                        pipe_res,
                        ttl_seconds,
                    )
                    return ConversationalActionResult(
                        status=ConversationalActionStatus.COMPLETED,
                        response_text=success_speech,
                        spoken_response=success_speech,
                        action_id=new_action_id,
                        pipeline_result=pipe_res,
                        contract=pipe_res.contract,
                        is_terminal=True,
                        recovery_context=recovery_ctx,
                        recovery_state=ActionRecoveryState.RESOLVED,
                    )

                # Reintento falló nuevamente
                recovery_ctx.pipeline_result = pipe_res
                recovery_ctx.failure_reason = pipe_res.error or "Error en reintento"
                fail_cat = classify_failure_category(pipe_res)
                recovery_ctx.failure_category = fail_cat

                if recovery_ctx.can_retry():
                    retry_fail_speech = "Sigue sin funcionar. ¿Quieres que lo intente de nuevo?"
                    return ConversationalActionResult(
                        status=ConversationalActionStatus.FAILED,
                        response_text=retry_fail_speech,
                        spoken_response=retry_fail_speech,
                        action_id=new_action_id,
                        pipeline_result=pipe_res,
                        contract=pipe_res.contract,
                        is_terminal=False,
                        recovery_context=recovery_ctx,
                        recovery_state=ActionRecoveryState.RETRY_AVAILABLE,
                        recovery_available=True,
                        details={"retry_count": recovery_ctx.retry_count},
                    )
                else:
                    limit_speech = "Ya lo intenté varias veces y sigue sin funcionar. ¿Quieres que hagamos otra cosa?"
                    return ConversationalActionResult(
                        status=ConversationalActionStatus.FAILED,
                        response_text=limit_speech,
                        spoken_response=limit_speech,
                        action_id=new_action_id,
                        pipeline_result=pipe_res,
                        contract=pipe_res.contract,
                        is_terminal=True,
                        recovery_context=recovery_ctx,
                        recovery_state=ActionRecoveryState.LIMIT_EXCEEDED,
                        recovery_available=False,
                        details={"retry_count": recovery_ctx.retry_count},
                    )

            # 1.5.3 CASO MODIFICACIÓN ("mejor abre Chrome", "en vez de eso abre Y")
            if rec_intent == RecoveryUserIntent.MODIFY and mod_detail:
                recovery_ctx.recovery_state = ActionRecoveryState.MODIFICATION_AVAILABLE
                with self._mutex:
                    self._recovery_contexts.pop(session_id, None)

                # Modificación dentro de secuencia pausada
                if recovery_ctx.sequence_id and session_id in self._pending_sequences:
                    seq = self._pending_sequences[session_id]
                    if seq.current_step_index < len(seq.steps):
                        failed_step = seq.steps[seq.current_step_index]
                        norm = _normalize_app(mod_detail)
                        failed_step.target = norm
                        failed_step.description = f"Abrir {norm}"
                        failed_step.parameters = {"nombre_app": norm, "app_name": norm}
                        failed_step.action_id = f"mod-{failed_step.action_id}"
                        failed_step.status = ActionStepStatus.PENDING
                        for r_step in seq.steps[seq.current_step_index + 1 :]:
                            r_step.status = ActionStepStatus.PENDING
                        seq.overall_status = ActionSequenceStatus.RUNNING
                        return self._execute_sequence(
                            sequence=seq,
                            session_id=session_id,
                            custom_verifier=custom_verifier,
                            ttl_seconds=ttl_seconds,
                        )

                # Modificación de acción individual: despachar nueva intención sin reintentar la fallida
                return self.process_turn(
                    user_input=f"Abre {mod_detail}",
                    session_id=session_id,
                    custom_verifier=custom_verifier,
                    ttl_seconds=ttl_seconds,
                )

            # 1.5.4 CASO NO RELACIONADO ("¿qué hora es?")
            with self._mutex:
                self._recovery_contexts.pop(session_id, None)
                self._pending_sequences.pop(session_id, None)
            # Continúa hacia abajo para procesar la nueva orden con normalidad

        # ── 2. NO HAY ACCIÓN PENDIENTE ──
        # Si el usuario dice "Sí" o "No" sin tener nada pendiente, no inventar ni ejecutar nada
        orphan_choice = classify_confirmation_intent(user_input)
        if orphan_choice is not None:
            logger.info(f"[CONTROLLER ORPHAN] Respuesta '{user_input}' recibida sin acción pendiente.")
            idle_speech = "No tengo ninguna acción pendiente de confirmación."
            return ConversationalActionResult(
                status=ConversationalActionStatus.IDLE,
                response_text=idle_speech,
                spoken_response=idle_speech,
                is_terminal=True,
            )

        # ── 3. RESOLUCIÓN DE CONTINUIDAD CONTEXTUAL (FASE 64.3.2 Y 64.3.3) ──
        action_ctx = self.get_action_context(session_id)
        open_apps = self.get_session_open_apps(session_id)
        continuity_res = self.continuity_resolver.resolve(
            user_input=user_input,
            action_context=action_ctx,
            ttl_seconds=ttl_seconds,
            active_session_apps=open_apps,
        )

        eff_intent = intent
        eff_params = dict(parameters or {})
        eff_risk = risk_level
        extracted_entities: tuple[str, ...] = ()

        if continuity_res.is_reference:
            # Si es una referencia pero ambigua o expirada o sin contexto -> pedir aclaración
            if continuity_res.is_ambiguous or continuity_res.is_expired or not continuity_res.resolved_intent:
                q_text = continuity_res.clarification_question or "¿Podrías aclarar qué deseas hacer?"
                logger.info(
                    f"[CONTROLLER CLARIFY] Solicitud ambigua o expirada ('{user_input}'). "
                    f"Pregunta: '{q_text}'"
                )
                return ConversationalActionResult(
                    status=ConversationalActionStatus.CLARIFICATION_REQUIRED,
                    response_text=q_text,
                    spoken_response=q_text,
                    is_terminal=False,
                    error=continuity_res.reason,
                    details={"is_ambiguous": continuity_res.is_ambiguous, "is_expired": continuity_res.is_expired},
                )

            # Caso Multi-Target / Plural Resuelto (Fase 64.3.3)
            if continuity_res.is_plural and continuity_res.resolved_targets:
                logger.info(
                    f"[CONTROLLER PLURAL SEQUENCE] Secuencia multi-target resuelta: "
                    f"targets={continuity_res.resolved_targets}"
                )
                plural_seq = self.step_planner.plan_plural_sequence(
                    intent=continuity_res.resolved_intent or "close_application",
                    targets=list(continuity_res.resolved_targets),
                    session_id=session_id,
                    raw_input=user_input,
                )
                return self._execute_sequence(
                    sequence=plural_seq,
                    session_id=session_id,
                    custom_verifier=custom_verifier,
                    ttl_seconds=ttl_seconds,
                )

            # Referencia resuelta inequívocamente a un único target
            logger.info(
                f"[CONTROLLER CONTINUITY RESOLVED] Referente resuelto con éxito: "
                f"intent={continuity_res.resolved_intent} target={continuity_res.resolved_target}"
            )
            eff_intent = continuity_res.resolved_intent
            eff_params.update(continuity_res.resolved_parameters)
            if eff_risk is None:
                eff_risk = "HIGH" if any(w in eff_intent for w in ("close", "delete", "kill")) else "SAFE"
            if continuity_res.resolved_target:
                extracted_entities = (continuity_res.resolved_target,)
        else:
            # Entrada directa o nueva intención explícita
            # Comprobar si es una orden compuesta o secuencia explícita (Fase 64.3.3)
            if eff_intent is None and contract is None and self.step_planner.is_compound_or_sequence(user_input):
                comp_seq = self.step_planner.plan_sequence(user_input, session_id=session_id, context=action_ctx)
                if comp_seq and len(comp_seq.steps) > 1:
                    logger.info(
                        f"[CONTROLLER COMPOUND SEQUENCE] Secuencia de {len(comp_seq.steps)} pasos detectada para: '{user_input}'"
                    )
                    return self._execute_sequence(
                        sequence=comp_seq,
                        session_id=session_id,
                        custom_verifier=custom_verifier,
                        ttl_seconds=ttl_seconds,
                    )

            found_entities = self.continuity_resolver.extract_entities(user_input)
            if found_entities:
                extracted_entities = tuple(found_entities)

            if eff_intent is None and contract is None:
                inferred_intent, inferred_params, inferred_risk = self._infer_intent_and_params(user_input)
                eff_intent = inferred_intent
                eff_params.update(inferred_params)
                if eff_risk is None:
                    eff_risk = inferred_risk

        pipe_res = self.pipeline.execute(
            user_input=user_input,
            session_id=session_id,
            intent=eff_intent,
            parameters=eff_params,
            contract=contract,
            custom_verifier=custom_verifier,
            risk_level=eff_risk,
            confidence=confidence,
        )

        # 3.1 Si requiere confirmación humana (WAITING_CONFIRMATION)
        if pipe_res.status == ActionPipelineStatus.WAITING_CONFIRMATION:
            ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
            expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
            prompt = pipe_res.spoken_response or pipe_res.response_text
            act_intent = pipe_res.contract.action_intent if pipe_res.contract else None

            target_contract = pipe_res.contract or contract
            if target_contract is None:
                return ConversationalActionResult(
                    status=ConversationalActionStatus.FAILED,
                    response_text="Error interno: contrato de acción no disponible.",
                    spoken_response="Error interno: contrato de acción no disponible.",
                    action_id=pipe_res.action_id,
                    is_terminal=True,
                    error="Missing contract in WAITING_CONFIRMATION",
                )

            pending_obj = PendingActionConfirmation(
                action_id=pipe_res.action_id,
                session_id=session_id,
                contract=target_contract,
                action_intent=act_intent,
                prompt=prompt,
                expires_at=expires_at,
                status=ConversationalActionStatus.WAITING_CONFIRMATION,
            )

            with self._mutex:
                self._pending_confirmations[session_id] = pending_obj

            logger.info(
                f"[CONTROLLER PAUSED] Acción [{pipe_res.action_id}] pausada en espera de confirmación "
                f"(expira en {ttl}s)."
            )

            return ConversationalActionResult(
                status=ConversationalActionStatus.WAITING_CONFIRMATION,
                response_text=pipe_res.response_text,
                spoken_response=pipe_res.spoken_response,
                action_id=pipe_res.action_id,
                contract=pipe_res.contract,
                pipeline_result=pipe_res,
                is_terminal=False,
            )

        # 3.2 Otros resultados del pipeline
        elapsed = (time.perf_counter() - t_start) * 1000.0
        mapped_status = (
            ConversationalActionStatus.COMPLETED
            if pipe_res.status == ActionPipelineStatus.COMPLETED
            else (
                ConversationalActionStatus.CLARIFICATION_REQUIRED
                if pipe_res.status == ActionPipelineStatus.CLARIFICATION_REQUIRED
                else (
                    ConversationalActionStatus.REJECTED
                    if pipe_res.status == ActionPipelineStatus.REJECTED
                    else ConversationalActionStatus.FAILED
                )
            )
        )

        # Si se completó con éxito real, registrar en contexto de acción de la sesión (Fase 64.3.2)
        if pipe_res.status == ActionPipelineStatus.COMPLETED:
            target_val = (
                eff_params.get("app_name")
                or eff_params.get("nombre_app")
                or eff_params.get("target")
                or (extracted_entities[0] if extracted_entities else "app")
            )
            act_context = ActionContext(
                action_id=pipe_res.action_id,
                action=eff_intent or "action",
                skill=(
                    pipe_res.contract.execution_spec.skill_id
                    if pipe_res.contract and pipe_res.contract.execution_spec
                    else "windows.apps"
                ),
                operation=(
                    (pipe_res.contract.execution_spec.tool_name or "execute")
                    if pipe_res.contract and pipe_res.contract.execution_spec
                    else "execute"
                ),
                target=str(target_val),
                result=pipe_res.dispatch_result.output if pipe_res.dispatch_result else None,
                status="COMPLETED",
                timestamp=time.time(),
                entities=extracted_entities if extracted_entities else ((str(target_val),) if target_val else ()),
                ttl_seconds=ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds,
            )
            with self._mutex:
                self._action_contexts[session_id] = act_context

                # Actualizar aplicaciones activas en la sesión
                norm_target = _normalize_app(str(target_val))
                open_list = self._session_open_apps.setdefault(session_id, [])
                if "open" in (eff_intent or "") or "launch" in (eff_intent or ""):
                    if norm_target not in open_list:
                        open_list.append(norm_target)
                elif "close" in (eff_intent or "") or "terminate" in (eff_intent or ""):
                    if norm_target in open_list:
                        open_list.remove(norm_target)

        # Si la acción falló, fue rechazada o quedó no verificada, preparar recuperación conversacional (Fase 64.3.4)
        if pipe_res.status in (ActionPipelineStatus.FAILED, ActionPipelineStatus.REJECTED, ActionPipelineStatus.EXECUTED):
            fail_cat = classify_failure_category(pipe_res)
            target_val = (
                eff_params.get("app_name")
                or eff_params.get("nombre_app")
                or eff_params.get("target")
                or (extracted_entities[0] if extracted_entities else "app")
            )
            rec_ctx = ActionRecoveryContext(
                action_id=pipe_res.action_id,
                original_action_id=pipe_res.action_id,
                session_id=session_id,
                intent=eff_intent or "action",
                target=str(target_val) if target_val else None,
                parameters=eff_params,
                risk_level=eff_risk or ("HIGH" if any(w in (eff_intent or "") for w in ("close", "delete", "kill", "terminate")) else "SAFE"),
                failure_category=fail_cat,
                failure_reason=pipe_res.error or "Error durante la ejecución",
                recovery_state=ActionRecoveryState.RETRY_AVAILABLE,
                retry_count=0,
                max_retries=self.max_retries,
                contract=pipe_res.contract,
                pipeline_result=pipe_res,
                execution_result=pipe_res.dispatch_result.output if pipe_res.dispatch_result else None,
                verification_result=pipe_res.verification_report,
            )
            # Registrar contexto de fallo en ActionContext (status="FAILED") para continuidad (Regla 14)
            failed_act_ctx = ActionContext(
                action_id=pipe_res.action_id,
                action=eff_intent or "action",
                skill=(
                    pipe_res.contract.execution_spec.skill_id
                    if pipe_res.contract and pipe_res.contract.execution_spec
                    else "windows.apps"
                ),
                operation=(
                    (pipe_res.contract.execution_spec.tool_name or "execute")
                    if pipe_res.contract and pipe_res.contract.execution_spec
                    else "execute"
                ),
                target=str(target_val) if target_val else "app",
                status="FAILED",
                timestamp=time.time(),
                entities=extracted_entities if extracted_entities else ((str(target_val),) if target_val else ()),
                ttl_seconds=ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds,
            )
            with self._mutex:
                self._recovery_contexts[session_id] = rec_ctx
                self._last_failed_contexts[session_id] = failed_act_ctx

            recovery_speech = build_recovery_prompt(
                category=fail_cat,
                target=str(target_val) if target_val else None,
                raw_error=pipe_res.error,
            )

            try:
                from core.experience import get_experience_logger
                get_experience_logger().log_interaction(
                    user_input=user_input,
                    response_text=recovery_speech,
                    session_id=session_id,
                    intent_name=eff_intent or "action_failure",
                    error_message=pipe_res.error,
                    metadata_extra={"action_id": pipe_res.action_id, "failure_category": fail_cat.value},
                )
            except Exception:
                pass

            return ConversationalActionResult(
                status=mapped_status,
                response_text=recovery_speech,
                spoken_response=recovery_speech,
                action_id=pipe_res.action_id,
                contract=pipe_res.contract,
                pipeline_result=pipe_res,
                is_terminal=False,
                error=pipe_res.error,
                recovery_context=rec_ctx,
                recovery_state=ActionRecoveryState.RETRY_AVAILABLE,
                recovery_available=True,
                details={
                    "duration_ms": elapsed,
                    "recovery_state": ActionRecoveryState.RETRY_AVAILABLE.value,
                    "failure_category": fail_cat.value,
                    "can_retry": True,
                },
            )

        return ConversationalActionResult(
            status=mapped_status,
            response_text=pipe_res.response_text,
            spoken_response=pipe_res.spoken_response,
            action_id=pipe_res.action_id,
            contract=pipe_res.contract,
            pipeline_result=pipe_res,
            is_terminal=(mapped_status != ConversationalActionStatus.CLARIFICATION_REQUIRED),
            error=pipe_res.error,
            details={"duration_ms": elapsed},
        )

    # ── MOTOR DE EJECUCIÓN SECUENCIAL (FASE 64.3.3) ──────────────────────────

    def _execute_sequence(
        self,
        sequence: ActionSequence,
        session_id: str,
        custom_verifier: Any = None,
        ttl_seconds: float | None = None,
    ) -> ConversationalActionResult:
        """Ejecuta una secuencia multi-paso asegurando que cada paso pase por el ActionPipeline."""
        from core.execution.action_pipeline import ActionPipelineStatus

        sequence.overall_status = ActionSequenceStatus.RUNNING

        while sequence.current_step_index < len(sequence.steps):
            step = sequence.steps[sequence.current_step_index]

            # Idempotencia: si el paso ya fue completado, avanzar sin duplicar ejecución
            if step.status == ActionStepStatus.COMPLETED:
                sequence.current_step_index += 1
                continue

            step.status = ActionStepStatus.RUNNING

            try:
                # Cada paso pasa por: Planner -> Gate -> Confirmation -> Dispatcher -> Verifier -> Feedback
                pipe_res = self.pipeline.execute(
                    user_input=step.description or step.intent,
                    session_id=session_id,
                    intent=step.intent,
                    parameters=step.parameters,
                    custom_verifier=custom_verifier,
                    risk_level=step.risk_level,
                    request_id=step.action_id,
                )
            except Exception as exc:
                logger.error(
                    f"[SEQUENCE STEP EXCEPTION] Excepción ejecutando paso {step.step_number}: {exc}",
                    exc_info=True,
                )
                step.status = ActionStepStatus.FAILED
                step.error = str(exc)
                sequence.overall_status = ActionSequenceStatus.FAILED
                with self._mutex:
                    self._pending_sequences.pop(session_id, None)

                err_speech = f"Ocurrió un error al ejecutar el paso {step.step_number} ({step.description}): {exc}"
                return ConversationalActionResult(
                    status=ConversationalActionStatus.FAILED,
                    response_text=err_speech,
                    spoken_response=err_speech,
                    action_id=step.action_id,
                    is_terminal=True,
                    error=str(exc),
                    details={"sequence_id": sequence.sequence_id, "failed_step": step.step_number},
                )

            # 1. El paso requiere confirmación humana (WAITING_CONFIRMATION) -> La secuencia se PAUSA
            if pipe_res.status == ActionPipelineStatus.WAITING_CONFIRMATION:
                step.status = ActionStepStatus.WAITING_CONFIRMATION
                step.contract = pipe_res.contract
                sequence.overall_status = ActionSequenceStatus.WAITING_CONFIRMATION
                with self._mutex:
                    self._pending_sequences[session_id] = sequence

                prompt_text = pipe_res.spoken_response or pipe_res.response_text or f"¿Confirmas {step.description}?"
                logger.info(
                    f"[SEQUENCE PAUSED] Secuencia {sequence.sequence_id} pausada en paso {step.step_number} por confirmación."
                )
                return ConversationalActionResult(
                    status=ConversationalActionStatus.WAITING_CONFIRMATION,
                    response_text=prompt_text,
                    spoken_response=prompt_text,
                    action_id=step.action_id,
                    contract=pipe_res.contract,
                    pipeline_result=pipe_res,
                    is_terminal=False,
                    details={"sequence_id": sequence.sequence_id, "paused_at_step": step.step_number},
                )

            # 2. El paso culminó con éxito verificado (COMPLETED o EXECUTED)
            if pipe_res.status in (ActionPipelineStatus.EXECUTED, ActionPipelineStatus.COMPLETED):
                step.status = ActionStepStatus.COMPLETED
                step.contract = pipe_res.contract
                step.pipeline_result = pipe_res

                # Actualizar contexto conversacional tras este paso verificado
                self._update_context_after_step(session_id, step, pipe_res, ttl_seconds)

                # Avanzar ordenadamente al siguiente paso
                sequence.current_step_index += 1
                continue

            # 3. El paso falló (FAILED / SECURITY_DENIED / REJECTED)
            step.status = ActionStepStatus.FAILED
            step.contract = pipe_res.contract
            step.pipeline_result = pipe_res
            step.error = pipe_res.error or "Falló la ejecución del paso"

            if sequence.policy == SequenceFailurePolicy.STOP_ON_FAILURE:
                # Marcar pasos posteriores dependientes como SKIPPED
                for rem_step in sequence.steps[sequence.current_step_index + 1 :]:
                    rem_step.status = ActionStepStatus.SKIPPED

                sequence.overall_status = ActionSequenceStatus.FAILED

                fail_cat = classify_failure_category(pipe_res)
                rec_ctx = ActionRecoveryContext(
                    action_id=step.action_id,
                    original_action_id=step.action_id,
                    session_id=session_id,
                    intent=step.intent,
                    target=step.target,
                    parameters=step.parameters,
                    risk_level=step.risk_level,
                    failure_category=fail_cat,
                    failure_reason=step.error or "Error durante el paso",
                    recovery_state=ActionRecoveryState.SEQUENCE_PAUSED,
                    retry_count=0,
                    max_retries=self.max_retries,
                    sequence_id=sequence.sequence_id,
                    step_id=step.step_id,
                    step_number=step.step_number,
                    contract=pipe_res.contract,
                    pipeline_result=pipe_res,
                )
                with self._mutex:
                    self._recovery_contexts[session_id] = rec_ctx
                    self._pending_sequences[session_id] = sequence

                # Registrar contexto de fallo para recuperación y trazabilidad (Regla 14)
                if step.target:
                    self._last_failed_contexts[session_id] = ActionContext(
                        action_id=step.action_id,
                        action=step.intent,
                        skill="windows.apps",
                        operation="launch_app",
                        target=str(step.target),
                        status="FAILED",
                        timestamp=time.time(),
                        entities=(str(step.target),),
                        ttl_seconds=ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds,
                    )

                if sequence.completed_steps:
                    completed_names = [s.target or s.description for s in sequence.completed_steps]
                    comp_text = f"Abrí {' y '.join(completed_names)}" if len(completed_names) <= 2 else f"Completé los primeros {len(completed_names)} pasos"
                    fail_speech = f"{comp_text}, pero ocurrió un error en el paso {step.step_number} ({step.description}): {step.error or 'no pudo completarse'}. ¿Quieres que lo intente de nuevo?"
                else:
                    fail_speech = f"La secuencia no pudo completarse debido a un error en el paso {step.step_number} ({step.description}): {step.error}."
                    fail_speech += " ¿Quieres que lo intente de nuevo?"

                try:
                    from core.experience import get_experience_logger
                    get_experience_logger().log_interaction(
                        user_input=sequence.raw_input,
                        response_text=fail_speech,
                        session_id=session_id,
                        intent_name=step.intent,
                        error_message=step.error,
                        metadata_extra={"sequence_id": sequence.sequence_id, "failed_step": step.step_number},
                    )
                except Exception:
                    pass

                return ConversationalActionResult(
                    status=ConversationalActionStatus.FAILED,
                    response_text=fail_speech,
                    spoken_response=fail_speech,
                    action_id=step.action_id,
                    contract=pipe_res.contract,
                    pipeline_result=pipe_res,
                    is_terminal=False,
                    error=step.error,
                    recovery_context=rec_ctx,
                    recovery_state=ActionRecoveryState.SEQUENCE_PAUSED,
                    recovery_available=True,
                    details={
                        "sequence_id": sequence.sequence_id,
                        "failed_step": step.step_number,
                        "recovery_state": ActionRecoveryState.SEQUENCE_PAUSED.value,
                    },
                )

        # Todos los pasos completados exitosamente
        sequence.overall_status = ActionSequenceStatus.COMPLETED
        with self._mutex:
            self._pending_sequences.pop(session_id, None)

        last_step = sequence.steps[-1] if sequence.steps else None

        # Si la secuencia involucró múltiples entidades/aplicaciones en el mismo comando compuesto,
        # registrar dichas entidades en el ActionContext para detectar ambigüedad si el usuario dice "ciérralo"
        if len(sequence.steps) > 1 and last_step:
            all_targets = tuple(
                str(s.target or s.parameters.get("app_name") or "")
                for s in sequence.completed_steps
                if (s.target or s.parameters.get("app_name"))
            )
            if len(all_targets) > 1:
                cur_ctx = self._action_contexts.get(session_id)
                if cur_ctx:
                    self._action_contexts[session_id] = ActionContext(
                        action_id=cur_ctx.action_id,
                        action=cur_ctx.action,
                        skill=cur_ctx.skill,
                        operation=cur_ctx.operation,
                        target=cur_ctx.target,
                        result=cur_ctx.result,
                        status=cur_ctx.status,
                        timestamp=cur_ctx.timestamp,
                        entities=all_targets,
                        ttl_seconds=cur_ctx.ttl_seconds,
                    )
        completed_descs = [s.description for s in sequence.completed_steps]
        if len(sequence.steps) == 2:
            summary_speech = f"Listo, completé la secuencia: {completed_descs[0]} y {completed_descs[1]}."
        elif len(sequence.steps) > 2:
            summary_speech = f"Listo, completé los {len(sequence.steps)} pasos solicitados."
        else:
            summary_speech = (
                last_step.pipeline_result.spoken_response
                if last_step and last_step.pipeline_result and last_step.pipeline_result.spoken_response
                else "Listo, acción completada."
            )

        return ConversationalActionResult(
            status=ConversationalActionStatus.COMPLETED,
            response_text=summary_speech,
            spoken_response=summary_speech,
            action_id=last_step.action_id if last_step else sequence.sequence_id,
            contract=last_step.contract if last_step else None,
            pipeline_result=last_step.pipeline_result if last_step else None,
            is_terminal=True,
            details={"sequence_id": sequence.sequence_id, "steps_count": len(sequence.steps)},
        )

    def _continue_sequence(
        self,
        sequence: ActionSequence,
        session_id: str,
        user_confirmed: bool,
        custom_verifier: Any = None,
        ttl_seconds: float | None = None,
    ) -> ConversationalActionResult:
        """Reanuda una secuencia pausada tras la confirmación o rechazo del usuario."""
        from core.execution.action_pipeline import ActionPipelineStatus

        pending_step = sequence.pending_step
        if not pending_step:
            with self._mutex:
                self._pending_sequences.pop(session_id, None)
            return ConversationalActionResult(
                status=ConversationalActionStatus.IDLE,
                response_text="No hay paso pendiente en la secuencia.",
                spoken_response="No hay paso pendiente en la secuencia.",
                is_terminal=True,
            )

        # Caso Rechazo / Cancelación del usuario ("No", "Cancelar", "Mejor no", etc.)
        if not user_confirmed:
            logger.info(
                f"[SEQUENCE CANCELLED] Usuario rechazó paso {pending_step.step_number} "
                f"de la secuencia {sequence.sequence_id}."
            )
            pipe_res = self.pipeline.confirm_action(action_id=pending_step.action_id, user_confirmed=False)
            pending_step.status = ActionStepStatus.REJECTED
            sequence.overall_status = ActionSequenceStatus.CANCELLED
            for rem_step in sequence.steps[sequence.current_step_index + 1 :]:
                rem_step.status = ActionStepStatus.SKIPPED
            with self._mutex:
                self._pending_sequences.pop(session_id, None)

            cancel_speech = "Entendido, operación cancelada."
            return ConversationalActionResult(
                status=ConversationalActionStatus.CANCELLED,
                response_text=cancel_speech,
                spoken_response=cancel_speech,
                action_id=pending_step.action_id,
                pipeline_result=pipe_res,
                is_terminal=True,
                details={"sequence_id": sequence.sequence_id, "rejected_step": pending_step.step_number},
            )

        # Caso Confirmación Afirmativa ("Sí", "Claro", "Adelante", etc.)
        logger.info(
            f"[SEQUENCE RESUME] Confirmando paso {pending_step.step_number} "
            f"de la secuencia {sequence.sequence_id}."
        )
        pipe_res = self.pipeline.confirm_action(
            action_id=pending_step.action_id,
            user_confirmed=True,
            custom_verifier=custom_verifier,
        )

        if pipe_res.status in (ActionPipelineStatus.EXECUTED, ActionPipelineStatus.COMPLETED):
            pending_step.status = ActionStepStatus.COMPLETED
            pending_step.pipeline_result = pipe_res
            self._update_context_after_step(session_id, pending_step, pipe_res, ttl_seconds)
            sequence.current_step_index += 1

            # Si quedan más pasos, continuar con la ejecución del resto de la secuencia
            if sequence.current_step_index < len(sequence.steps):
                return self._execute_sequence(sequence, session_id, custom_verifier=custom_verifier, ttl_seconds=ttl_seconds)

            # Si ya se completaron todos los pasos
            sequence.overall_status = ActionSequenceStatus.COMPLETED
            with self._mutex:
                self._pending_sequences.pop(session_id, None)

            completed_descs = [s.description for s in sequence.completed_steps]
            if len(sequence.steps) == 2:
                final_speech = f"Listo, completé la secuencia: {completed_descs[0]} y {completed_descs[1]}."
            elif len(sequence.steps) > 2:
                final_speech = f"Listo, completé los {len(sequence.steps)} pasos solicitados."
            else:
                final_speech = pipe_res.spoken_response or pipe_res.response_text or "Listo, acción completada."

            return ConversationalActionResult(
                status=ConversationalActionStatus.COMPLETED,
                response_text=final_speech,
                spoken_response=final_speech,
                action_id=pending_step.action_id,
                contract=pending_step.contract,
                pipeline_result=pipe_res,
                is_terminal=True,
                details={"sequence_id": sequence.sequence_id, "completed_steps": len(sequence.steps)},
            )
        else:
            pending_step.status = ActionStepStatus.FAILED
            pending_step.pipeline_result = pipe_res
            pending_step.error = pipe_res.error
            sequence.overall_status = ActionSequenceStatus.FAILED
            for rem_step in sequence.steps[sequence.current_step_index + 1 :]:
                rem_step.status = ActionStepStatus.SKIPPED

            fail_cat = classify_failure_category(pipe_res)
            rec_ctx = ActionRecoveryContext(
                action_id=pending_step.action_id,
                original_action_id=pending_step.action_id,
                session_id=session_id,
                intent=pending_step.intent,
                target=pending_step.target,
                parameters=pending_step.parameters,
                risk_level=pending_step.risk_level,
                failure_category=fail_cat,
                failure_reason=pipe_res.error or "Error durante la ejecución del paso",
                recovery_state=ActionRecoveryState.SEQUENCE_PAUSED,
                retry_count=0,
                max_retries=self.max_retries,
                sequence_id=sequence.sequence_id,
                step_id=pending_step.step_id,
                step_number=pending_step.step_number,
                contract=pending_step.contract,
                pipeline_result=pipe_res,
            )
            with self._mutex:
                self._recovery_contexts[session_id] = rec_ctx
                self._pending_sequences[session_id] = sequence

            fail_speech = f"Falló el paso {pending_step.step_number}: {pipe_res.error or 'error de ejecución'}. ¿Quieres que lo intente de nuevo?"
            return ConversationalActionResult(
                status=ConversationalActionStatus.FAILED,
                response_text=fail_speech,
                spoken_response=fail_speech,
                action_id=pending_step.action_id,
                pipeline_result=pipe_res,
                is_terminal=False,
                error=pipe_res.error,
                recovery_context=rec_ctx,
                recovery_state=ActionRecoveryState.SEQUENCE_PAUSED,
                recovery_available=True,
                details={"sequence_id": sequence.sequence_id, "failed_step": pending_step.step_number},
            )

    def _update_context_after_step(
        self,
        session_id: str,
        step: ActionStep,
        pipe_res: ActionPipelineResult,
        ttl_seconds: float | None = None,
    ) -> None:
        """Actualiza el contexto conversacional y las aplicaciones activas tras un paso exitoso."""
        target_val = step.target or step.parameters.get("app_name") or "app"
        with self._mutex:
            # Actualizar lista de aplicaciones abiertas activas en la sesión
            norm_target = _normalize_app(str(target_val))
            open_list = self._session_open_apps.setdefault(session_id, [])
            if "open" in step.intent or "launch" in step.intent:
                if norm_target not in open_list:
                    open_list.append(norm_target)
            elif "close" in step.intent or "terminate" in step.intent:
                if norm_target in open_list:
                    open_list.remove(norm_target)

            all_entities = (str(target_val),)

            act_ctx = ActionContext(
                action_id=step.action_id,
                action=step.intent,
                skill=(
                    step.contract.execution_spec.skill_id
                    if step.contract and step.contract.execution_spec
                    else "windows.apps"
                ),
                operation=(
                    (step.contract.execution_spec.tool_name or "execute")
                    if step.contract and step.contract.execution_spec
                    else "execute"
                ),
                target=str(target_val),
                result=pipe_res.dispatch_result.output if pipe_res.dispatch_result else None,
                status="COMPLETED",
                timestamp=time.time(),
                entities=all_entities,
                ttl_seconds=ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds,
            )
            self._action_contexts[session_id] = act_ctx

    # ── HEURÍSTICA DE INFERENCIA DE INTENCIÓN PARA ENTRADA LIBRE ─────────────

    def _infer_intent_and_params(self, text: str) -> tuple[str, dict[str, Any], str | None]:
        """Infiere la intención y parámetros de acciones habituales para texto libre."""
        lower = text.lower().strip()

        # Cierre de aplicación (riesgo HIGH -> requiere confirmación)
        if any(w in lower for w in ("cierra", "cerrar", "kill", "termina", "apaga")):
            target = (
                "notepad" if any(a in lower for a in ("bloc", "notas", "notepad")) else (
                    "calc" if any(a in lower for a in ("calc", "calculadora")) else (
                        "chrome" if "chrome" in lower else (
                            "edge" if "edge" in lower else (
                                "paint" if "paint" in lower else (
                                    "spotify" if "spotify" in lower else "app"
                                )
                            )
                        )
                    )
                )
            )
            return "close_application", {"nombre_app": target, "app_name": target}, "HIGH"

        # Apertura de aplicación (riesgo SAFE -> ejecución directa)
        if any(w in lower for w in ("abre", "abrir", "launch", "ejecuta", "inicia")):
            target = (
                "calc" if any(a in lower for a in ("calc", "calculadora")) else (
                    "notepad" if any(a in lower for a in ("bloc", "notas", "notepad")) else (
                        "chrome" if "chrome" in lower else (
                            "edge" if "edge" in lower else (
                                "paint" if "paint" in lower else (
                                    "spotify" if "spotify" in lower else (
                                        "youtube" if "youtube" in lower else "app"
                                    )
                                )
                            )
                        )
                    )
                )
            )
            return "open_application", {"nombre_app": target, "app_name": target}, "SAFE"

        # Eliminación de archivo (riesgo DANGEROUS -> requiere confirmación)
        if any(w in lower for w in ("elimina", "borra", "destruye")):
            return "delete_file", {"path": "C:\\temp.txt"}, "DANGEROUS"

        return "open_application", {}, "SAFE"


def get_conversational_action_controller() -> ConversationalActionController:
    """Factory helper para obtener la instancia única del ConversationalActionController."""
    return ConversationalActionController.get_instance()


__all__ = [
    "ConversationalActionController",
    "ConversationalActionResult",
    "ConversationalActionStatus",
    "PendingActionConfirmation",
    "classify_confirmation_intent",
    "get_conversational_action_controller",
]
