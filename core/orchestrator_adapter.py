"""Adaptador de integración del Orchestrator con Event Bus y State Machine para JESSYCA 4.0.

Conecta el flujo de eventos de voz (UtteranceFinal) con el Orchestrator existente de JESSYCA
(JessycaLocalAgent / orquestador), manteniendo la State Machine sincronizada y publicando
eventos tipados correspondientes (IntentClassified, ActionProposed, ClarificationRequested,
SpeakRequested, ErrorOccurred) sin duplicar la lógica de decisión ni romper la arquitectura asíncrona.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import traceback
import uuid
from typing import Any

from core.bus import EventBus, get_event_bus
from core.events.base import (
    ActionProposed,
    ClarificationRequested,
    ErrorOccurred,
    IntentClassified,
    SpeakRequested,
    UtteranceFinal,
)
from core.logger import get_logger
from core.state.machine import StateMachine
from core.state.states import SessionState

logger = get_logger("jessyca.orchestrator_adapter")


class OrchestratorAdapter:
    """Adaptador que conecta UtteranceFinal del Event Bus con el Orchestrator existente."""

    def __init__(
        self,
        orchestrator: Any | None = None,
        event_bus: EventBus | None = None,
        state_machine: StateMachine | None = None,
        fast_router: Any | None = None,
    ) -> None:
        """Inicializa el adaptador del orquestador.

        Args:
            orchestrator: Instancia del orquestador (JessycaLocalAgent o compatible).
                Si es None, se cargará bajo demanda (lazy).
            event_bus: Instancia de EventBus. Si es None, utiliza get_event_bus().
            state_machine: Instancia opcional de StateMachine para sincronizar estados.
            fast_router: Instancia opcional de FastRouter para pre-clasificación rápida.
        """
        self._orchestrator = orchestrator
        self._event_bus = event_bus or get_event_bus()
        self._state_machine = state_machine
        self._fast_router = fast_router
        self._lock = threading.Lock()
        self._started = False
        self._current_session_id: str | None = None

    @property
    def is_started(self) -> bool:
        """Indica si el adaptador está actualmente suscrito al Event Bus."""
        return self._started

    @property
    def current_session_id(self) -> str | None:
        """Devuelve el session_id activo."""
        return self._current_session_id

    def start(self) -> None:
        """Inicia el adaptador suscribiéndose a UtteranceFinal en el Event Bus de forma idempotente."""
        with self._lock:
            if self._started:
                logger.debug("[ORCHESTRATOR_ADAPTER] start() ignorado: ya está iniciado.")
                return

            self._event_bus.subscribe(
                UtteranceFinal,
                self.on_utterance_final,
            )
            self._started = True
            logger.info("[ORCHESTRATOR_ADAPTER] Adaptador iniciado y suscrito a UtteranceFinal.")

    def stop(self) -> None:
        """Detiene el adaptador cancelando la suscripción al Event Bus."""
        with self._lock:
            if not self._started:
                return

            self._event_bus.unsubscribe(UtteranceFinal, self.on_utterance_final)
            self._started = False
            logger.info("[ORCHESTRATOR_ADAPTER] Adaptador detenido y desuscrito.")

    def __enter__(self) -> OrchestratorAdapter:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    async def __aenter__(self) -> OrchestratorAdapter:
        self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    def _ensure_orchestrator(self) -> Any:
        """Obtiene la instancia del orquestador existente si no fue inyectada."""
        if self._orchestrator is None:
            try:
                from core.local_agent.local_agent import JessycaLocalAgent

                self._orchestrator = JessycaLocalAgent.get_instance()
            except Exception as exc:
                logger.warning(
                    f"[ORCHESTRATOR_ADAPTER] No se pudo obtener JessycaLocalAgent: {exc}"
                )
        return self._orchestrator

    def _transition_to_routing_if_needed(self) -> None:
        """Garantiza de forma segura que la State Machine se encuentre en ROUTING."""
        if self._state_machine is None:
            return

        current = self._state_machine.current_state
        if current == SessionState.ROUTING:
            return

        try:
            if self._state_machine.can_transition_to(SessionState.ROUTING):
                self._state_machine.transition_to(SessionState.ROUTING)
            elif current == SessionState.LISTENING:
                self._state_machine.transition_to(SessionState.TRANSCRIBING)
                self._state_machine.transition_to(SessionState.ROUTING)
            elif current == SessionState.IDLE:
                self._state_machine.transition_to(SessionState.WAKEWORD)
                self._state_machine.transition_to(SessionState.LISTENING)
                self._state_machine.transition_to(SessionState.TRANSCRIBING)
                self._state_machine.transition_to(SessionState.ROUTING)
            elif current == SessionState.WAKEWORD:
                self._state_machine.transition_to(SessionState.LISTENING)
                self._state_machine.transition_to(SessionState.TRANSCRIBING)
                self._state_machine.transition_to(SessionState.ROUTING)
        except Exception as exc:
            logger.warning(
                f"[ORCHESTRATOR_ADAPTER] No se pudo transicionar State Machine a ROUTING desde {current}: {exc}"
            )

    async def on_utterance_final(self, event: UtteranceFinal) -> None:
        """Handler asíncrono para eventos UtteranceFinal.

        1. Extrae el texto y conserva session_id y metadata.
        2. Garantiza que la State Machine esté en ROUTING.
        3. Ejecuta el Orchestrator sin bloquear innecesariamente el Event Bus.
        4. Publica IntentClassified y la decisión (ActionProposed, ClarificationRequested o SpeakRequested).
        5. Actualiza la State Machine según el resultado.
        6. Aísla errores publicando ErrorOccurred y recuperando la State Machine a IDLE.
        """
        raw_text = (event.text or "").strip()
        if not raw_text:
            logger.debug("[ORCHESTRATOR_ADAPTER] UtteranceFinal con texto vacío ignorado.")
            return

        # Conservar session_id
        session_id = event.session_id or self._current_session_id
        if not session_id:
            if self._state_machine is not None:
                session_id = self._state_machine.session_id
            else:
                session_id = "default_session"
        self._current_session_id = session_id

        logger.info(
            f"[ORCHESTRATOR_ADAPTER] Procesando UtteranceFinal: '{raw_text}' (session_id={session_id})"
        )

        # 1. Asegurar estado ROUTING en State Machine
        self._transition_to_routing_if_needed()

        try:
            # 1.5. Pre-evaluación con Fast Router si está disponible
            if self._fast_router is not None:
                decision = self._fast_router.route(raw_text)
                cat_val = str(getattr(decision.category, "value", decision.category))

                if cat_val == "COMMAND" and decision.confidence >= 0.80:
                    intent_event = IntentClassified(
                        intent=decision.intent,
                        confidence=decision.confidence,
                        slots=decision.parameters,
                        raw_text=raw_text,
                        session_id=session_id,
                        metadata={"source": "fast_router", **event.metadata},
                    )
                    await self._event_bus.publish(intent_event)

                    action_id = getattr(event, "action_id", None) or f"act-{uuid.uuid4().hex[:8]}"
                    cmd_params = dict(decision.parameters)
                    cmd_params.setdefault("action_id", action_id)
                    action_event = ActionProposed(
                        action_name=decision.target_skill or decision.intent,
                        action_id=action_id,
                        parameters=cmd_params,
                        source="fast_router",
                        session_id=session_id,
                        metadata={
                            "intent": decision.intent,
                            "requires_confirmation": decision.requires_confirmation,
                            "action_id": action_id,
                            **event.metadata,
                        },
                    )
                    await self._event_bus.publish(action_event)

                    if self._state_machine is not None:
                        if decision.requires_confirmation:
                            if self._state_machine.can_transition_to(SessionState.CONFIRMING):
                                self._state_machine.transition_to(SessionState.CONFIRMING)
                        else:
                            if self._state_machine.can_transition_to(SessionState.EXECUTING):
                                self._state_machine.transition_to(SessionState.EXECUTING)
                    return

                elif cat_val == "CONVERSATION" and decision.suggested_response and decision.confidence >= 0.80:
                    intent_event = IntentClassified(
                        intent=decision.intent,
                        confidence=decision.confidence,
                        slots=decision.parameters,
                        raw_text=raw_text,
                        session_id=session_id,
                        metadata={"source": "fast_router", **event.metadata},
                    )
                    await self._event_bus.publish(intent_event)

                    speak_event = SpeakRequested(
                        text=decision.suggested_response,
                        session_id=session_id,
                        metadata={"intent": decision.intent, "source": "fast_router", **event.metadata},
                    )
                    await self._event_bus.publish(speak_event)

                    if self._state_machine is not None and self._state_machine.can_transition_to(SessionState.RESPONDING):
                        self._state_machine.transition_to(SessionState.RESPONDING)
                    return

                elif cat_val == "AMBIGUOUS" and decision.suggested_response:
                    intent_event = IntentClassified(
                        intent=decision.intent,
                        confidence=decision.confidence,
                        slots=decision.parameters,
                        raw_text=raw_text,
                        session_id=session_id,
                        metadata={"source": "fast_router", **event.metadata},
                    )
                    await self._event_bus.publish(intent_event)

                    clarif_event = ClarificationRequested(
                        question=decision.suggested_response,
                        original_text=raw_text,
                        session_id=session_id,
                        context={"intent": decision.intent},
                        metadata={"source": "fast_router", **event.metadata},
                    )
                    await self._event_bus.publish(clarif_event)

                    if self._state_machine is not None and self._state_machine.can_transition_to(SessionState.CLARIFYING):
                        self._state_machine.transition_to(SessionState.CLARIFYING)
                    return

            # 2. Invocar Orchestrator existente de forma no bloqueante
            orchestrator = self._ensure_orchestrator()
            if orchestrator is None:
                raise RuntimeError("No hay un orquestador disponible para procesar la petición.")

            res = await self._call_orchestrator(orchestrator, raw_text, session_id, event.metadata)

            # 3. Procesar y traducir el resultado a eventos tipados y transiciones
            action_id = getattr(event, "action_id", None) or f"act-{uuid.uuid4().hex[:8]}"
            await self._handle_orchestrator_result(res, raw_text, session_id, event.metadata, action_id=action_id)

        except Exception as exc:
            logger.error(
                f"[ORCHESTRATOR_ADAPTER] Excepción durante la ejecución del orquestador: {exc}",
                exc_info=True,
            )
            # Publicar ErrorOccurred al Event Bus sin tumbar el bus
            try:
                error_event = ErrorOccurred(
                    error_message=str(exc),
                    error_type=exc.__class__.__name__,
                    session_id=session_id,
                    details={"raw_text": raw_text},
                    traceback=traceback.format_exc(),
                )
                await self._event_bus.publish(error_event)
            except Exception as bus_err:
                logger.error(
                    f"[ORCHESTRATOR_ADAPTER] Error al publicar ErrorOccurred en Event Bus: {bus_err}"
                )

            # Recuperar State Machine a un estado válido (IDLE)
            if self._state_machine is not None:
                try:
                    if self._state_machine.can_transition_to(SessionState.IDLE):
                        self._state_machine.transition_to(SessionState.IDLE)
                    else:
                        self._state_machine.reset(new_session_id=session_id)
                except Exception as sm_err:
                    logger.error(
                        f"[ORCHESTRATOR_ADAPTER] Error al recuperar State Machine a IDLE: {sm_err}"
                    )

    async def _call_orchestrator(
        self,
        orchestrator: Any,
        text: str,
        session_id: str,
        metadata: dict[str, Any],
    ) -> Any:
        """Invoca el orquestador en un hilo secundario si es síncrono para no bloquear el Event Bus."""
        # 1. Caso: JessycaLocalAgent (posee método .interact)
        if hasattr(orchestrator, "interact"):
            from core.local_agent.local_agent_models import InputModality, JessycaRequest

            req = JessycaRequest(
                session_id=session_id,
                user_input=text,
                modality=InputModality.VOICE,
                metadata=metadata,
            )
            if inspect.iscoroutinefunction(orchestrator.interact):
                return await orchestrator.interact(req)
            return await asyncio.to_thread(orchestrator.interact, req)

        # 2. Caso: Callable directo (función síncrona o asíncrona)
        if callable(orchestrator):
            if inspect.iscoroutinefunction(orchestrator):
                return await orchestrator(text)
            return await asyncio.to_thread(orchestrator, text)

        # 3. Caso: Módulo orquestador legacy con ejecutar_orden_texto
        if hasattr(orchestrator, "ejecutar_orden_texto"):
            return await asyncio.to_thread(orchestrator.ejecutar_orden_texto, text)

        raise TypeError(f"El orquestador proporcionado tiene un tipo incompatible: {type(orchestrator)}")

    async def _handle_orchestrator_result(
        self,
        res: Any,
        raw_text: str,
        session_id: str,
        metadata: dict[str, Any],
        action_id: str | None = None,
    ) -> None:
        """Interpreta la salida del orquestador y emite los eventos tipados y transiciones correspondientes."""
        # Extraer metadatos comunes de intención
        intent_name = "unknown"
        confidence = 1.0
        slots: dict[str, Any] = {}

        if hasattr(res, "intent") and res.intent:
            intent_name = str(res.intent)
        elif isinstance(res, dict) and "intent" in res:
            intent_name = str(res["intent"])

        action_contract = getattr(res, "action_intent_contract", None)
        if action_contract is not None and hasattr(action_contract, "action_intent"):
            contract_slots = getattr(action_contract.action_intent, "parameters", {})
            if isinstance(contract_slots, dict):
                slots = contract_slots

        # Publicar SIEMPRE IntentClassified si se identificó o procesó la intención
        intent_event = IntentClassified(
            intent=intent_name,
            confidence=confidence,
            slots=slots,
            raw_text=raw_text,
            session_id=session_id,
            metadata=metadata,
        )
        await self._event_bus.publish(intent_event)

        # ── CASO A: Clarificación requerida ───────────────────────────────────
        is_clarification = False
        clarification_q = ""

        res_status = getattr(res, "status", None)
        if getattr(res, "requires_clarification", False):
            is_clarification = True
            raw_q = (
                getattr(res, "clarification_question", None)
                or getattr(res, "spoken_text", None)
                or getattr(res, "response_text", "")
            )
            clarification_q = str(raw_q or "")
        elif res_status is not None and str(res_status).endswith("AWAITING_CLARIFICATION"):
            is_clarification = True
            raw_q = (
                getattr(res, "clarification_question", None)
                or getattr(res, "response_text", "")
            )
            clarification_q = str(raw_q or "")
        elif isinstance(res, dict) and (res.get("requires_clarification") or res.get("type") == "clarification"):
            is_clarification = True
            clarification_q = str(res.get("question") or res.get("clarification_question") or res.get("text", ""))

        if is_clarification:
            clarif_event = ClarificationRequested(
                question=clarification_q or "¿Podrías aclarar tu solicitud?",
                original_text=raw_text,
                session_id=session_id,
                context={"intent": intent_name},
                metadata=metadata,
            )
            await self._event_bus.publish(clarif_event)

            if self._state_machine is not None and self._state_machine.can_transition_to(SessionState.CLARIFYING):
                self._state_machine.transition_to(SessionState.CLARIFYING)
            return

        # ── CASO B: Propuesta de Acción ──────────────────────────────────────
        is_action = False
        action_name = ""
        parameters: dict[str, Any] = {}
        requires_confirmation = False

        selected_skill = getattr(res, "selected_skill", None)
        if selected_skill and str(selected_skill).lower() not in ("auto", "none", "", "conversational"):
            is_action = True
            action_name = str(selected_skill)
            out_data = getattr(res, "output_data", {})
            if isinstance(out_data, dict):
                parameters = out_data
            requires_confirmation = bool(getattr(res, "requires_confirmation", False))

        elif action_contract is not None:
            is_action = True
            contract_intent = getattr(action_contract, "action_intent", None)
            if contract_intent is not None:
                action_name = getattr(contract_intent, "intent_name", "") or intent_name
                parameters = getattr(contract_intent, "parameters", {}) or {}
            requires_confirmation = bool(getattr(res, "requires_confirmation", False))

        elif isinstance(res, dict) and (
            res.get("type") == "action" or "action" in res or "action_name" in res or "skill" in res
        ):
            is_action = True
            action_name = str(res.get("action") or res.get("action_name") or res.get("skill") or intent_name)
            parameters = res.get("parameters", {}) if isinstance(res.get("parameters"), dict) else {}
            requires_confirmation = bool(res.get("requires_confirmation", False))

        if is_action and action_name:
            resolved_action_id = action_id or metadata.get("action_id") or f"act-{uuid.uuid4().hex[:8]}"
            action_event = ActionProposed(
                action_name=action_name,
                action_id=resolved_action_id,
                parameters=parameters,
                source="orchestrator",
                session_id=session_id,
                metadata={"intent": intent_name, "action_id": resolved_action_id, **metadata},
            )
            await self._event_bus.publish(action_event)

            # Transicionar State Machine a CONFIRMING o EXECUTING según corresponda
            if self._state_machine is not None:
                if requires_confirmation:
                    if self._state_machine.can_transition_to(SessionState.CONFIRMING):
                        self._state_machine.transition_to(SessionState.CONFIRMING)
                else:
                    if self._state_machine.can_transition_to(SessionState.EXECUTING):
                        self._state_machine.transition_to(SessionState.EXECUTING)
            return

        # ── CASO C: Conversación Normal / Respuesta Hablada ───────────────────
        spoken_text = ""
        if hasattr(res, "spoken_text") and res.spoken_text:
            spoken_text = str(res.spoken_text)
        elif hasattr(res, "response_text") and res.response_text:
            spoken_text = str(res.response_text)
        elif isinstance(res, dict):
            spoken_text = str(res.get("spoken_text") or res.get("response_text") or res.get("text") or "")
        elif isinstance(res, str):
            spoken_text = res

        speak_event = SpeakRequested(
            text=spoken_text,
            session_id=session_id,
            metadata={"intent": intent_name, **metadata},
        )
        await self._event_bus.publish(speak_event)

        # Transicionar State Machine a RESPONDING
        if self._state_machine is not None and self._state_machine.can_transition_to(SessionState.RESPONDING):
            self._state_machine.transition_to(SessionState.RESPONDING)
