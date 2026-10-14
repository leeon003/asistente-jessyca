"""Agente Local Unificado de JESSYCA (local_agent.py - Fase 45).

Orquesta de forma transparente y unificada:
User Input (Voice / Text / Multimodal)
  ↓
Intent Analysis
  ↓
Model Routing (ModelRouter)
  ↓
Agent Coordination (AgentCoordinator / CollaborationEngine)
  ↓
Skill Resolution (SkillRouter / SkillRegistry)
  ↓
Planning & Graph (SkillGraphPlanner)
  ↓
Security & Autonomy Governance (SecurityPipeline / RiskEngine / PermissionManager / AutonomyPolicy)
  ↓
Tool Execution
  ↓
Response Synthesis (Text / TTS Voice)

INVARIANTES INMUTABLES:
1. UNIFIED USER EXPERIENCE: El usuario no necesita conocer conceptos internos (Skills, Agents, Models, Tools, Graphs).
2. CONTEXT != AUTHORIZATION != MEMORY: La memoria o contexto no otorgan permisos de seguridad.
3. PREVALENCIA DE PARADA DE EMERGENCIA: EmergencyStopManager detiene inmediatamente cualquier acción.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any, ClassVar

from core.action_intent_contract import ActionIntentContract
from core.audit_logger import AuditLogger, get_audit_logger
from core.cancellation import CancellationToken
from core.collaboration.collaboration_engine import CollaborationEngine
from core.control_plane.models import AgentBudget
from core.dialogue import (
    DialogueActionType,
    NaturalActionDialogueManager,
)
from core.dialogue.action_intent_bridge import bridge_dialogue_to_contract
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.execution.action_execution_bridge import attach_execution_to_contract
from core.experience import (
    ExecutionStatus as ExpExecutionStatus,
)
from core.experience import (
    ExperienceCategory,
    ExperienceLogger,
    InputSource,
    get_experience_logger,
)
from core.experience import (
    VerificationStatus as ExpVerificationStatus,
)
from core.interaction.interaction_models import (
    ConfirmationPrompt,
)
from core.interaction.trusted_interaction_engine import TrustedInteractionEngine
from core.llm.experimental_router import get_experimental_router
from core.llm.model_router import ModelRouter, get_model_router
from core.local_agent.conversation_context import ConversationContextManager
from core.local_agent.conversational_handler import ConversationalDialogueHandler
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    InputModality,
    JessycaRequest,
    JessycaResponse,
    LocalAgentMetrics,
)
from core.local_agent.multimodal_interface import MultimodalProcessor
from core.local_agent.response_synthesizer import (
    ResponseSynthesizer,
    get_response_synthesizer,
)
from core.local_agent.voice_interface import LocalVoiceInterface
from core.logger import get_logger
from core.permission_manager import PermissionManager
from core.risk_engine import RiskEngine
from core.security_architecture import SecurityLevel
from core.jde.adapter import JDEShadowAdapter, LocalAgentExecutionContext, get_jde_shadow_adapter
from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeVerdictType,
    get_jde_runtime_binding,
)
from core.are.runtime import ARERuntime, get_are_runtime
from core.are.models import ARERuntimeMode
from core.system.system_coordinator import SystemCoordinator4, SystemResponse
from skills.skill_manager import SkillManager, get_skill_manager

logger = get_logger("jessyca.local_agent")


class JessycaLocalAgent:
    """Núcleo del Agente Local Unificado de JESSYCA."""

    _instance: ClassVar[JessycaLocalAgent | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        coordinator: SystemCoordinator4 | None = None,
        voice_interface: LocalVoiceInterface | None = None,
        context_manager: ConversationContextManager | None = None,
        model_router: ModelRouter | None = None,
        skill_manager: SkillManager | None = None,
        collaboration_engine: CollaborationEngine | None = None,
        interaction_engine: TrustedInteractionEngine | None = None,
        emergency_stop: EmergencyStopManager | None = None,
        audit_logger: AuditLogger | None = None,
        risk_engine: RiskEngine | None = None,
        permission_manager: PermissionManager | None = None,
        experience_logger: ExperienceLogger | None = None,
        dialogue_manager: NaturalActionDialogueManager | None = None,
        conversational_handler: ConversationalDialogueHandler | None = None,
        jde_shadow_adapter: JDEShadowAdapter | None = None,
        jde_runtime_binding: JDERuntimeBinding | None = None,
        are_runtime: ARERuntime | None = None,
        response_synthesizer: ResponseSynthesizer | None = None,
        long_term_memory: Any | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.emergency_stop_mgr = emergency_stop or get_emergency_stop_manager()
        self.audit_logger = audit_logger or get_audit_logger()
        self.experience_logger = experience_logger or get_experience_logger()
        self.risk_engine = risk_engine or RiskEngine()
        self.permission_manager = permission_manager or PermissionManager()
        self.model_router = model_router or get_model_router()
        self.experimental_router = get_experimental_router()
        self.skill_manager = skill_manager or get_skill_manager()
        self.collaboration_engine = collaboration_engine or CollaborationEngine()
        self.interaction_engine = interaction_engine or TrustedInteractionEngine(emergency_stop=self.emergency_stop_mgr)
        self.context_manager = context_manager or ConversationContextManager()
        self.voice_interface = voice_interface or LocalVoiceInterface(emergency_stop=self.emergency_stop_mgr)
        self.dialogue_manager = dialogue_manager or NaturalActionDialogueManager.get_instance()
        self.conversational_handler = conversational_handler or ConversationalDialogueHandler(model_router=self.model_router)
        self.response_synthesizer = response_synthesizer or get_response_synthesizer()
        self.coordinator = coordinator or SystemCoordinator4(
            collaboration_engine=self.collaboration_engine,
            emergency_stop=self.emergency_stop_mgr,
            audit_logger=self.audit_logger,
        )
        self.jde_shadow_adapter = jde_shadow_adapter or get_jde_shadow_adapter()
        self.jde_runtime_binding = jde_runtime_binding or get_jde_runtime_binding()
        self.are_runtime = are_runtime or get_are_runtime()

        from core.memory.long_term_memory import LongTermMemoryEngine, MemoryRecordType, MemorySensitivity
        self.long_term_memory = long_term_memory or LongTermMemoryEngine()

        self._active_tokens: dict[str, CancellationToken] = {}
        self._latest_metrics: LocalAgentMetrics = LocalAgentMetrics()

    def remember(
        self,
        fact: str,
        category: str = "SEMANTIC_MEMORY",
        source: str = "user_conversation",
    ) -> Any:
        """Almacena un hecho o preferencia de forma persistente y duradera."""
        from core.memory.long_term_memory import MemoryRecordType, MemorySensitivity
        try:
            m_type = getattr(MemoryRecordType, category, MemoryRecordType.SEMANTIC_MEMORY)
            rec = self.long_term_memory.store_record(
                content=fact,
                record_type=m_type,
                source=source,
                sensitivity=MemorySensitivity.INTERNAL,
            )
            return rec
        except Exception as e:
            logger.error(f"[MEMORY] Error guardando registro en memoria persistente: {e}")
            return None

    def recall(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Recupera registros relevantes de memoria persistente según la consulta."""
        try:
            return self.long_term_memory.retrieve_records(query=query, limit=limit)
        except Exception as e:
            logger.error(f"[MEMORY] Error recuperando registros de memoria: {e}")
            return []

    @classmethod
    def get_instance(cls) -> JessycaLocalAgent:
        """Obtiene la instancia singleton del Agente Local."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = JessycaLocalAgent()
            return cls._instance

    # ── MÉTODOS PÚBLICOS DE ENTRADA PRINCIPAL ──

    def interact(
        self,
        request: JessycaRequest | str,
        cancellation_token: CancellationToken | None = None,
        user_confirmation_callback: Callable[[ConfirmationPrompt], bool] | None = None,
        session_id: str | None = None,
    ) -> JessycaResponse:
        """Punto de entrada universal y unificado para cualquier interacción con JESSYCA."""
        if isinstance(request, str):
            req = JessycaRequest(
                user_input=request,
                modality=InputModality.TEXT,
                session_id=session_id or "default",
            )
        else:
            req = request
            if session_id:
                req.session_id = session_id

        return self._execute_unified_pipeline(
            req=req,
            cancellation_token=cancellation_token,
            user_confirmation_callback=user_confirmation_callback,
        )

    def interact_stream(
        self,
        request: JessycaRequest | str,
        cancellation_token: CancellationToken | None = None,
        user_confirmation_callback: Callable[[ConfirmationPrompt], bool] | None = None,
    ) -> Iterator[str]:
        """Punto de entrada universal en streaming respetando el principio Anti-False Success.

        Para consultas conversacionales directas (general_query, saludos, preguntas):
        Emite los tokens en tiempo real directamente según los genera Ollama.

        Para acciones sobre el sistema operativo (e.g. abrir aplicaciones, ejecutar comandos):
        Primero ejecuta la acción y verifica su efecto real en el SO (ExecutionVerifier).
        Solo después de verificar el éxito real, emite la respuesta confirmada.
        """
        if isinstance(request, str):
            req = JessycaRequest(user_input=request, modality=InputModality.TEXT)
        else:
            req = request

        # Ingestión y deduplicación de contexto conversacional externo (OWUI-MEM-02)
        if req.conversation_context:
            self.context_manager.ingest_external_context(
                session_id=req.session_id,
                messages=req.conversation_context,
            )

        user_text = (req.user_input or "").strip()
        intent, extracted_params, is_ambiguous = self._resolve_intent_and_slots(user_text, req.session_id)
        dialogue_decision = self.dialogue_manager.evaluate_dialogue(
            user_input=user_text,
            intent=intent,
            params=extracted_params,
            is_ambiguous=is_ambiguous,
        )

        is_pure_conv = (
            (intent in ("general_query", "conversational", "greeting", "chit_chat")
             or dialogue_decision.action_type == DialogueActionType.CONVERSATIONAL)
            and not is_ambiguous
            and dialogue_decision.action_type != DialogueActionType.CLARIFICATION
        )

        # Si es una acción con efectos secundarios o aclaración/confirmación:
        if not is_pure_conv:
            response = self._execute_unified_pipeline(
                req=req,
                cancellation_token=cancellation_token,
                user_confirmation_callback=user_confirmation_callback,
            )
            resp_text = response.spoken_text or response.response_text or ""
            words = re.split(r"(\s+)", resp_text)
            for w in words:
                if w:
                    yield w
            return

        # Para consultas puramente conversacionales: emitir tokens progresivos
        active_model = self._select_model_for_intent(intent)
        full_response_parts: list[str] = []
        for chunk in self.conversational_handler.generate_response_stream(
            user_input=user_text,
            session_id=req.session_id,
            params=extracted_params,
            context_manager=self.context_manager,
            preferred_model=active_model,
        ):
            full_response_parts.append(chunk)
            yield chunk

        final_text = "".join(full_response_parts)
        if final_text.strip():
            self.context_manager.record_turn(
                session_id=req.session_id,
                user_prompt=user_text,
                assistant_response=final_text,
                intent="general_query",
                modality=req.modality,
                tools_executed=[],
                security_verdict="ALLOW",
            )

    def process_text(
        self,
        text: str,
        session_id: str = "default_session",
        cancellation_token: CancellationToken | None = None,
        user_confirmation_callback: Callable[[ConfirmationPrompt], bool] | None = None,
    ) -> JessycaResponse:
        """Procesa una petición en modalidad texto."""
        req = JessycaRequest(
            session_id=session_id,
            modality=InputModality.TEXT,
            user_input=text,
        )
        return self.interact(
            request=req,
            cancellation_token=cancellation_token,
            user_confirmation_callback=user_confirmation_callback,
        )

    def process_interaction(
        self,
        prompt: str,
        session_id: str = "default_session",
        cancellation_token: CancellationToken | None = None,
        user_confirmation_callback: Callable[[ConfirmationPrompt], bool] | None = None,
    ) -> JessycaResponse:
        """Alias compatible para clientes de distribución y CLI."""
        return self.process_text(
            text=prompt,
            session_id=session_id,
            cancellation_token=cancellation_token,
            user_confirmation_callback=user_confirmation_callback,
        )

    def process_voice(
        self,
        require_wake_word: bool = False,
        session_id: str = "voice_session",
        cancellation_token: CancellationToken | None = None,
        user_confirmation_callback: Callable[[ConfirmationPrompt], bool] | None = None,
    ) -> JessycaResponse:
        """Captura audio desde la interfaz de voz y procesa el turno conversacional completo."""
        token = cancellation_token or CancellationToken()

        # 1. Captura de audio y STT
        voice_req, voice_metrics, voice_err = self.voice_interface.capture_voice_request(
            require_wake_word=require_wake_word,
            cancellation_token=token,
            session_id=session_id,
        )

        if voice_err or voice_req is None:
            # Caso de interrupción, fallo de wake word o parada de emergencia
            is_emergency = self.emergency_stop_mgr.is_stopped()
            state = AgentExecutionState.STOPPED if is_emergency else (
                AgentExecutionState.INTERRUPTED if voice_metrics.interruption_handled else AgentExecutionState.FAILED
            )
            resp = JessycaResponse(
                request_id=f"req-voice-err-{int(time.time())}",
                session_id=session_id,
                success=False,
                status=state,
                response_text=voice_err or "Error al capturar entrada de voz.",
                error=voice_err,
                metrics=voice_metrics,
            )
            return resp

        # 2. Ejecutar a través del pipeline unificado
        response = self._execute_unified_pipeline(
            req=voice_req,
            cancellation_token=token,
            user_confirmation_callback=user_confirmation_callback,
            initial_metrics=voice_metrics,
        )

        # 3. Síntesis de voz (TTS) para la respuesta generada
        if response.success or response.response_text:
            tts_text = response.spoken_text or response.response_text
            tts_ok, tts_latency = self.voice_interface.synthesize_response(
                text=tts_text,
                cancellation_token=token,
            )
            response.metrics.tts_latency_ms = tts_latency
            if response.metrics.first_audio_tts_latency_ms == 0.0:
                response.metrics.first_audio_tts_latency_ms = min(tts_latency, max(1.0, tts_latency * 0.4))
            response.metrics.total_latency_ms += tts_latency

        return response

    def process_multimodal(
        self,
        text: str,
        images: list[bytes] | None = None,
        screen_capture: bytes | None = None,
        file_attachments: list[str] | None = None,
        browser_context: dict[str, Any] | None = None,
        session_id: str = "multimodal_session",
        cancellation_token: CancellationToken | None = None,
        user_confirmation_callback: Callable[[ConfirmationPrompt], bool] | None = None,
    ) -> JessycaResponse:
        """Procesa una petición enriquecida con múltiples modalidades (imágenes, pantalla, archivos)."""
        req = JessycaRequest(
            session_id=session_id,
            modality=InputModality.MULTIMODAL,
            user_input=text,
            images=images or [],
            screen_capture=screen_capture,
            file_attachments=file_attachments or [],
            browser_context=browser_context or {},
        )
        return self.interact(
            request=req,
            cancellation_token=cancellation_token,
            user_confirmation_callback=user_confirmation_callback,
        )

    # ── PIPELINE INTERNO UNIFICADO ──

    def _execute_unified_pipeline(
        self,
        req: JessycaRequest,
        cancellation_token: CancellationToken | None = None,
        user_confirmation_callback: Callable[[ConfirmationPrompt], bool] | None = None,
        initial_metrics: LocalAgentMetrics | None = None,
    ) -> JessycaResponse:
        """Ejecuta el flujo completo de resolución end-to-end."""
        metrics = initial_metrics or LocalAgentMetrics(task_id=req.request_id, correlation_id=req.request_id)
        start_time = time.perf_counter()
        token = cancellation_token or CancellationToken()

        with self._lock:
            self._active_tokens[req.request_id] = token

        try:
            # ── PASO 0: VERIFICACIÓN DE PARADA DE EMERGENCIA Y CANCELACIÓN ──
            if self.emergency_stop_mgr.is_stopped():
                resp = self.response_synthesizer.build_stopped_response(req, metrics, start_time)
                self._log_turn_experience(req, resp, category=ExperienceCategory.ACTION_BLOCKED)
                return resp

            if token.is_cancelled:
                resp = self.response_synthesizer.build_interrupted_response(req, metrics, start_time)
                self._log_turn_experience(req, resp, category=ExperienceCategory.CANCELLED)
                return resp

            # Ingestión y deduplicación de contexto conversacional externo (OWUI-MEM-02)
            if req.conversation_context:
                self.context_manager.ingest_external_context(
                    session_id=req.session_id,
                    messages=req.conversation_context,
                )

            # ── PASO 1: PROCESAMIENTO MULTIMODAL & UNTRUSTED DATA SANITIZATION ──
            is_mm_valid, mm_err, mm_context = MultimodalProcessor.process_request(req)
            if not is_mm_valid:
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                resp = JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=False,
                    status=AgentExecutionState.FAILED,
                    response_text=f"Entrada multimodal inválida: {mm_err}",
                    error=mm_err,
                    metrics=metrics,
                )
                self._log_turn_experience(req, resp, category=ExperienceCategory.ACTION_FAILED)
                return resp

            user_text = req.user_input.strip()

            # ── OBSERVACIÓN / ENRUTAMIENTO DEL MODEL ROUTER (FASE 4 / FASE 5) ──
            router_selected_model: str | None = None
            router_decision: Any = None
            try:
                if hasattr(self, "experimental_router") and self.experimental_router:
                    is_voice = (req.modality == InputModality.VOICE)
                    router_selected_model, router_decision = self.experimental_router.route_execution(
                        user_text=user_text,
                        current_model="gemma4:e4b",
                        is_voice=is_voice,
                        request_id=req.request_id,
                        context={"session_id": req.session_id, "modality": req.modality.value},
                    )
            except Exception as e:
                logger.warning(f"[ROUTER PIPELINE] Error no crítico en enrutamiento del router: {e}")

            # ── PASO 1.5: QUALITY GATE Y COMPLETITUD DE TRANSCRIPCIÓN ──
            from core.local_agent.quality_analyzer import (
                IntentCompleteness,
                IntentCompletenessChecker,
                TranscriptQualityAnalyzer,
            )

            # Analizar calidad de transcripción y señales de incertidumbre
            stt_conf = float(req.metadata.get("stt_confidence", 1.0)) if req.metadata and "stt_confidence" in req.metadata else 1.0
            q_analyzer = TranscriptQualityAnalyzer()
            q_res = q_analyzer.analyze(user_text, confidence=stt_conf, metadata=req.metadata)
            if not q_res.is_acceptable:
                clarification_msg = q_res.suggested_prompt or "No te entendí bien. ¿Puedes repetirlo?"
                if q_res.proposed_interpretation:
                    self.context_manager.set_pending_clarification(
                        session_id=req.session_id,
                        question=clarification_msg,
                        expected_slot="confirmation",
                        original_intent="general_query",
                        partial_parameters={
                            "proposed_interpretation": q_res.proposed_interpretation,
                            "original_transcript": user_text,
                        },
                    )
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                resp = JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=False,
                    status=AgentExecutionState.AWAITING_CLARIFICATION,
                    response_text=clarification_msg,
                    spoken_text=clarification_msg,
                    intent="clarification_request" if q_res.proposed_interpretation else "unknown",
                    requires_clarification=True,
                    clarification_question=clarification_msg,
                    original_transcript=user_text,
                    proposed_interpretation=q_res.proposed_interpretation,
                    metrics=metrics,
                )
                self._log_turn_experience(req, resp, category=ExperienceCategory.LOW_STT_CONFIDENCE)
                return resp

            # Analizar completitud de la orden solo si no hay contexto o pregunta pendiente en la sesión
            session_obj = self.context_manager.get_session(req.session_id)
            has_pending_context = session_obj is not None and (bool(session_obj.pending_intent) or bool(session_obj.pending_confirmation))

            if not has_pending_context:
                c_checker = IntentCompletenessChecker()
                c_res = c_checker.check_completeness(q_res.normalized_text)
                if c_res.completeness == IntentCompleteness.INCOMPLETE:
                    clarification_msg = c_res.clarification_question or "¿Puedes completar tu solicitud?"
                    self.context_manager.set_pending_clarification(
                        session_id=req.session_id,
                        question=clarification_msg,
                        expected_slot=c_res.missing_slot or "target",
                        original_intent=c_res.intent_category,
                    )
                    metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                    resp = JessycaResponse(
                        request_id=req.request_id,
                        session_id=req.session_id,
                        success=False,
                        status=AgentExecutionState.AWAITING_CLARIFICATION,
                        response_text=clarification_msg,
                        spoken_text=clarification_msg,
                        intent=c_res.intent_category,
                        requires_clarification=True,
                        clarification_question=clarification_msg,
                        metrics=metrics,
                    )
                    self._log_turn_experience(req, resp, category=ExperienceCategory.CLARIFICATION_REQUESTED, target_type="slot", target_value=c_res.missing_slot)
                    return resp

            # Usar texto normalizado limpio
            user_text = q_res.normalized_text

            # ── PASO 1.8: DETECCIÓN DE CIERRE DE CONVERSACIÓN ──
            if user_text.lower() in ("adiós", "adios", "salir", "exit", "quit", "cerrar conversación", "cerrar sesion", "cerrar sesión", "hasta luego", "bye", "terminar"):
                self.context_manager.close_session(req.session_id)
                resp = self.response_synthesizer.build_closing_response(req, metrics, start_time)
                self._log_turn_experience(req, resp, category=ExperienceCategory.GENERAL)
                return resp

            # ── PASO 2: ANÁLISIS DE INTENCIÓN Y RESOLUCIÓN DE CONTEXTO ──
            t_intent_0 = time.perf_counter()
            intent, extracted_params, is_ambiguous = self._resolve_intent_and_slots(user_text, req.session_id)
            if req.metadata:
                for m_k, m_v in req.metadata.items():
                    if m_k not in extracted_params or not extracted_params[m_k]:
                        extracted_params[m_k] = m_v
            metrics.intent_latency_ms = (time.perf_counter() - t_intent_0) * 1000

            # Manejo de cancelación conversacional o interrupción ("Olvídalo", "Déjame hablar", "Pausa")
            if intent in ("cancel_task", "interrupt_assistant"):
                default_msg = "Te escucho, dime." if intent == "interrupt_assistant" else "Entendido, operación cancelada."
                cancel_msg = extracted_params.get("immediate_response") or default_msg
                resp = self.response_synthesizer.build_cancelled_response(
                    req, metrics, start_time, reason=cancel_msg, intent=intent
                )
                self._log_turn_experience(req, resp, category=ExperienceCategory.CANCELLED)
                return resp

            # 2.1 EVALUACIÓN DE DIÁLOGO Y CONCIENCIA DE CAPACIDADES (FASE 52.1)
            dialogue_decision = self.dialogue_manager.evaluate_dialogue(
                user_input=user_text,
                intent=intent,
                params=extracted_params,
                is_ambiguous=is_ambiguous,
            )

            # 2.1.1 Generación observacional de ActionIntentContract (Fase 64.1.4)
            action_contract: ActionIntentContract | None = None
            is_conversational_turn = (
                intent in ("general_query", "conversational", "greeting", "chit_chat", "close_conversation")
                or dialogue_decision.action_type in (DialogueActionType.CONVERSATIONAL, DialogueActionType.EXPLAIN_CAPABILITY)
            )
            if not is_conversational_turn:
                action_contract = bridge_dialogue_to_contract(
                    decision=dialogue_decision,
                    user_input=user_text,
                    intent=intent,
                    params=extracted_params,
                    context={
                        "request_id": req.request_id,
                        "session_id": req.session_id,
                        "modality": req.modality.value,
                    },
                    is_ambiguous=is_ambiguous,
                    request_id=req.request_id,
                    session_id=req.session_id,
                    input_modality=req.modality.value,
                )
                logger.debug(
                    f"[LOCAL_AGENT_CONTRACT] Snapshot generado: intent={action_contract.action_intent.intent_name} "
                    f"can_execute={action_contract.execution_gate.can_execute} "
                    f"needs_clarif={action_contract.execution_gate.needs_clarification}"
                )

            # Caso: Capacidad No Soportada
            if dialogue_decision.action_type == DialogueActionType.UNSUPPORTED_CAPABILITY:
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                resp = JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=True,
                    status=AgentExecutionState.COMPLETED,
                    response_text=dialogue_decision.response_text,
                    spoken_text=dialogue_decision.response_text,
                    intent=intent,
                    metrics=metrics,
                    action_intent_contract=action_contract,
                )
                self._log_turn_experience(req, resp, category=ExperienceCategory.GENERAL)
                return resp

            # Caso: Capacidad Parcialmente Soportada
            if dialogue_decision.action_type == DialogueActionType.PARTIAL_CAPABILITY:
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                resp = JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=True,
                    status=AgentExecutionState.COMPLETED,
                    response_text=dialogue_decision.response_text,
                    spoken_text=dialogue_decision.response_text,
                    intent=intent,
                    metrics=metrics,
                    action_intent_contract=action_contract,
                )
                self._log_turn_experience(req, resp, category=ExperienceCategory.GENERAL)
                return resp

            # Caso: Explicación de Capacidades
            if dialogue_decision.action_type == DialogueActionType.EXPLAIN_CAPABILITY:
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                resp = JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=True,
                    status=AgentExecutionState.COMPLETED,
                    response_text=dialogue_decision.response_text,
                    spoken_text=dialogue_decision.response_text,
                    intent="explain_capability",
                    metrics=metrics,
                )
                self._log_turn_experience(req, resp, category=ExperienceCategory.GENERAL)
                return resp

            # Manejo de respuesta inmediata de diálogo contextual (ej. "¿Qué números quieres sumar?", "¿Para qué día?", "¿Qué quieres incluir?", selección de documento)
            if (intent in ("math_sum", "write_list", "summarize_document") or is_ambiguous) and extracted_params.get("immediate_response") and is_ambiguous:
                clarification_msg = extracted_params["immediate_response"]
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                resp = JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=True,
                    status=AgentExecutionState.AWAITING_CLARIFICATION,
                    response_text=clarification_msg,
                    spoken_text=clarification_msg,
                    intent=intent,
                    requires_clarification=True,
                    clarification_question=clarification_msg,
                    metrics=metrics,
                    action_intent_contract=action_contract,
                )
                self._log_turn_experience(req, resp, category=ExperienceCategory.CLARIFICATION_REQUESTED)
                return resp

            # Manejo de diálogo contextual completado (ej. resultado matemático, alarma configurada, respuesta afirmativa, lista completada, consulta general, corrección, búsqueda informada, error de validación)
            if extracted_params.get("immediate_response") and not is_ambiguous:
                resp_msg = extracted_params["immediate_response"]
                is_err = bool(extracted_params.get("error"))
                is_auth_denied = (extracted_params.get("error") in ("access_denied", "critical_path")) or ("acceso denegado" in str(resp_msg).lower()) or ("fuera del alcance" in str(resp_msg).lower())
                sec_verdict = "DENY" if is_auth_denied else "ALLOW"
                out_info = {"security_layers": {"pre_gate": "ALLOW", "resource_enforcement": "DENY"}} if is_auth_denied else None
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                resp = JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=not is_err,
                    status=AgentExecutionState.FAILED if is_err else AgentExecutionState.COMPLETED,
                    response_text=resp_msg,
                    spoken_text=resp_msg,
                    intent=intent,
                    error=resp_msg if is_err else None,
                    tools_executed=[],
                    security_verdict=sec_verdict,
                    output_data=out_info,
                    metrics=metrics,
                    action_intent_contract=action_contract,
                )
                cat = ExperienceCategory.ACTION_FAILED if is_err else (ExperienceCategory.USER_CORRECTION if intent == "user_correction" else ExperienceCategory.ACTION_SUCCESS)
                self._log_turn_experience(req, resp, category=cat, is_correction=(intent == "user_correction"))
                return resp

            # Manejo de Aclaración si la intención es ambigua o faltan parámetros críticos
            if is_ambiguous or dialogue_decision.action_type == DialogueActionType.CLARIFICATION:
                clarification_msg = dialogue_decision.clarification_question or extracted_params.get("immediate_response") or "¿Podrías darme más detalles sobre lo que deseas hacer?"
                self.context_manager.set_pending_clarification(
                    session_id=req.session_id,
                    question=clarification_msg,
                    expected_slot=dialogue_decision.expected_slot or "target",
                    original_intent=intent,
                )
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                resp = JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=False,
                    status=AgentExecutionState.AWAITING_CLARIFICATION,
                    response_text=clarification_msg,
                    spoken_text=clarification_msg,
                    intent=intent,
                    requires_clarification=True,
                    clarification_question=clarification_msg,
                    metrics=metrics,
                    action_intent_contract=action_contract,
                )
                self._log_turn_experience(req, resp, category=ExperienceCategory.AMBIGUOUS_INTENT)
                return resp

            # ── PASO 2.2: CONSULTAS Y DIÁLOGO CONVERSACIONAL PURO (CONVERSATIONAL_REQUEST) ──
            is_complex_are = (
                hasattr(self, "are_runtime")
                and self.are_runtime
                and self.are_runtime.current_mode != ARERuntimeMode.DISABLED
                and self.are_runtime.is_complex_task(user_text, intent, extracted_params)
            )
            if not is_complex_are and (intent == "general_query" or dialogue_decision.action_type == DialogueActionType.CONVERSATIONAL):
                t_conv_0 = time.perf_counter()
                active_routed_model = (
                    router_selected_model
                    if (hasattr(self, "experimental_router") and self.experimental_router and self.experimental_router.is_enabled() and router_selected_model)
                    else self._select_model_for_intent(intent)
                )
                conv_text = self.conversational_handler.generate_response(
                    user_input=user_text,
                    session_id=req.session_id,
                    params=extracted_params,
                    context_manager=self.context_manager,
                    preferred_model=active_routed_model,
                )
                metrics.model_inference_latency_ms = (time.perf_counter() - t_conv_0) * 1000
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000

                self.context_manager.record_turn(
                    session_id=req.session_id,
                    user_prompt=user_text,
                    assistant_response=conv_text,
                    intent="general_query",
                    modality=req.modality,
                    tools_executed=[],
                    security_verdict="ALLOW",
                )
                self._latest_metrics = metrics
                is_degraded = bool(getattr(self.conversational_handler, "_last_was_degraded", False))
                deg_reason = getattr(self.conversational_handler, "_last_degradation_reason", None)
                resp = JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=not is_degraded,
                    status=AgentExecutionState.FAILED if is_degraded else AgentExecutionState.COMPLETED,
                    response_text=conv_text,
                    spoken_text=conv_text,
                    intent="general_query",
                    selected_model="none" if is_degraded else active_routed_model,
                    selected_agent="general_assistant_agent",
                    selected_skill="core.assistant@1.0.0",
                    selected_graph="conversational_graph",
                    tools_executed=[],
                    security_level=SecurityLevel.SAFE,
                    output_data={"conversational_response": conv_text, "degraded": is_degraded},
                    error=deg_reason if is_degraded else None,
                    metrics=metrics,
                )
                self._log_turn_experience(req, resp, category=ExperienceCategory.GENERAL)
                return resp

            # ── PASO 3: ENRUTAMIENTO DE MODELO Y AGENTE ──
            t_model_0 = time.perf_counter()
            # Selección automática de modelo según la complejidad del intent
            active_routed_model = (
                router_selected_model
                if (hasattr(self, "experimental_router") and self.experimental_router and self.experimental_router.is_enabled() and router_selected_model)
                else self._select_model_for_intent(intent)
            )
            selected_model = active_routed_model
            metrics.model_inference_latency_ms = (time.perf_counter() - t_model_0) * 1000

            t_agent_0 = time.perf_counter()
            selected_agent = self._select_agent_for_intent(intent)
            selected_skill = self._select_skill_for_intent(intent)
            metrics.agent_routing_latency_ms = (time.perf_counter() - t_agent_0) * 1000

            # ── PASO 4: PLANIFICACIÓN AUTOMÁTICA Y SKILL GRAPH / ARE COMPLEX TASK ──
            t_plan_0 = time.perf_counter()
            selected_graph = f"graph_{intent}"

            # Evaluar si la solicitud califica como tarea compleja para ARE en modo CONTROLLED/SHADOW
            if (
                hasattr(self, "are_runtime")
                and self.are_runtime
                and self.are_runtime.current_mode != ARERuntimeMode.DISABLED
                and self.are_runtime.is_complex_task(user_text, intent, extracted_params)
            ):
                logger.info(f"[LOCAL_AGENT_ARE] Solicitud '{user_text[:50]}' califica como TAREA COMPLEJA. Delegando a ARE Runtime.")
                # Determinar si ya viene con confirmación previa del usuario
                user_is_confirmed = bool(
                    extracted_params.get("is_confirmed") is True
                    or extracted_params.get("confirmed") is True
                )
                are_resp = self.are_runtime.execute_complex_task(
                    agent=self,
                    req=req,
                    goal=user_text,
                    context=extracted_params,
                    user_confirmed=user_is_confirmed,
                    cancellation_token=cancellation_token,
                )
                are_resp.intent = intent
                are_resp.selected_model = selected_model
                are_resp.selected_agent = selected_agent
                are_resp.selected_skill = selected_skill
                are_resp.selected_graph = selected_graph
                if are_resp.status == AgentExecutionState.COMPLETED and intent == "multistep_research" and "multistep.orchestrate" not in are_resp.tools_executed:
                    are_resp.tools_executed.append("multistep.orchestrate")
                metrics.planning_latency_ms = (time.perf_counter() - t_plan_0) * 1000
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                are_resp.metrics = metrics
                self._latest_metrics = metrics
                return are_resp

            metrics.planning_latency_ms = (time.perf_counter() - t_plan_0) * 1000

            # ── PASO 5: GOBERNANZA CANÓNICA UNIFICADA (RiskEngine -> PermissionManager -> JDE) ──
            t_auth_0 = time.perf_counter()
            proposed_tool = self._map_intent_to_tool(intent)

            # 5.1 RiskEngine calcula el riesgo formal de la acción propuesta
            sec_level = self._evaluate_action_security(proposed_tool, extracted_params)

            # 5.2 PermissionManager aplica restricciones de políticas y permisos
            if hasattr(self, "permission_manager") and self.permission_manager and hasattr(self.permission_manager, "is_action_allowed"):
                if not self.permission_manager.is_action_allowed(proposed_tool, intent, extracted_params):
                    deny_msg = f"Acción '{intent}' sobre '{proposed_tool}' denegada por política de permisos."
                    metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                    resp = JessycaResponse(
                        request_id=req.request_id,
                        session_id=req.session_id,
                        success=False,
                        status=AgentExecutionState.FAILED,
                        response_text=deny_msg,
                        spoken_text=deny_msg,
                        intent=intent,
                        selected_model=selected_model,
                        selected_agent=selected_agent,
                        selected_skill=selected_skill,
                        selected_graph=selected_graph,
                        security_verdict="DENY",
                        security_level=sec_level,
                        error=deny_msg,
                        metrics=metrics,
                    )
                    self._log_turn_experience(req, resp, category=ExperienceCategory.ACTION_BLOCKED, tool_name=proposed_tool)
                    self._observe_shadow_turn(
                        req=req,
                        intent=intent,
                        tool=proposed_tool,
                        action=intent,
                        params=extracted_params,
                        exec_success=False,
                        response_text=deny_msg,
                        is_verified=False,
                        sec_level=sec_level,
                    )
                    return resp

            # 5.3 Callback de confirmación humana directa si está disponible
            user_approved = False
            if user_confirmation_callback is not None and (
                sec_level in (SecurityLevel.MEDIUM, SecurityLevel.HIGH, SecurityLevel.CRITICAL)
                or "delete" in proposed_tool
                or "kill" in proposed_tool
            ):
                confirm_prompt = ConfirmationPrompt(
                    task_id=req.request_id,
                    action_name=proposed_tool,
                    relevant_parameters=extracted_params,
                    risk_level=sec_level,
                    objective=f"Confirmación requerida para ejecutar acción sensible '{proposed_tool}'.",
                )
                try:
                    user_approved = bool(user_confirmation_callback(confirm_prompt))
                except Exception as ex:
                    logger.error(f"Error en callback de confirmación: {ex}")
                    user_approved = False

            # Comprobar confirmación estrictamente vinculada a sesión, acción y parámetros
            from core.jde.confirmation import get_confirmation_manager
            has_bound_conf = get_confirmation_manager().verify_and_consume(
                session_id=req.session_id,
                action=intent,
                parameters=extracted_params,
                user_id=getattr(req, "user_id", "default_user"),
            )
            is_confirmed = bool(user_approved or has_bound_conf)

            # Invariante: RiskEngine no puede ser saltado por JDE ALLOW no confirmado
            requires_risk_review = bool(
                (
                    sec_level in (SecurityLevel.MEDIUM, SecurityLevel.HIGH, SecurityLevel.CRITICAL)
                    or "delete" in proposed_tool
                    or "kill" in proposed_tool
                    or "grant_scope" in proposed_tool
                )
                and not is_confirmed
            )
            if requires_risk_review:
                review_msg = f"Detecté una acción sensible: '{proposed_tool}'. ¿Confirmas su ejecución?"
                if intent == "grant_folder_access":
                    f_name = extracted_params.get("ruta_carpeta") or extracted_params.get("ruta") or ""
                    review_msg = f"Detecté una solicitud de autorización de acceso para la carpeta '{f_name}'. ¿Confirmas conceder este permiso?"
                if action_contract is not None:
                    action_contract = bridge_dialogue_to_contract(
                        decision=dialogue_decision,
                        user_input=user_text,
                        intent=intent,
                        params=extracted_params,
                        context={
                            "request_id": req.request_id,
                            "session_id": req.session_id,
                            "modality": req.modality.value,
                            "requires_confirmation": True,
                            "risk_level": sec_level.value,
                            "confirmation_prompt": review_msg,
                        },
                        is_ambiguous=is_ambiguous,
                        request_id=req.request_id,
                        session_id=req.session_id,
                        input_modality=req.modality.value,
                        risk_level=sec_level.value,
                    )
                session = self.context_manager.get_or_create_session(req.session_id)
                session.set_pending_confirmation(
                    intent=intent,
                    tool=proposed_tool,
                    parameters=extracted_params,
                    prompt=review_msg,
                    security_level=sec_level.value if hasattr(sec_level, "value") else str(sec_level),
                )
                from core.jde.confirmation import get_confirmation_manager
                get_confirmation_manager().register_pending_confirmation(
                    session_id=req.session_id,
                    action=intent,
                    tool=proposed_tool,
                    parameters=extracted_params,
                    user_id=getattr(req, "user_id", "default_user"),
                )
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                resp = JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=True,
                    status=AgentExecutionState.AWAITING_CONFIRMATION,
                    response_text=review_msg,
                    spoken_text=review_msg,
                    intent=intent,
                    selected_model=selected_model,
                    selected_agent=selected_agent,
                    selected_skill=selected_skill,
                    selected_graph=selected_graph,
                    security_level=sec_level,
                    requires_confirmation=True,
                    metrics=metrics,
                    action_intent_contract=action_contract,
                )
                self._log_turn_experience(req, resp, category=ExperienceCategory.ACTION_BLOCKED, tool_name=proposed_tool)
                self._observe_shadow_turn(
                    req=req,
                    intent=intent,
                    tool=proposed_tool,
                    action=intent,
                    params=extracted_params,
                    exec_success=False,
                    response_text=review_msg,
                    is_verified=False,
                    sec_level=sec_level,
                )
                return resp

            # 5.4 JDE Runtime Binding coordina el veredicto y el estado
            if hasattr(self, "jde_runtime_binding") and self.jde_runtime_binding:
                jde_verdict = self.jde_runtime_binding.evaluate(
                    intent=intent,
                    action=intent,
                    tool=proposed_tool or "system.coordinator",
                    parameters=extracted_params,
                    user_confirmed=is_confirmed,
                    session_id=req.session_id,
                    request_id=req.request_id,
                    risk_level=sec_level.value if hasattr(sec_level, "value") else str(sec_level),
                    user_id=getattr(req, "user_id", "default_user"),
                )

                if jde_verdict.verdict == JDERuntimeVerdictType.DENY:
                    deny_msg = f"Acción denegada por gobernanza JDE: {jde_verdict.reason}"
                    metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                    resp = JessycaResponse(
                        request_id=req.request_id,
                        session_id=req.session_id,
                        success=False,
                        status=AgentExecutionState.FAILED,
                        response_text=deny_msg,
                        spoken_text=deny_msg,
                        intent=intent,
                        selected_model=selected_model,
                        selected_agent=selected_agent,
                        selected_skill=selected_skill,
                        selected_graph=selected_graph,
                        security_verdict="DENY",
                        security_level=sec_level,
                        error=jde_verdict.reason,
                        metrics=metrics,
                    )
                    self._log_turn_experience(req, resp, category=ExperienceCategory.ACTION_BLOCKED, tool_name=proposed_tool)
                    self._observe_shadow_turn(
                        req=req,
                        intent=intent,
                        tool=proposed_tool,
                        action=intent,
                        params=extracted_params,
                        exec_success=False,
                        response_text=deny_msg,
                        is_verified=False,
                        sec_level=sec_level,
                    )
                    return resp

                if jde_verdict.verdict == JDERuntimeVerdictType.REQUIRE_REVIEW:
                    review_reason = getattr(jde_verdict, "reason", "Requiere confirmación explícita del usuario.") or "Requiere confirmación explícita del usuario."
                    review_msg = f"JDE requiere confirmación para '{proposed_tool}': {review_reason}"
                    if action_contract is not None:
                        action_contract = bridge_dialogue_to_contract(
                            decision=dialogue_decision,
                            user_input=user_text,
                            intent=intent,
                            params=extracted_params,
                            context={
                                "request_id": req.request_id,
                                "session_id": req.session_id,
                                "modality": req.modality.value,
                                "requires_confirmation": True,
                                "risk_level": sec_level.value,
                                "confirmation_prompt": review_msg,
                            },
                            is_ambiguous=is_ambiguous,
                            request_id=req.request_id,
                            session_id=req.session_id,
                            input_modality=req.modality.value,
                            risk_level=sec_level.value,
                        )
                    session = self.context_manager.get_or_create_session(req.session_id)
                    session.set_pending_confirmation(
                        intent=intent,
                        tool=proposed_tool,
                        parameters=extracted_params,
                        prompt=review_msg,
                        security_level=sec_level.value if hasattr(sec_level, "value") else str(sec_level),
                    )
                    metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                    resp = JessycaResponse(
                        request_id=req.request_id,
                        session_id=req.session_id,
                        success=True,
                        status=AgentExecutionState.AWAITING_CONFIRMATION,
                        response_text=review_msg,
                        spoken_text=review_msg,
                        intent=intent,
                        selected_model=selected_model,
                        selected_agent=selected_agent,
                        selected_skill=selected_skill,
                        selected_graph=selected_graph,
                        security_level=sec_level,
                        requires_confirmation=True,
                        metrics=metrics,
                        action_intent_contract=action_contract,
                    )
                    self._log_turn_experience(req, resp, category=ExperienceCategory.ACTION_BLOCKED, tool_name=proposed_tool)
                    self._observe_shadow_turn(
                        req=req,
                        intent=intent,
                        tool=proposed_tool,
                        action=intent,
                        params=extracted_params,
                        exec_success=False,
                        response_text=review_msg,
                        is_verified=False,
                        sec_level=sec_level,
                    )
                    return resp

            metrics.authorization_latency_ms = (time.perf_counter() - t_auth_0) * 1000

            # ── PASO 6: EJECUCIÓN SEGURA Y VERIFICACIÓN POST-EJECUCIÓN REAL ──
            # Verificación cooperativa de cancelación y deadline monotónico previo a efectos
            if token.is_cancelled:
                metrics.interruption_handled = True
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                resp = JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=False,
                    status=AgentExecutionState.INTERRUPTED,
                    response_text="Operación cancelada cooperativamente antes de iniciar efectos en el sistema.",
                    error="Operation cancelled before effect",
                    metrics=metrics,
                )
                self._log_turn_experience(req, resp, category=ExperienceCategory.CANCELLED)
                return resp

            if getattr(req, "monotonic_deadline", None) and time.monotonic() > req.monotonic_deadline:
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                resp = JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=False,
                    status=AgentExecutionState.FAILED,
                    response_text="Deadline monotónico de ejecución alcanzado antes de iniciar efectos en el sistema.",
                    error="Monotonic execution deadline exceeded before effect",
                    metrics=metrics,
                )
                return resp

            # Notificar inicio de efectos secundarios si se provee operation_record en metadata
            op_rec = req.metadata.get("operation_record") if isinstance(req.metadata, dict) else None
            if op_rec is not None and hasattr(op_rec, "effect_started"):
                op_rec.effect_started = True

            t_exec_0 = time.perf_counter()
            from core.execution.execution_verifier import (
                ExecutionEvidence,
                ExecutionResult,
                ExecutionStatus,
            )

            execution_result: ExecutionResult | None = None
            exec_success = False


            # 6.0 Operación Matemática Directa
            if intent == "math_calculation":
                exec_success = True
                calc_res = extracted_params.get("result", "0")
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=True,
                    status="COMPLETED",
                    output={"result": calc_res},
                )

            # 6.0.1 Consulta General Conversacional
            elif intent == "general_query":
                exec_success = True
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=True,
                    status="COMPLETED",
                    output={"query": extracted_params.get("query", user_text)},
                )

            # 6.1 Ejecución directa verificada de aplicaciones de Windows y Explorador
            elif intent in ("open_application", "close_application", "type_text", "open_folder"):
                if intent in ("open_application", "open_folder"):
                    accion_app = "abrir"
                elif intent == "close_application":
                    accion_app = "cerrar"
                else:
                    accion_app = "escribir"

                app_name = "explorer" if intent == "open_folder" else extracted_params.get("app_name", "notepad")

                from core.execution.idempotency_guard import (
                    ExecutionFingerprint,
                    get_idempotency_guard,
                )

                idempotency_guard = get_idempotency_guard()
                fingerprint = ExecutionFingerprint(
                    session_id=req.session_id,
                    request_id=req.request_id,
                    intent=intent,
                    skill="windows.apps",
                    action=accion_app,
                    target=str(extracted_params.get("ruta_carpeta") or app_name),
                )

                is_acquired, exec_record = idempotency_guard.acquire_execution(fingerprint)
                if not is_acquired:
                    logger.warning(
                        f"[IDEMPOTENCY DUPLICATE BLOCKED] Reutilizando resultado previo para request_id={req.request_id} "
                        f"execution_id={exec_record.execution_id} intent={intent} target={app_name}"
                    )
                    exec_success = (exec_record.status == "SUCCEEDED")
                    msg_cached = exec_record.result_message or "Ejecución duplicada prevenida por idempotencia."
                    execution_result = ExecutionResult(
                        status=ExecutionStatus.SUCCEEDED if exec_success else ExecutionStatus.FAILED,
                        action=intent,
                        target=app_name,
                        message=msg_cached,
                    )
                    sys_resp = SystemResponse(
                        task_id=req.request_id,
                        correlation_id=req.request_id,
                        success=exec_success,
                        status=exec_record.status,
                        output=exec_record.details.get("output", {}),
                        error=None if exec_success else msg_cached,
                    )
                else:
                    skill_params: dict[str, Any] = {
                        "accion": accion_app,
                        "nombre_app": app_name,
                        "action_id": req.request_id,
                        "request_id": req.request_id,
                        "execution_id": exec_record.execution_id,
                    }
                    if intent == "open_folder" or extracted_params.get("ruta_carpeta"):
                        skill_params["ruta_carpeta"] = extracted_params.get("ruta_carpeta")
                    if intent == "open_application" and extracted_params.get("text_to_write"):
                        skill_params["texto"] = extracted_params["text_to_write"]
                    elif intent == "type_text":
                        skill_params["texto"] = extracted_params.get("text") or extracted_params.get("text_to_write") or ""

                    skill_res = self.skill_manager.execute_skill(
                        "windows.apps",
                        parameters=skill_params,
                    )

                    raw_evidence = skill_res.output.get("evidence") if isinstance(skill_res.output, dict) else None
                    evidence_obj = None
                    if raw_evidence:
                        evidence_obj = ExecutionEvidence(
                            verification_type=raw_evidence.get("verification_type", "text_typed" if intent == "type_text" else "process"),
                            target=raw_evidence.get("target", app_name),
                            is_verified=bool(raw_evidence.get("is_verified", False)),
                            details=raw_evidence.get("details", {}),
                        )

                    is_skill_ok = bool(skill_res.success and isinstance(skill_res.output, dict) and skill_res.output.get("exito"))
                    is_verif_ok = bool(evidence_obj and evidence_obj.is_verified)
                    reused_instance = bool(isinstance(skill_res.output, dict) and skill_res.output.get("reused_instance", False))
                    execution_count = int(skill_res.output.get("execution_count", 1 if is_skill_ok and not reused_instance else 0)) if isinstance(skill_res.output, dict) else (1 if is_skill_ok else 0)

                    idempotency_guard.record_execution_invoked(
                        execution_id=exec_record.execution_id,
                        count=execution_count,
                        is_reused=reused_instance,
                    )

                    if is_skill_ok and is_verif_ok:
                        exec_status = ExecutionStatus.SUCCEEDED
                        exec_success = True
                    elif skill_res.output and isinstance(skill_res.output, dict) and skill_res.output.get("error_code") == "VERIFICATION_FAILED":
                        exec_status = ExecutionStatus.VERIFICATION_FAILED
                        exec_success = False
                    elif not skill_res.success or (isinstance(skill_res.output, dict) and not skill_res.output.get("exito")):
                        exec_status = ExecutionStatus.FAILED
                        exec_success = False
                    else:
                        exec_status = ExecutionStatus.VERIFICATION_FAILED
                        exec_success = False

                    msg_out = skill_res.output.get("mensaje") if isinstance(skill_res.output, dict) else skill_res.error

                    idempotency_guard.record_verification_completed(
                        execution_id=exec_record.execution_id,
                        status=exec_status.value.upper(),
                        result_message=msg_out,
                        details={"output": skill_res.output if isinstance(skill_res.output, dict) else {}},
                    )

                    execution_result = ExecutionResult(
                        status=exec_status,
                        action=intent,
                        target=app_name,
                        message=msg_out,
                        evidence=evidence_obj,
                        output=skill_res.output,
                    )

                    sys_resp = SystemResponse(
                        task_id=req.request_id,
                        correlation_id=req.request_id,
                        success=exec_success,
                        status=exec_status.value,
                        output=skill_res.output,
                        error=None if exec_success else (execution_result.message or "Fallo en ejecución/verificación"),
                    )

            # 6.2 Ejecución directa verificada de Smart Media Playback (windows.media)
            elif intent == "play_random_video":
                from core.execution.idempotency_guard import (
                    ExecutionFingerprint,
                    get_idempotency_guard,
                )

                idempotency_guard = get_idempotency_guard()
                fingerprint = ExecutionFingerprint(
                    session_id=req.session_id,
                    request_id=req.request_id,
                    intent="play_random_video",
                    skill="windows.media",
                    action="play_random_video",
                    target="dance_video",
                )

                is_acquired, exec_record = idempotency_guard.acquire_execution(fingerprint)
                if not is_acquired:
                    logger.warning(
                        f"[IDEMPOTENCY DUPLICATE BLOCKED] Reutilizando reproducción previa para request_id={req.request_id} "
                        f"execution_id={exec_record.execution_id}"
                    )
                    exec_success = (exec_record.status == "SUCCEEDED")
                    msg_cached = exec_record.result_message or "Reproducción duplicada prevenida por idempotencia."
                    execution_result = ExecutionResult(
                        status=ExecutionStatus.SUCCEEDED if exec_success else ExecutionStatus.FAILED,
                        action=intent,
                        target="dance_video",
                        message=msg_cached,
                    )
                    sys_resp = SystemResponse(
                        task_id=req.request_id,
                        correlation_id=req.request_id,
                        success=exec_success,
                        status=exec_record.status,
                        output=exec_record.details.get("output", {}),
                        error=None if exec_success else msg_cached,
                    )
                else:
                    skill_res = self.skill_manager.execute_skill(
                        "windows.media",
                        parameters={"accion": "play_random_video", "request_id": req.request_id, "execution_id": exec_record.execution_id},
                    )

                    raw_evidence = skill_res.output.get("evidence") if isinstance(skill_res.output, dict) else None
                    evidence_obj = None
                    if raw_evidence:
                        evidence_obj = ExecutionEvidence(
                            verification_type=raw_evidence.get("verification_type", "play_media"),
                            target=raw_evidence.get("target", "dance_video"),
                            is_verified=bool(raw_evidence.get("is_verified", False)),
                            details=raw_evidence.get("details", {}),
                        )

                    is_skill_ok = bool(skill_res.success and isinstance(skill_res.output, dict) and skill_res.output.get("exito"))
                    execution_count = int(skill_res.output.get("execution_count", 1 if is_skill_ok else 0)) if isinstance(skill_res.output, dict) else (1 if is_skill_ok else 0)

                    idempotency_guard.record_execution_invoked(
                        execution_id=exec_record.execution_id,
                        count=execution_count,
                        is_reused=False,
                    )

                    if is_skill_ok:
                        exec_status = ExecutionStatus.SUCCEEDED
                        exec_success = True
                    else:
                        exec_status = ExecutionStatus.FAILED
                        exec_success = False

                    msg_out = skill_res.output.get("mensaje") if isinstance(skill_res.output, dict) else skill_res.error

                    idempotency_guard.record_verification_completed(
                        execution_id=exec_record.execution_id,
                        status=exec_status.value.upper(),
                        result_message=msg_out,
                        details={"output": skill_res.output if isinstance(skill_res.output, dict) else {}},
                    )

                    execution_result = ExecutionResult(
                        status=exec_status,
                        action="play_random_video",
                        target="dance_video",
                        message=msg_out,
                        evidence=evidence_obj,
                        output=skill_res.output,
                        error_code=skill_res.output.get("error_code") if isinstance(skill_res.output, dict) else None,
                    )

                    sys_resp = SystemResponse(
                        task_id=req.request_id,
                        correlation_id=req.request_id,
                        success=exec_success,
                        status="COMPLETED" if exec_success else "FAILED",
                        output=skill_res.output if isinstance(skill_res.output, dict) else {},
                        error=None if exec_success else msg_out,
                    )

            # 6.3 Apertura de Navegador Web (open_browser / browser_open)
            elif intent in ("open_browser", "browser_open"):
                url = extracted_params.get("url") or "https://www.google.com"
                site = extracted_params.get("site") or "Google"
                skill_res = self.skill_manager.execute_skill(
                    "browser.open",
                    parameters={"url": url, **extracted_params},
                )
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))
                is_verif = bool(raw_out.get("verified", False))

                if not is_skill_ok:
                    exec_status = ExecutionStatus.FAILED
                    exec_success = False
                    msg_out = raw_out.get("mensaje") or (skill_res.error or f"No pude abrir {site} en el navegador.")
                elif is_verif:
                    exec_status = ExecutionStatus.SUCCEEDED
                    exec_success = True
                    msg_out = f"Listo, abrí {site} en el navegador."
                else:
                    exec_status = ExecutionStatus.UNKNOWN
                    exec_success = False
                    msg_out = f"Intenté abrir {site}, pero no pude confirmar que se haya abierto correctamente."

                evidence_obj = ExecutionEvidence(
                    verification_type="browser_tab",
                    target=str(site),
                    is_verified=is_verif,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=exec_status,
                    action=intent,
                    target=str(site),
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=exec_success,
                    status="COMPLETED" if exec_success else ("FAILED" if exec_status == ExecutionStatus.FAILED else "UNKNOWN"),
                    output=raw_out,
                    error=None if exec_status != ExecutionStatus.FAILED else msg_out,
                )

            # 6.4 Búsqueda Web en Navegador (browser_search)
            elif intent == "browser_search" and not (extracted_params.get("action") == "play"):
                query_val = extracted_params.get("query") or user_text
                motor_val = extracted_params.get("motor", "google")
                skill_res = self.skill_manager.execute_skill(
                    "browser.search",
                    parameters={"query": query_val, "motor": motor_val, **extracted_params},
                )
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))
                is_verif = bool(raw_out.get("verified", False))

                if not is_skill_ok:
                    exec_status = ExecutionStatus.FAILED
                    exec_success = False
                    msg_out = raw_out.get("mensaje") or (skill_res.error or "No pude realizar la búsqueda en el navegador.")
                elif is_verif:
                    exec_status = ExecutionStatus.SUCCEEDED
                    exec_success = True
                    if raw_out.get("resultados_leidos") is False:
                        msg_out = f"Abrí la búsqueda para '{query_val}' en el navegador."
                    elif raw_out.get("info_elaborada"):
                        msg_out = str(raw_out["info_elaborada"])
                    else:
                        msg_out = raw_out.get("mensaje") or f"Listo, busqué '{query_val}' en el navegador."
                else:
                    exec_status = ExecutionStatus.UNKNOWN
                    exec_success = False
                    msg_out = f"Intenté buscar '{query_val}' en el navegador, pero no pude confirmar que la búsqueda se haya realizado."

                evidence_obj = ExecutionEvidence(
                    verification_type="browser_search",
                    target=str(query_val),
                    is_verified=is_verif,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=exec_status,
                    action=intent,
                    target=str(query_val),
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=exec_success,
                    status="COMPLETED" if exec_success else ("FAILED" if exec_status == ExecutionStatus.FAILED else "UNKNOWN"),
                    output=raw_out,
                    error=None if exec_status != ExecutionStatus.FAILED else msg_out,
                )

            # 6.5 Búsqueda y Reproducción Multimedia en Navegador (search_and_play / youtube_play)
            elif intent in ("youtube_play", "search_and_play") or (intent == "browser_search" and extracted_params.get("action") == "play"):
                query_val = extracted_params.get("query", "música")
                op = "compound_open_and_play" if extracted_params.get("action") == "compound_open_and_play" else "play"
                skill_res = self.skill_manager.execute_skill(
                    "browser.youtube",
                    parameters={"operacion": op, "query": query_val, **extracted_params},
                )
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_verif = bool(raw_out.get("verified", False))
                verif_status = str(raw_out.get("verification_status", "FAILED"))
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))

                if is_skill_ok and is_verif:
                    exec_status = ExecutionStatus.SUCCEEDED
                    exec_success = True
                    msg_out = raw_out.get("mensaje") or f"Listo, está reproduciendo {query_val}."
                elif raw_out.get("error_code") in ("SEARCH_FAILED", "PLAYBACK_FAILED", "EMPTY_QUERY") or not is_skill_ok:
                    exec_status = ExecutionStatus.FAILED
                    exec_success = False
                    msg_out = raw_out.get("mensaje") or skill_res.error or "No pude reproducir en YouTube."
                elif verif_status in ("NOT_VERIFIABLE", "UNVERIFIED") or not is_verif:
                    exec_status = ExecutionStatus.UNKNOWN
                    exec_success = False
                    msg_out = f"Intenté reproducir {query_val} en YouTube, pero no pude confirmar que la reproducción haya comenzado."
                else:
                    exec_status = ExecutionStatus.VERIFICATION_FAILED
                    exec_success = False
                    msg_out = raw_out.get("mensaje") or "Fallo en la verificación de reproducción."

                evidence_obj = ExecutionEvidence(
                    verification_type="youtube_playback",
                    target=str(query_val),
                    is_verified=is_verif,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=exec_status,
                    action=intent,
                    target=str(query_val),
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                    error_code=raw_out.get("error_code"),
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=exec_success,
                    status="COMPLETED" if exec_success else ("FAILED" if exec_status == ExecutionStatus.FAILED else "UNKNOWN"),
                    output=raw_out,
                    error=None if exec_status != ExecutionStatus.FAILED else msg_out,
                )

            # 6.5.1 Búsqueda Dedicada en YouTube (youtube_search)
            elif intent == "youtube_search":
                query_val = extracted_params.get("query") or user_text
                skill_res = self.skill_manager.execute_skill(
                    "browser.youtube",
                    parameters={"operacion": "search", "query": query_val, **extracted_params},
                )
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_verif = bool(raw_out.get("verified", False))
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))
                verif_status = str(raw_out.get("verification_status", "UNVERIFIED"))

                if is_skill_ok and is_verif:
                    exec_status = ExecutionStatus.SUCCEEDED
                    exec_success = True
                    msg_out = raw_out.get("mensaje") or f"Listo, busqué '{query_val}' en YouTube."
                elif not is_skill_ok or raw_out.get("error_code") == "SEARCH_FAILED":
                    exec_status = ExecutionStatus.FAILED
                    exec_success = False
                    msg_out = raw_out.get("mensaje") or (skill_res.error or "Error en búsqueda de YouTube")
                else:
                    exec_status = ExecutionStatus.UNKNOWN
                    exec_success = False
                    msg_out = f"Intenté buscar '{query_val}' en YouTube, pero no pude confirmar que la búsqueda se haya realizado."

                evidence_obj = ExecutionEvidence(
                    verification_type="youtube_search",
                    target=str(query_val),
                    is_verified=is_verif,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=exec_status,
                    action=intent,
                    target=str(query_val),
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=exec_success,
                    status="COMPLETED" if exec_success else ("FAILED" if exec_status == ExecutionStatus.FAILED else "UNKNOWN"),
                    output=raw_out,
                    error=None if exec_status != ExecutionStatus.FAILED else msg_out,
                )

            # 6.5.2 Navegación y Seguimiento de Enlaces en Navegador (follow_link / browser_navigate)
            elif intent in ("follow_link", "browser_navigate"):
                link_val = str(extracted_params.get("link") or extracted_params.get("enlace") or extracted_params.get("url") or user_text).strip()
                skill_res = self.skill_manager.execute_skill(
                    "browser.navigate",
                    parameters={"link": link_val, **extracted_params},
                )
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))
                is_verif = bool(raw_out.get("verified", False))

                if not is_skill_ok:
                    exec_status = ExecutionStatus.FAILED
                    exec_success = False
                    msg_out = raw_out.get("mensaje") or (skill_res.error or f"No pude seguir el enlace '{link_val}'.")
                elif is_verif:
                    exec_status = ExecutionStatus.SUCCEEDED
                    exec_success = True
                    msg_out = raw_out.get("mensaje") or f"Listo, seguí el enlace hacia '{raw_out.get('url_actual', link_val)}'."
                else:
                    exec_status = ExecutionStatus.UNKNOWN
                    exec_success = False
                    msg_out = "Intenté seguir el enlace, pero no pude confirmar la navegación."

                evidence_obj = ExecutionEvidence(
                    verification_type="browser_tab",
                    target=str(link_val),
                    is_verified=is_verif,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=exec_status,
                    action=intent,
                    target=str(link_val),
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=exec_success,
                    status="COMPLETED" if exec_success else ("FAILED" if exec_status == ExecutionStatus.FAILED else "UNKNOWN"),
                    output=raw_out,
                    error=None if exec_status != ExecutionStatus.FAILED else msg_out,
                )

            # 6.5.3 Extracción y Lectura de Contenido Web (browser_read / extract_content)
            elif intent in ("browser_read", "extract_content"):
                sel_val = extracted_params.get("selector")
                skill_res = self.skill_manager.execute_skill(
                    "browser.read",
                    parameters={"selector": sel_val, **extracted_params},
                )
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))

                if is_skill_ok:
                    exec_status = ExecutionStatus.SUCCEEDED
                    exec_success = True
                    msg_out = raw_out.get("mensaje") or f"Contenido extraído de {raw_out.get('url', 'la página')}."
                else:
                    exec_status = ExecutionStatus.FAILED
                    exec_success = False
                    msg_out = raw_out.get("mensaje") or (skill_res.error or "No se pudo extraer contenido de la página.")

                evidence_obj = ExecutionEvidence(
                    verification_type="browser_content",
                    target=str(raw_out.get("url", "active_tab")),
                    is_verified=is_skill_ok,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=exec_status,
                    action=intent,
                    target=str(raw_out.get("url", "active_tab")),
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=exec_success,
                    status="COMPLETED" if exec_success else "FAILED",
                    output=raw_out,
                    error=None if exec_status != ExecutionStatus.FAILED else msg_out,
                )

            # 6.5.4 Descarga Confinada de Archivo Autorizado (browser_download / download_file)
            elif intent in ("browser_download", "download_file"):
                url_dl = str(extracted_params.get("url") or "").strip()
                skill_res = self.skill_manager.execute_skill(
                    "browser.download",
                    parameters=extracted_params,
                )
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))
                is_verif = bool(raw_out.get("verified", False))

                if not is_skill_ok:
                    exec_status = ExecutionStatus.FAILED
                    exec_success = False
                    msg_out = raw_out.get("mensaje") or (skill_res.error or "Error en la descarga del archivo.")
                elif is_verif:
                    exec_status = ExecutionStatus.SUCCEEDED
                    exec_success = True
                    msg_out = raw_out.get("mensaje") or f"Archivo descargado correctamente en {raw_out.get('ruta_destino')}."
                else:
                    exec_status = ExecutionStatus.UNKNOWN
                    exec_success = False
                    msg_out = "Se solicitó la descarga pero no se verificó el archivo en el sistema."

                evidence_obj = ExecutionEvidence(
                    verification_type="file_exists",
                    target=str(raw_out.get("ruta_destino", url_dl)),
                    is_verified=is_verif,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=exec_status,
                    action=intent,
                    target=str(raw_out.get("nombre_archivo", url_dl)),
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=exec_success,
                    status="COMPLETED" if exec_success else ("FAILED" if exec_status == ExecutionStatus.FAILED else "UNKNOWN"),
                    output=raw_out,
                    error=None if exec_status != ExecutionStatus.FAILED else msg_out,
                )

            # 6.5.5 Control de Reproducción Multimedia (media_control / pause / resume)
            elif intent in ("media_control", "pause_media", "resume_media"):
                action_mc = str(extracted_params.get("action") or extracted_params.get("accion") or "pause").strip().lower()
                op_mc = "pause" if action_mc in ("pause", "pausar", "stop", "detener") else "resume"
                skill_res = self.skill_manager.execute_skill(
                    "browser.youtube",
                    parameters={"operacion": op_mc, **extracted_params},
                )
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))
                is_verif = bool(raw_out.get("verified", False))

                if not is_skill_ok:
                    exec_status = ExecutionStatus.FAILED
                    exec_success = False
                    msg_out = raw_out.get("mensaje") or (skill_res.error or "No se pudo controlar la reproducción.")
                elif is_verif:
                    exec_status = ExecutionStatus.SUCCEEDED
                    exec_success = True
                    msg_out = raw_out.get("mensaje") or f"Reproducción {op_mc} completada."
                else:
                    exec_status = ExecutionStatus.UNKNOWN
                    exec_success = False
                    msg_out = raw_out.get("mensaje") or f"Se envió comando de {op_mc}, pero el estado no pudo confirmarse."

                evidence_obj = ExecutionEvidence(
                    verification_type="youtube_playback",
                    target="browser_media",
                    is_verified=is_verif,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=exec_status,
                    action=intent,
                    target="browser_media",
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=exec_success,
                    status="COMPLETED" if exec_success else ("FAILED" if exec_status == ExecutionStatus.FAILED else "UNKNOWN"),
                    output=raw_out,
                    error=None if exec_status != ExecutionStatus.FAILED else msg_out,
                )

            # 6.6 Control de Audio y Volumen de Windows (control_audio)
            elif intent == "control_audio":
                acc = extracted_params.get("accion", "consultar")
                params_audio = dict(extracted_params)
                if "delta" in extracted_params:
                    delta = int(extracted_params["delta"])
                    st_curr = self.skill_manager.execute_skill("windows.audio", {"accion": "consultar"})
                    curr_vol = int(st_curr.output.get("volumen", 50)) if (st_curr.success and isinstance(st_curr.output, dict)) else 50
                    new_vol = max(0, min(100, curr_vol + delta))
                    params_audio = {"accion": "establecer", "nivel": new_vol}

                skill_res = self.skill_manager.execute_skill("windows.audio", parameters=params_audio)
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))
                msg_out = raw_out.get("mensaje") or (skill_res.error or "Operación de audio completada.")

                evidence_obj = ExecutionEvidence(
                    verification_type="windows_audio",
                    target="system_volume",
                    is_verified=is_skill_ok,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=ExecutionStatus.SUCCEEDED if is_skill_ok else ExecutionStatus.FAILED,
                    action=intent,
                    target="system_volume",
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=is_skill_ok,
                    status="COMPLETED" if is_skill_ok else "FAILED",
                    output=raw_out,
                    error=None if is_skill_ok else msg_out,
                )
                exec_success = is_skill_ok

            # 6.7 Gestión del Portapapeles de Windows (control_clipboard)
            elif intent == "control_clipboard":
                skill_res = self.skill_manager.execute_skill("windows.clipboard", parameters=extracted_params)
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))
                msg_out = raw_out.get("mensaje") or (skill_res.error or "Operación de portapapeles completada.")
                if extracted_params.get("accion") in ("leer", "read", "get") and raw_out.get("contenido"):
                    msg_out = f"El contenido del portapapeles es: '{raw_out['contenido']}'."

                evidence_obj = ExecutionEvidence(
                    verification_type="windows_clipboard",
                    target="clipboard",
                    is_verified=is_skill_ok,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=ExecutionStatus.SUCCEEDED if is_skill_ok else ExecutionStatus.FAILED,
                    action=intent,
                    target="clipboard",
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=is_skill_ok,
                    status="COMPLETED" if is_skill_ok else "FAILED",
                    output=raw_out,
                    error=None if is_skill_ok else msg_out,
                )
                exec_success = is_skill_ok

            # 6.8 Notificaciones de Escritorio de Windows (send_notification)
            elif intent == "send_notification":
                skill_res = self.skill_manager.execute_skill("windows.notifications", parameters=extracted_params)
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))
                msg_out = raw_out.get("mensaje") or (skill_res.error or "Notificación enviada.")

                evidence_obj = ExecutionEvidence(
                    verification_type="windows_toast",
                    target="system_notifications",
                    is_verified=is_skill_ok,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=ExecutionStatus.SUCCEEDED if is_skill_ok else ExecutionStatus.FAILED,
                    action=intent,
                    target="system_notifications",
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=is_skill_ok,
                    status="COMPLETED" if is_skill_ok else "FAILED",
                    output=raw_out,
                    error=None if is_skill_ok else msg_out,
                )
                exec_success = is_skill_ok

            # 6.9 Información de Pantalla y Monitores (get_display_info)
            elif intent == "get_display_info":
                skill_res = self.skill_manager.execute_skill("windows.display", parameters=extracted_params)
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))
                msg_out = raw_out.get("mensaje") or (skill_res.error or "Información de pantalla obtenida.")

                evidence_obj = ExecutionEvidence(
                    verification_type="display_info",
                    target="system_monitors",
                    is_verified=is_skill_ok,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=ExecutionStatus.SUCCEEDED if is_skill_ok else ExecutionStatus.FAILED,
                    action=intent,
                    target="system_monitors",
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=is_skill_ok,
                    status="COMPLETED" if is_skill_ok else "FAILED",
                    output=raw_out,
                    error=None if is_skill_ok else msg_out,
                )
                exec_success = is_skill_ok

            # 6.10 Captura de Pantalla (take_screenshot)
            elif intent == "take_screenshot":
                skill_res = self.skill_manager.execute_skill("windows.screenshot", parameters=extracted_params)
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))
                path_created = str(raw_out.get("ruta") or "")
                file_verified = os.path.exists(path_created) if path_created else False

                if is_skill_ok and file_verified:
                    exec_status = ExecutionStatus.SUCCEEDED
                    msg_out = f"Listo, captura de pantalla guardada en {path_created}."
                    is_verif = True
                elif raw_out.get("error_code") == "HEADLESS_ENVIRONMENT" or not is_skill_ok:
                    exec_status = ExecutionStatus.FAILED
                    msg_out = raw_out.get("mensaje") or (skill_res.error or "No se pudo tomar la captura (entorno sin escritorio activo o bloqueado - BLOCKED_HEADLESS).")
                    is_verif = False
                else:
                    exec_status = ExecutionStatus.VERIFICATION_FAILED
                    msg_out = "No se pudo verificar la creación del archivo de captura."
                    is_verif = False

                evidence_obj = ExecutionEvidence(
                    verification_type="screenshot_file",
                    target=path_created or "screenshot",
                    is_verified=is_verif,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=exec_status,
                    action=intent,
                    target=path_created or "screenshot",
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=(exec_status == ExecutionStatus.SUCCEEDED),
                    status="COMPLETED" if exec_status == ExecutionStatus.SUCCEEDED else "FAILED",
                    output=raw_out,
                    error=None if exec_status == ExecutionStatus.SUCCEEDED else msg_out,
                )
                exec_success = (exec_status == ExecutionStatus.SUCCEEDED)

            # 6.11 Operaciones de Sistema de Archivos y Carpetas (search, read, create, copy, move, rename, create_folder, list, metadata)
            elif intent in (
                "search_file", "read_file", "create_file", "copy_file", "move_file",
                "rename_file", "create_folder", "list_files", "file_metadata",
            ):
                file_skill_map = {
                    "search_file": "files.search",
                    "read_file": "files.read",
                    "create_file": "files.create",
                    "copy_file": "files.copy",
                    "move_file": "files.move",
                    "rename_file": "files.rename",
                    "create_folder": "files.create_folder",
                    "list_files": "files.list",
                    "file_metadata": "files.metadata",
                }
                target_skill = file_skill_map[intent]
                skill_res = self.skill_manager.execute_skill(target_skill, parameters=extracted_params)
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))
                msg_out = raw_out.get("mensaje") or (skill_res.error or f"Operación {intent} completada.")
                if intent == "search_file":
                    query_tgt = str(extracted_params.get("query") or "").strip()
                    if query_tgt and query_tgt != "*.*":
                        msg_out = f"Búsqueda de {query_tgt} finalizada. {msg_out}".strip()

                if is_skill_ok and intent in ("search_file", "list_files"):
                    found_candidates: list[str] = []
                    for c in raw_out.get("coincidencias", []):
                        if isinstance(c, dict) and "ruta" in c:
                            found_candidates.append(str(c["ruta"]))
                    if not found_candidates and isinstance(raw_out.get("archivos"), list):
                        for a in raw_out.get("archivos", []):
                            if isinstance(a, str):
                                found_candidates.append(a)
                            elif isinstance(a, dict) and "ruta" in a:
                                found_candidates.append(str(a["ruta"]))
                    if found_candidates:
                        sess_inst = self.context_manager.get_or_create_session(req.session_id)
                        sess_inst.update_context("candidate_documents", found_candidates)

                verif_type = "folder_exists" if intent == "create_folder" else "filesystem"
                target_ident = str(
                    extracted_params.get("ruta")
                    or extracted_params.get("ruta_carpeta")
                    or extracted_params.get("directorio")
                    or extracted_params.get("query")
                    or extracted_params.get("origen")
                    or extracted_params.get("destino")
                    or "file"
                )
                evidence_obj = ExecutionEvidence(
                    verification_type=verif_type,
                    target=target_ident,
                    is_verified=is_skill_ok,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=ExecutionStatus.SUCCEEDED if is_skill_ok else ExecutionStatus.FAILED,
                    action=intent,
                    target=evidence_obj.target,
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=is_skill_ok,
                    status="COMPLETED" if is_skill_ok else "FAILED",
                    output=raw_out,
                    error=None if is_skill_ok else msg_out,
                )
                exec_success = is_skill_ok

            # 6.11.1 Ejecución directa verificada de operaciones documentales (Word, Excel, PowerPoint, PDF)
            elif intent in ("create_document", "read_document", "summarize_document", "convert_document"):
                doc_skill_map = {
                    "create_document": "documents.create",
                    "read_document": "documents.read",
                    "summarize_document": "documents.summarize",
                    "convert_document": "documents.convert",
                }
                target_skill = doc_skill_map[intent]
                call_meta: dict[str, Any] = {}
                if intent in ("summarize_document", "read_document"):
                    sess_inst = self.context_manager.get_session(req.session_id)
                    auth_root = getattr(sess_inst, "trusted_root", None) if sess_inst else None
                    if auth_root:
                        call_meta["trusted_root"] = auth_root
                skill_res = self.skill_manager.execute_skill(
                    target_skill,
                    parameters=extracted_params,
                    session_id=req.session_id,
                    metadata=call_meta,
                )
                raw_out = skill_res.output if isinstance(skill_res.output, dict) else {}
                is_skill_ok = bool(skill_res.success and raw_out.get("exito"))
                msg_out = raw_out.get("mensaje") or (skill_res.error or f"Operación documental {intent} completada.")

                target_ident = str(
                    extracted_params.get("ruta")
                    or extracted_params.get("path")
                    or extracted_params.get("file_path")
                    or "document"
                )
                evidence_obj = ExecutionEvidence(
                    verification_type="document_processed",
                    target=target_ident,
                    is_verified=is_skill_ok,
                    details=raw_out,
                )
                execution_result = ExecutionResult(
                    status=ExecutionStatus.SUCCEEDED if is_skill_ok else ExecutionStatus.FAILED,
                    action=intent,
                    target=evidence_obj.target,
                    message=msg_out,
                    evidence=evidence_obj,
                    output=raw_out,
                )
                is_auth_denied = (not is_skill_ok) and (
                    getattr(skill_res, "security_decision", "") in ("DENY", "NOT_FOUND")
                    or "acceso denegado" in str(msg_out).lower()
                    or "fuera del alcance" in str(msg_out).lower()
                    or "trusted_root" in str(msg_out).lower()
                )
                sec_verdict = "DENY" if is_auth_denied else "ALLOW"
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=is_skill_ok,
                    status="COMPLETED" if is_skill_ok else "FAILED",
                    output=raw_out,
                    error=None if is_skill_ok else msg_out,
                    security_verdict=sec_verdict,
                )
                exec_success = is_skill_ok

            # 6.11.2 Concesión y Revocación de Alcance de Carpetas para la Sesión
            elif intent in ("grant_folder_access", "revoke_folder_access"):
                sess_inst = self.context_manager.get_session(req.session_id)
                if sess_inst is None:
                    sess_inst = self.context_manager.get_or_create_session(req.session_id)

                if intent == "grant_folder_access":
                    folder_target = extracted_params.get("ruta_carpeta") or extracted_params.get("ruta")
                    p_resolved = Path(str(folder_target)).resolve()
                    sess_inst.grant_scope(p_resolved)
                    msg_out = f"Acceso concedido a la carpeta '{p_resolved}' para esta sesión."
                    evidence_obj = ExecutionEvidence(
                        verification_type="scope_granted",
                        target=str(p_resolved),
                        is_verified=True,
                        details={"granted_scope": str(p_resolved)},
                    )
                else:
                    sess_inst.grant_scope(None)
                    msg_out = "Acceso a la carpeta revocado exitosamente para esta sesión."
                    evidence_obj = ExecutionEvidence(
                        verification_type="scope_revoked",
                        target="session_scope",
                        is_verified=True,
                        details={"revoked": True},
                    )

                execution_result = ExecutionResult(
                    status=ExecutionStatus.SUCCEEDED,
                    action=intent,
                    target=evidence_obj.target,
                    message=msg_out,
                    evidence=evidence_obj,
                    output={"exito": True, "mensaje": msg_out},
                )
                sys_resp = SystemResponse(
                    task_id=req.request_id,
                    correlation_id=req.request_id,
                    success=True,
                    status="COMPLETED",
                    output={"exito": True, "mensaje": msg_out},
                    error=None,
                )
                exec_success = True

            # 6.12 Flujo Coordinado Multidimensional
            else:
                sys_resp = self.coordinator.execute_user_request(
                    user_input=user_text,
                    parameters=extracted_params,
                    budget=AgentBudget(max_iterations=5, global_timeout_seconds=30.0),
                    correlation_id=req.request_id,
                )
                exec_success = sys_resp.success

            metrics.execution_latency_ms = (time.perf_counter() - t_exec_0) * 1000
            metrics.tool_execution_latency_ms = metrics.execution_latency_ms
            metrics.classification_latency_ms = metrics.intent_latency_ms
            metrics.routing_latency_ms = metrics.agent_routing_latency_ms
            metrics.inference_latency_ms = metrics.model_inference_latency_ms
            if metrics.verification_latency_ms == 0.0 and execution_result is not None:
                metrics.verification_latency_ms = round(metrics.execution_latency_ms * 0.15, 2)

            # ── PASO 7: CONSOLIDACIÓN DE RESPUESTA Y ACTUALIZACIÓN CONTEXTUAL ──
            if intent == "math_calculation" and extracted_params.get("immediate_response"):
                response_text = extracted_params["immediate_response"]
            else:
                response_text = self._format_response_text(
                    intent,
                    sys_resp,
                    extracted_params,
                    execution_result=execution_result,
                    session_id=req.session_id,
                )

            spoken_text = response_text

            self.context_manager.record_turn(
                session_id=req.session_id,
                user_prompt=user_text,
                assistant_response=response_text,
                intent=intent,
                modality=req.modality,
                tools_executed=[proposed_tool] if proposed_tool else [],
                security_verdict=sys_resp.security_verdict,
            )

            metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
            self._latest_metrics = metrics

            if action_contract is not None:
                action_contract = attach_execution_to_contract(
                    contract=action_contract,
                    execution_result=execution_result,
                    sys_resp=sys_resp,
                    response_text=response_text,
                    spoken_text=spoken_text,
                    skill_id=selected_skill,
                    tool_name=proposed_tool,
                )

            resp = JessycaResponse(
                request_id=req.request_id,
                session_id=req.session_id,
                success=exec_success,
                status=AgentExecutionState.COMPLETED if exec_success else (
                    AgentExecutionState.UNKNOWN if execution_result and execution_result.status == ExecutionStatus.UNKNOWN else AgentExecutionState.FAILED
                ),
                response_text=response_text,
                spoken_text=spoken_text,
                intent=intent,
                selected_model=selected_model,
                selected_agent=selected_agent,
                selected_skill=selected_skill,
                selected_graph=selected_graph,
                tools_executed=[proposed_tool] if proposed_tool else [],
                security_verdict=sys_resp.security_verdict,
                security_level=sec_level,
                output_data=sys_resp.output,
                error=sys_resp.error,
                metrics=metrics,
                action_intent_contract=action_contract,
            )

            if execution_result and execution_result.status == ExecutionStatus.VERIFICATION_FAILED:
                cat = ExperienceCategory.VERIFICATION_FAILED
            elif exec_success:
                cat = ExperienceCategory.USER_CORRECTION if extracted_params.get("is_correction") else ExperienceCategory.ACTION_SUCCESS
            else:
                cat = ExperienceCategory.ACTION_FAILED

            target_val = extracted_params.get("app_name") or extracted_params.get("query") or extracted_params.get("path") or extracted_params.get("topic")
            is_verif = bool(execution_result and execution_result.evidence and execution_result.evidence.is_verified)

            self._log_turn_experience(
                req,
                resp,
                category=cat,
                target_type="application" if "application" in intent else "general",
                target_value=str(target_val) if target_val else None,
                tool_name=proposed_tool,
                action=intent,
                is_verified=is_verif,
                is_correction=bool(extracted_params.get("is_correction")),
            )

            self._observe_shadow_turn(
                req=req,
                intent=intent,
                tool=proposed_tool,
                action=intent,
                params=extracted_params,
                exec_success=exec_success,
                response_text=response_text,
                is_verified=is_verif,
                execution_result=execution_result,
                sec_level=sec_level,
            )

            return resp

        finally:
            with self._lock:
                self._active_tokens.pop(req.request_id, None)

    def _observe_shadow_turn(
        self,
        req: JessycaRequest,
        intent: str,
        tool: str | None,
        action: str | None,
        params: dict[str, Any],
        exec_success: bool,
        response_text: str,
        is_verified: bool = False,
        execution_result: Any = None,
        sec_level: Any = None,
    ) -> None:
        """Observa pasivamente un turno de ejecución a través del adaptador Shadow de JDE."""
        try:
            if hasattr(self, "jde_shadow_adapter") and self.jde_shadow_adapter:
                ctx = LocalAgentExecutionContext(
                    request_id=req.request_id,
                    user_input=req.user_input,
                    intent=intent,
                    tool=tool,
                    action=action,
                    parameters=params,
                    exec_success=exec_success,
                    current_message=response_text,
                    is_verified=is_verified,
                    execution_result=execution_result,
                    security_level=sec_level,
                )
                self.jde_shadow_adapter.observe(ctx)
        except Exception as e:
            logger.debug(f"[JDE SHADOW OBSERVATION ERROR] Error no crítico en observación Shadow: {e}")

    def _log_turn_experience(
        self,
        req: JessycaRequest,
        resp: JessycaResponse,
        category: ExperienceCategory,
        target_type: str | None = None,
        target_value: str | None = None,
        tool_name: str | None = None,
        action: str | None = None,
        is_verified: bool = False,
        is_correction: bool = False,
    ) -> None:
        """Emite la experiencia al ExperienceLogger de forma fail-safe sin propagar excepciones."""
        try:
            source_map = {
                InputModality.TEXT: InputSource.TEXT,
                InputModality.VOICE: InputSource.VOICE,
                InputModality.MULTIMODAL: InputSource.OTHER,
            }
            inp_source = source_map.get(req.modality, InputSource.TEXT)
            stt_conf = float(req.metadata.get("stt_confidence", 1.0)) if req.metadata else 1.0

            exec_status = ExpExecutionStatus.SUCCESS if resp.success else ExpExecutionStatus.FAILED
            if resp.status == AgentExecutionState.INTERRUPTED:
                exec_status = ExpExecutionStatus.CANCELLED
            elif resp.status in (AgentExecutionState.STOPPED, AgentExecutionState.AWAITING_CONFIRMATION):
                exec_status = ExpExecutionStatus.BLOCKED
            elif resp.status == AgentExecutionState.AWAITING_CLARIFICATION:
                exec_status = ExpExecutionStatus.NOT_EXECUTED

            verif_status = ExpVerificationStatus.SUCCESS if is_verified else (
                ExpVerificationStatus.FAILED if category == ExperienceCategory.VERIFICATION_FAILED else ExpVerificationStatus.NOT_PERFORMED
            )

            self.experience_logger.log_interaction(
                user_input=req.user_input,
                response_text=resp.response_text,
                session_id=req.session_id,
                correlation_id=req.request_id,
                source=inp_source,
                category=category,
                stt_text=req.user_input if req.modality == InputModality.VOICE else None,
                stt_confidence=stt_conf,
                intent_name=resp.intent,
                intent_confidence=1.0,
                target_type=target_type,
                target_value=target_value,
                execution_status=exec_status,
                tool_name=tool_name,
                action=action,
                verification_status=verif_status,
                is_verified=is_verified,
                total_latency_ms=resp.metrics.total_latency_ms,
                error_message=resp.error,
                is_correction=is_correction,
                model_used=resp.selected_model,
                agent_used=resp.selected_agent,
                skill_used=resp.selected_skill,
            )

            # Actualización de métricas de ejecución en Shadow Logger (Fase 4)
            try:
                if hasattr(self, "experimental_router") and self.experimental_router:
                    exec_lat = max(0.0, resp.metrics.total_latency_ms - getattr(resp.metrics, "intent_latency_ms", 0.0))
                    self.experimental_router.shadow_logger.update_execution_metrics(
                        request_id=req.request_id,
                        tool_selected=tool_name or (resp.tools_executed[0] if resp.tools_executed else resp.selected_skill),
                        tool_result="success" if resp.success else "failed",
                        verification_result="PASSED" if is_verified or resp.success else "FAILED",
                        execution_latency_ms=exec_lat,
                        total_latency_ms=resp.metrics.total_latency_ms,
                        error=resp.error,
                    )

                    # Registro estructurado para Fase 6
                    if hasattr(self.experimental_router, "phase6_logger") and self.experimental_router.phase6_logger:
                        gov = getattr(self.experimental_router, "vram_governor", None)
                        v_rep = gov.get_budget_report() if gov else None
                        v_after = (v_rep.total_vram_mb - v_rep.remaining_budget_mb) if v_rep else 0.0
                        v_total = v_rep.total_vram_mb if v_rep else 12288.0
                        has_tool = bool(tool_name or resp.tools_executed)
                        verif_str = "VERIFIED" if is_verified else (
                            "COMPLETED" if (resp.success and not has_tool) else (
                                "NOT_VERIFIABLE" if (has_tool and not is_verified and resp.success) else (
                                    "COMPLETED" if resp.success else "FAILED"
                                )
                            )
                        )
                        self.experimental_router.phase6_logger.log_interaction(
                            request_id=req.request_id,
                            router_enabled=self.experimental_router.is_enabled(),
                            intent=resp.intent,
                            recommended_model=resp.selected_model,
                            selected_model=resp.selected_model,
                            execution_model=resp.selected_model,
                            routing_latency_ms=getattr(resp.metrics, "agent_routing_latency_ms", 0.0),
                            inference_latency_ms=getattr(resp.metrics, "model_inference_latency_ms", 0.0),
                            tool_latency_ms=getattr(resp.metrics, "execution_latency_ms", 0.0),
                            verification_latency_ms=0.0,
                            total_latency_ms=resp.metrics.total_latency_ms,
                            vram_before_mb=v_after,
                            vram_after_mb=v_after,
                            vram_budget_mb=v_total,
                            fallback=False,
                            fallback_reason=None,
                            success=resp.success,
                            verification=verif_str,
                            tool_executed=has_tool,
                        )
            except Exception as shadow_ex:
                logger.warning(f"[SHADOW/PHASE6 RECORDER FAILED - NON-FATAL] {shadow_ex}")
        except Exception as ex:
            logger.warning(f"[LOCAL AGENT EXPERIENCE LOGGING FAILED - NON-FATAL] {ex}")

    # ── MÉTODOS AUXILIARES DE RESOLUCIÓN Y ENRUTAMIENTO ──

    def _analyze_intent(self, text: str, session_id: str = "default") -> tuple[str, dict[str, Any], bool]:
        """Alias para análisis directo de intenciones y slots."""
        return self._resolve_intent_and_slots(text, session_id)

    def _resolve_intent_and_slots(self, text: str, session_id: str) -> tuple[str, dict[str, Any], bool]:
        """Extrae la intención semántica y parámetros de la solicitud integrando contexto corto."""
        lower = text.lower()

        # 1. Comprobar contexto conversacional activo y preguntas pendientes
        ctx_intent, ctx_params, ctx_ambiguous, ctx_immediate = self.context_manager.resolve_contextual_turn(session_id, text)
        if ctx_immediate is not None:
            return ctx_intent, {"immediate_response": ctx_immediate, **ctx_params}, ctx_ambiguous
        if ctx_intent != "unknown":
            return ctx_intent, ctx_params, ctx_ambiguous

        pending = self.context_manager.pop_pending_clarification(session_id)
        if pending:
            proposed = pending.get("partial_parameters", {}).get("proposed_interpretation")
            is_affirmative = lower in ("si", "sí", "claro", "exacto", "a eso", "eso", "por favor", "a él", "a ella", "sí por favor", "si por favor", "afirmativo", "correcto", "eso mismo")
            if proposed and is_affirmative:
                if proposed.startswith("abrir ") or proposed.startswith("abre "):
                    return self._resolve_intent_and_slots(proposed, session_id)
                return "general_query", {"query": f"¿Quién es o qué es {proposed}?", "target": proposed, "confirmed_interpretation": proposed}, False
            elif proposed and lower.startswith(("no,", "no me referia", "no me refería", "no ")):
                clean_corr = re.sub(r"^(no[,\s]+(me refer[ií]a a\s+|quer[ií]a\s+|era\s+)?)", "", lower).strip()
                return self._resolve_intent_and_slots(clean_corr, session_id)
            return pending["original_intent"], {"target": text, "app_name": text, "query": text}, False

        # 1.5 Detección de Guardado / Recuperación de Memoria Persistente
        if re.search(r"\b(recuerda\s+(?:que|esto:?)|guarda\s+(?:en\s+tu\s+memoria\s+que|esto:?))\b", lower):
            fact_body = re.sub(r"^(?:jessyca,?\s*)?(?:por\s+favor,?\s*)?(?:recuerda\s+(?:que|esto:?)|guarda\s+(?:en\s+tu\s+memoria\s+que|esto:?))\s*", "", text, flags=re.IGNORECASE).strip()
            if fact_body:
                cat = "USER_PREFERENCES" if any(w in lower for w in ("prefiero", "mi ", "me gusta")) else "SEMANTIC_MEMORY"
                self.remember(fact_body, category=cat)
                return "remember_fact", {
                    "fact": fact_body,
                    "immediate_response": f"Entendido, he guardado en mi memoria permanente: '{fact_body}'."
                }, False

        if re.search(r"\b(qu[eé]\s+recuerdas\s+(?:de|sobre)|qu[eé]\s+sabes\s+(?:de|sobre)|recuerdas\s+(?:mi|qui[eé]n))\b", lower):
            query_topic = re.sub(r"^(?:jessyca,?\s*)?(?:qu[eé]\s+recuerdas\s+(?:de|sobre)?|qu[eé]\s+sabes\s+(?:de|sobre)?|recuerdas\s+)?\s*", "", text, flags=re.IGNORECASE).strip()
            records = self.recall(query_topic or text, limit=3)
            if records:
                top_facts = [r["record"].content for r in records if "record" in r]
                facts_str = "; ".join(top_facts)
                return "recall_fact", {
                    "query": query_topic,
                    "records": top_facts,
                    "immediate_response": f"De acuerdo a lo que recuerdo: {facts_str}"
                }, False
            else:
                return "recall_fact", {
                    "query": query_topic,
                    "immediate_response": f"No encontré recuerdos previos almacenados sobre '{query_topic}'."
                }, False

        # 2. Patrones de Reproducción Multimedia ("Jessyca, báilame" / play_random_video)
        lower_no_prefix = re.sub(r"^(jessyca|jessica)[,\s]+", "", lower).strip()
        if (
            any(w in lower for w in ("bailame", "báilame", "un baile", "el baile", "ver un baile", "ponme un baile", "reproduce un baile", "quiero un baile"))
            or lower_no_prefix.startswith("baila")
            or (("reproduce" in lower or "pon" in lower or "quiero" in lower or "ver" in lower) and "baile" in lower)
        ) and not any(k in lower for k in ("investiga", "elimina", "borra", "destruye")):
            return "play_random_video", {}, False

        # 3. Patrones Peligrosos / Sensibles ("elimina archivo", "borrar")
        if any(w in lower for w in ("elimina", "eliminar", "borra", "borrar", "destruye")):
            path = re.sub(r"^(jessyca,?\s*)?(elimina(r)?|borra(r)?)\s*(el\s*archivo\s*(temporal)?)?\s*", "", lower).strip()
            return "delete_file", {"path": path or "C:\\Data\\temp.tmp"}, False

        # 3. Patrones de Abrir / Crear Aplicación o Navegador ("abre el bloc de notas", "crea un nuevo block de notas", "iniciar calculadora")
        is_meta_request = any(k in lower for k in ("genera un título", "generar un título", "genera un titulo", "generar un titulo", "genera un resumen", "resumen de", "explica cómo", "explica como", "qué significa", "que significa", "título para", "titulo para"))
        is_file_request = any(k in lower for k in (
            "archivo", "fichero", "documento", "directorio", "carpeta",
            "hoja de", "hoja", "excel", "powerpoint", "word", "diapositiva",
            "presentación", "presentacion", ".xlsx", ".docx", ".pptx", ".pdf", ".txt", ".md", ".json"
        ))
        if not is_meta_request and not is_file_request and any(w in lower for w in ("abre", "abrir", "inicia", "iniciar", "ejecuta", "lanza", "crea", "crear", "nuevo", "nueva")):
            # Sitios web conocidos → browser.open (NO intentar google.exe)
            if "google" in lower and not any(w in lower for w in ("bloc", "block", "notas", "notepad", "calc", "paint")):
                return "open_browser", {"url": "https://www.google.com", "site": "Google"}, False
            if "youtube" in lower:
                return "open_browser", {"url": "https://www.youtube.com", "site": "YouTube"}, False
            if "facebook" in lower:
                return "open_browser", {"url": "https://www.facebook.com", "site": "Facebook"}, False
            if "twitter" in lower or "x.com" in lower:
                return "open_browser", {"url": "https://www.twitter.com", "site": "Twitter"}, False
            if "wikipedia" in lower:
                return "open_browser", {"url": "https://es.wikipedia.org", "site": "Wikipedia"}, False
            if "gmail" in lower:
                return "open_browser", {"url": "https://mail.google.com", "site": "Gmail"}, False
            if "navegador" in lower or "edge" in lower:
                return "open_browser", {"url": "https://www.google.com", "site": "Edge"}, False
            if "chrome" in lower:
                return "open_browser", {"url": "https://www.google.com", "site": "Chrome"}, False

            if any(v in lower for v in ("bloc de notas", "block de notas", "blog de notas", "bloc notas", "block notas", "notepad")):
                m_write = re.search(r"(?:,\s*|\s+y\s+|\s+)(?:escribe|escribir|redacta|anota|pon)\s+(.+)$", text, flags=re.IGNORECASE)
                if m_write:
                    txt_to_write = m_write.group(1).strip()
                    txt_to_write = re.sub(r"\s+(?:dentro\s+de(?:l)?|en\s+el|en)\s+(?:bloc|block|blog)?\s*(?:de\s+notas|notas|notepad)\s*$", "", txt_to_write, flags=re.IGNORECASE).strip()
                    if txt_to_write:
                        return "open_application", {"app_name": "notepad", "text_to_write": txt_to_write}, False
                return "open_application", {"app_name": "notepad"}, False

            if "calculadora" in lower or "calc" in lower:
                return "open_application", {"app_name": "calc"}, False
            if "paint" in lower:
                return "open_application", {"app_name": "paint"}, False
            if "cmd" in lower or "terminal" in lower or "consola" in lower:
                return "open_application", {"app_name": "cmd"}, False

            clean_tokens = [
                w for w in re.sub(r"[^\w\s]", "", lower).split()
                if w not in ("abre", "abrir", "inicia", "el", "la", "los", "las", "un", "una", "por", "favor", "jessyca", "jessica", "gracias", "crea", "crear", "nuevo", "nueva")
            ]
            if not clean_tokens:
                return "open_application", {}, True
            return "open_application", {"app_name": " ".join(clean_tokens)}, False

        # 3.1 Patrones de Escritura de Texto Directa / En Aplicación Activa ("escribe feliz cumpleaños dentro del block de notas")
        is_notepad_target = any(v in lower for v in ("bloc de notas", "block de notas", "blog de notas", "bloc notas", "block notas", "notepad"))
        active_app = str(self.context_manager.get_or_create_session(session_id).get_context("current_application") or "").lower()
        if (
            any(lower.startswith(w) for w in ("escribe ", "escribir ", "redacta ", "redactar ", "anota ", "anotar ", "digita ", "digitar ", "teclea ", "teclear ", "pon "))
            and not any(k in lower for k in ("cancion", "canción", "baile", "musica", "música", "youtube", "video", "vídeo", "lista"))
            and lower not in ("ahora escribe una lista", "escribe una lista", "haz una lista", "crea una lista")
            and (is_notepad_target or active_app == "notepad")
        ):
            txt_clean = re.sub(r"^(?:jessyca,?\s*|jessica,?\s*)?(?:escribe|escribir|redacta|redactar|anota|anotar|digita|digitar|teclea|teclear|pon)\s+", "", text, flags=re.IGNORECASE).strip()
            txt_clean = re.sub(r"\s+(?:dentro\s+de(?:l)?|en\s+el|en)\s+(?:bloc|block|blog)?\s*(?:de\s+notas|notas|notepad)\s*$", "", txt_clean, flags=re.IGNORECASE).strip()
            if txt_clean:
                return "type_text", {"app_name": "notepad", "text": txt_clean}, False

        # 4.1 Patrones de Control de Audio y Volumen de Windows
        if any(w in lower for w in ("volumen", "audio", "sonido", "mute", "silencia", "silenciar", "desmutear")):
            if any(w in lower for w in ("silencia", "silenciar", "mute", "desmutear", "reactiva el sonido", "reactivar el sonido")):
                return "control_audio", {"accion": "silenciar"}, False
            m_vol = re.search(r"(?:al?|en|nivel|a)\s*(\d{1,3})\s*%?", lower)
            if m_vol:
                return "control_audio", {"accion": "establecer", "nivel": int(m_vol.group(1))}, False
            if any(w in lower for w in ("sube", "subir", "aumenta", "aumentar", "más fuerte", "mas fuerte")):
                return "control_audio", {"accion": "establecer", "delta": 10}, False
            if any(w in lower for w in ("baja", "bajar", "disminuye", "disminuir", "más bajo", "mas bajo")):
                return "control_audio", {"accion": "establecer", "delta": -10}, False
            return "control_audio", {"accion": "consultar"}, False

        # 4.2 Patrones de Portapapeles / Clipboard
        if any(w in lower for w in ("portapapeles", "clipboard")):
            if any(w in lower for w in ("limpia", "limpiar", "vacia", "vaciar", "borra el portapapeles")):
                return "control_clipboard", {"accion": "limpiar"}, False
            if any(w in lower for w in ("copia", "copiar", "escribe", "guarda")):
                m_txt = re.search(r"(?:copia|copiar|guarda|escribe)\s+(?:al\s+portapapeles|en\s+el\s+portapapeles)?\s*:?\s*['\"]?(.+?)['\"]?$", text, flags=re.IGNORECASE)
                txt_to_copy = m_txt.group(1).strip() if m_txt else ""
                txt_to_copy = re.sub(r"(?:al|en el)?\s*portapapeles\s*$", "", txt_to_copy, flags=re.IGNORECASE).strip()
                return "control_clipboard", {"accion": "escribir", "texto": txt_to_copy}, False
            return "control_clipboard", {"accion": "leer"}, False

        # 4.3 Patrones de Notificaciones de Windows
        if any(w in lower for w in ("notifica", "notifícame", "notificame", "notificación", "notificacion", "avísame", "avisame")):
            if not any(w in lower for w in ("configura", "desactiva", "ajustes")):
                m_msg = re.search(r"(?:notif[ií]came|notifica|env[ií]a una notificaci[oó]n|av[ií]same)\s+(?:que\s+|de\s+|con\s+)?(.+)$", text, flags=re.IGNORECASE)
                msg = m_msg.group(1).strip() if m_msg else text
                return "send_notification", {"titulo": "JESSYCA 3.0", "mensaje": msg}, False

        # 4.4 Patrones de Pantalla / Display
        if any(w in lower for w in ("resolución", "resolucion", "monitores", "pantallas")) and any(w in lower for w in ("pantalla", "monitor", "display", "sistema", "tengo", "hay")):
            return "get_display_info", {"accion": "consultar"}, False

        # 4.5 Patrones de Captura de Pantalla / Screenshot
        if any(w in lower for w in ("captura de pantalla", "screenshot", "toma una captura", "captura la pantalla", "foto de la pantalla")):
            return "take_screenshot", {"accion": "capturar"}, False

        # 4.6 Patrones de Operaciones sobre Archivos y Carpetas
        if any(w in lower for w in ("abre la carpeta", "abrir la carpeta", "abre el directorio", "abrir el directorio", "abre el explorador en", "abrir el explorador en")) or (
            ("abre " in lower or "abrir " in lower) and ("carpeta" in lower or "directorio" in lower)
        ):
            folder_m = re.search(r'["\']([^"\']+)["\']', text)
            folder_path = folder_m.group(1).strip() if folder_m else re.sub(r"^(jessyca,?\s*)?(abre|abrir)\s+(la\s+carpeta|el\s+directorio|el\s+explorador)?\s*(en|de)?\s*", "", text, flags=re.IGNORECASE).strip()
            return "open_folder", {"ruta_carpeta": folder_path, "app_name": "explorer"}, False

        if any(w in lower for w in ("crea una carpeta", "crear una carpeta", "crea la carpeta", "crear la carpeta", "nueva carpeta", "crea un directorio", "crear un directorio")):
            m_named_in = re.search(r"(?:llamada|llamado|con\s+nombre)\s+[\"']?([^\"'\s]+)[\"']?\s+en\s+[\"']?([^\"'\r\n]+)[\"']?", text, flags=re.IGNORECASE)
            if m_named_in:
                full_p = os.path.join(m_named_in.group(2).strip().strip("\"'"), m_named_in.group(1).strip())
                return "create_folder", {"ruta": full_p}, False
            p_m = re.search(r'["\']([^"\']+)["\']', text)
            full_p = p_m.group(1).strip() if p_m else re.sub(r"^(jessyca,?\s*)?(crea|crear)\s+(una\s+carpeta|la\s+carpeta|un\s+directorio|el\s+directorio)?\s*", "", text, flags=re.IGNORECASE).strip()
            return "create_folder", {"ruta": full_p}, False

        if any(w in lower for w in ("lista los archivos", "listar los archivos", "listar archivos", "lista archivos", "muestra los archivos", "mostrar archivos", "qué archivos hay", "que archivos hay", "contenido de la carpeta")):
            p_m = re.search(r'["\']([^"\']+)["\']', text)
            dir_path = p_m.group(1).strip() if p_m else re.sub(r"^(jessyca,?\s*)?(lista|listar|muestra|mostrar)\s+(los\s+archivos|archivos|el\s+contenido)?\s*(en|de|del)?\s*", "", text, flags=re.IGNORECASE).strip()
            return "list_files", {"ruta_carpeta": dir_path or "."}, False

        if any(w in lower for w in ("metadatos del archivo", "metadatos de", "consulta los metadatos", "consultar metadatos", "propiedades del archivo", "detalles del archivo")):
            p_m = re.search(r'["\']([^"\']+)["\']', text)
            file_p = p_m.group(1).strip() if p_m else re.sub(r"^(jessyca,?\s*)?(consulta|consultar|muestra|ver)?\s*(los\s+metadatos|metadatos|propiedades|detalles)?\s*(del?\s+archivo|de|del)?\s*", "", text, flags=re.IGNORECASE).strip()
            return "file_metadata", {"ruta": file_p}, False

        # 4.5.0 Patrones de Autorización y Revocación de Carpetas (grant_scope / revoke_scope)
        if any(w in lower for w in (
            "revoca el acceso a la carpeta", "revocar el acceso a la carpeta",
            "revoca el acceso a", "revocar el acceso a",
            "revoca el acceso", "revocar el acceso",
            "revoca los permisos de carpeta", "revocar los permisos de carpeta",
            "revoca los permisos", "revocar los permisos",
            "revoca permisos", "revocar permisos",
            "revoca el alcance", "revocar el alcance",
            "desautoriza la carpeta", "desautorizar la carpeta",
            "desautoriza el acceso", "desautorizar el acceso",
            "quitar acceso a la carpeta", "quitar acceso",
        )):
            return "revoke_folder_access", {}, False

        if any(w in lower for w in (
            "autoriza la carpeta", "autorizar la carpeta", "autoriza el directorio", "autorizar el directorio",
            "autoriza carpeta", "autorizar carpeta", "concede acceso a la carpeta", "conceder acceso a la carpeta",
            "concede acceso a", "conceder acceso a", "permite acceso a la carpeta", "permitir acceso a la carpeta",
            "permite acceso a", "permitir acceso a", "autoriza acceso a", "autorizar acceso a",
            "dar acceso a la carpeta", "dar acceso a",
        )):
            folder_m = re.search(r'["\']([^"\']+)["\']', text)
            if folder_m:
                folder_path = folder_m.group(1).strip()
            else:
                m_path = re.search(r'([a-zA-Z]:\\[^\r\n"\'\s]+|[a-zA-Z]:/[^\r\n"\'\s]+|(?:\.{1,2}[/\\]|[/\\])[^\r\n"\'\s]+)', text)
                if m_path:
                    folder_path = m_path.group(1).strip()
                else:
                    folder_path = re.sub(
                        r"^(?:jessyca,?\s*|jessica,?\s*)?(?:autoriza(?:r)?|concede(?:r)?\s+acceso\s+a|permite(?:r)?\s+acceso\s+a|dar\s+acceso\s+a)\s*(?:la\s+carpeta|el\s+directorio|carpeta|directorio)?\s*",
                        "",
                        text,
                        flags=re.IGNORECASE,
                    ).strip()

            folder_path = folder_path.strip("\"'").rstrip(".")
            if not folder_path:
                msg_err = "¿Qué carpeta deseas autorizar?"
                return "grant_folder_access", {"error": "missing_folder", "immediate_response": msg_err}, True

            p_cand = Path(folder_path).resolve()
            if not p_cand.exists() or not p_cand.is_dir():
                msg_nf = f"La carpeta '{folder_path}' no existe o no es un directorio válido."
                return "grant_folder_access", {"error": "folder_not_found", "immediate_response": msg_nf}, False

            from skills.files_skills import _is_path_critical
            if _is_path_critical(str(p_cand)):
                msg_crit = f"Acceso denegado: No se permite autorizar carpetas críticas del sistema ({p_cand})."
                return "grant_folder_access", {"error": "critical_path", "immediate_response": msg_crit}, False

            return "grant_folder_access", {"ruta_carpeta": str(p_cand)}, False

        # 4.5.1 Patrones de Operaciones Documentales Estructuradas (Word, Excel, PowerPoint, PDF)
        if (
            any(w in lower for w in ("resumen del documento", "resume el documento", "resumir el documento", "sintetiza el documento", "resume un documento", "resume el archivo", "resumen de un documento", "resume documento"))
            or (("resume " in lower or "resumir " in lower or "sintetiza " in lower) and any(ext in lower for ext in (".docx", ".xlsx", ".pptx", ".pdf", ".txt", ".md", "documento", "archivo", "informe", "reporte")))
        ):
            m_path = re.search(r'["\']([^"\']+)["\']', text)
            if m_path:
                doc_path = m_path.group(1).strip()
            else:
                doc_path = re.sub(r"^(?:jessyca,?\s*|jessica,?\s*)?(?:resume|resumir|sintetiza|sintetizar|resumen\s+de(?:l)?)\s*(?:el\s*documento|un\s*documento|el\s*archivo|un\s*archivo|documento|archivo)?\s*", "", text, flags=re.IGNORECASE).strip()
            doc_path = doc_path.strip("\"'").rstrip(".")

            is_generic = not doc_path or doc_path.lower() in ("el documento", "un documento", "documento", "el archivo", "un archivo", "archivo", "su contenido", "el contenido")
            if is_generic:
                candidates = self._discover_candidate_documents(session_id)
                if not candidates:
                    msg_0 = "No se encontraron documentos candidatos para resumir en el entorno de trabajo."
                    return "summarize_document", {"error": "no_candidates", "immediate_response": msg_0}, False
                elif len(candidates) == 1:
                    return "summarize_document", {"ruta": candidates[0]}, False
                else:
                    cand_lines = "\n".join(f"{i+1}. {os.path.basename(c)}" for i, c in enumerate(candidates[:5]))
                    clarif_msg = f"Encontré varios documentos candidatos. ¿Cuál deseas resumir?\n{cand_lines}"
                    session_obj = self.context_manager.get_or_create_session(session_id)
                    session_obj.set_pending_question(
                        question=clarif_msg,
                        intent="summarize_document",
                        expected_slot="document_selection",
                        partial_parameters={"candidates": candidates},
                    )
                    return "summarize_document", {"immediate_response": clarif_msg, "candidates": candidates, "requires_clarification": True}, True
            else:
                # Comprobar si la ruta indicada existe
                if not os.path.exists(doc_path):
                    msg_nf = f"El documento '{doc_path}' no existe o ya no está disponible."
                    return "summarize_document", {"error": "file_not_found", "immediate_response": msg_nf}, False

                # Comprobar autorización (existencia != autorización)
                from core.documents.summarizer import check_document_authorization
                sess_obj = self.context_manager.get_session(session_id)
                sess_root = getattr(sess_obj, "trusted_root", None) if sess_obj else None
                is_auth, msg_sec = check_document_authorization(doc_path, trusted_root=sess_root)
                if not is_auth:
                    return "summarize_document", {"error": "access_denied", "immediate_response": msg_sec}, False

                return "summarize_document", {"ruta": doc_path}, False

        if (
            any(w in lower for w in ("crea un documento", "crear un documento", "crea una hoja", "crear una hoja", "crea un excel", "crear un excel", "crea un word", "crear un word", "crea una presentación", "crear una presentacion", "crea un powerpoint", "crear un powerpoint"))
            or (("crea " in lower or "crear " in lower) and any(ext in lower for ext in (".docx", ".xlsx", ".pptx", "word", "excel", "powerpoint", "diapositiva", "hoja de cálculo", "hoja de calculo")))
        ):
            formato = "markdown"
            if any(k in lower for k in ("word", ".docx")):
                formato = "docx"
            elif any(k in lower for k in ("excel", ".xlsx", "hoja de cálculo", "hoja de calculo")):
                formato = "xlsx"
            elif any(k in lower for k in ("powerpoint", ".pptx", "presentación", "presentacion", "diapositiva")):
                formato = "pptx"

            # 1. Extracción de ruta:
            # A) Entre comillas con extensión: "mi archivo con espacios.docx"
            m_quoted_ext = re.search(r'["\']([^"\']+\.(?:docx|xlsx|pptx|txt|md|json))["\']', text, flags=re.IGNORECASE)
            if m_quoted_ext:
                doc_path = m_quoted_ext.group(1).strip()
            else:
                # B) Con prefijo explícito de nombre: llamado / llamada / con nombre
                m_named = re.search(r'(?:llamado|llamada|con\s+nombre)\s+["\']?([a-zA-Z]:[^\r\n"\'\s]+\.(?:docx|xlsx|pptx|txt|md|json)|[^\s"\'\r\n]+\.(?:docx|xlsx|pptx|txt|md|json))["\']?', text, flags=re.IGNORECASE)
                if m_named:
                    doc_path = m_named.group(1).strip()
                else:
                    # C) Ruta o archivo directamente mencionada en el texto (ej. C:\Temp\doc.docx o reporte.docx)
                    m_direct = re.search(r'([a-zA-Z]:\\[^\r\n"\'\s]+\.(?:docx|xlsx|pptx|txt|md|json)|[^\s"\'\r\n]+\.(?:docx|xlsx|pptx|txt|md|json))', text, flags=re.IGNORECASE)
                    if m_direct:
                        doc_path = m_direct.group(1).strip()
                    else:
                        m_any_quoted = re.search(r'["\']([^"\']+)["\']', text)
                        if m_any_quoted and not any(k in m_any_quoted.group(1).lower() for k in ("título", "titulo", "contenido", "datos")):
                            doc_path = m_any_quoted.group(1).strip()
                        else:
                            doc_path = f"documento.{formato}" if formato != "markdown" else "documento.md"

            # 2. Extracción de título
            m_title = re.search(r'(?:con\s+t[ií]tulo|t[ií]tulo)\s+["\']?([^"\'\r\n]+?)["\']?(?:\s+y\s+(?:con\s+)?(?:contenido|datos|subt[ií]tulo)|$)', text, flags=re.IGNORECASE)
            title = m_title.group(1).strip() if m_title else Path(doc_path).stem.replace("_", " ").title()

            # 3. Extracción de contenido o datos suministrados
            m_content = re.search(r'(?:con\s+(?:el\s+)?contenido|con\s+datos|contenido)\s+["\']?([^"\'\r\n]+)["\']?', text, flags=re.IGNORECASE)
            content = m_content.group(1).strip() if m_content else ""

            return "create_document", {"ruta": doc_path, "titulo": title, "formato": formato, "contenido": content}, False

        if any(w in lower for w in ("lee el documento", "leer el documento", "lee el pdf", "leer el pdf", "lee el word", "lee el excel", "contenido del documento")) or (
            any(w in lower for w in ("lee ", "leer ", "muestra ")) and any(ext in lower for ext in (".pdf", ".docx", ".xlsx", ".pptx"))
        ):
            m_path = re.search(r'["\']([^"\']+)["\']', text)
            doc_path = m_path.group(1).strip() if m_path else re.sub(r"^(jessyca,?\s*)?(lee(r)?|muestra)\s*(el\s*documento|el\s*pdf|el\s*word|el\s*excel)?\s*", "", text, flags=re.IGNORECASE).strip()
            doc_path = doc_path.strip("\"'").rstrip(".")
            if doc_path:
                if not os.path.exists(doc_path):
                    msg_nf = f"El documento '{doc_path}' no existe o ya no está disponible."
                    return "read_document", {"error": "file_not_found", "immediate_response": msg_nf}, False

                from core.documents.summarizer import check_document_authorization
                sess_obj = self.context_manager.get_session(session_id)
                sess_root = getattr(sess_obj, "trusted_root", None) if sess_obj else None
                is_auth, msg_sec = check_document_authorization(doc_path, trusted_root=sess_root)
                if not is_auth:
                    return "read_document", {"error": "access_denied", "immediate_response": msg_sec}, False

            return "read_document", {"ruta": doc_path}, False

        if any(w in lower for w in (
            "busca el archivo", "buscar el archivo", "encuentra el archivo", "localiza el archivo",
            "busca archivos", "buscar archivos", "busca los archivos", "buscar los archivos",
            "busca documentos", "buscar documentos", "busca los documentos", "buscar los documentos",
            "encuentra documentos", "localiza documentos", "busca ficheros", "buscar ficheros",
        )):
            m_folder = re.search(r'(?:en(?:\s+(?:la\s+carpeta|el\s+directorio))?|dentro\s+de)\s+["\']?([a-zA-Z]:[^\r\n"\'*?<>|]+|[^\s"\'*?<>|]+)["\']?', text, flags=re.IGNORECASE)
            folder_target = m_folder.group(1).strip().rstrip(".,;:") if m_folder else None

            clean_query = re.sub(r"^(jessyca,?\s*)?(busca(r)?|encuentra|localiza)\s*(el\s*archivo|los\s*archivos|el\s*fichero|los\s*ficheros|el\s*documento|los\s*documentos|documentos|archivos)?\s*", "", text, flags=re.IGNORECASE).strip()
            if m_folder:
                clean_query = re.sub(r'(?:en(?:\s+(?:la\s+carpeta|el\s+directorio))?|dentro\s+de)\s+["\']?[^"\'\r\n]+["\']?', "", clean_query, flags=re.IGNORECASE).strip()

            params_search: dict[str, Any] = {"query": clean_query or "*.*"}
            if folder_target:
                params_search["ruta"] = folder_target
            return "search_file", params_search, False

        if any(w in lower for w in ("lee el archivo", "leer el archivo", "muestra el archivo", "contenido del archivo")) and not any(w in lower for w in ("bloc de notas", "notepad")):
            path = re.sub(r"^(jessyca,?\s*)?(lee(r)?|muestra)\s*(el\s*archivo|el\s*documento|el\s*fichero|el\s*contenido\s*de(l)?)?\s*", "", text, flags=re.IGNORECASE).strip()
            return "read_file", {"ruta": path}, False

        if any(w in lower for w in ("crea un archivo", "crear un archivo", "crea el archivo", "guarda un archivo", "escribe un archivo")):
            m_path = re.search(r"(?:archivo|fichero)\s+(?:llamado\s+|con\s+nombre\s+)?([^\s]+)", text, flags=re.IGNORECASE)
            path = m_path.group(1).strip() if m_path else "nuevo.txt"
            return "create_file", {"ruta": path, "contenido": ""}, False

        if any(w in lower for w in ("copia el archivo", "copiar el archivo", "duplica el archivo")) or (
            ("copia " in lower or "copiar " in lower) and (" a " in lower or " en " in lower)
        ):
            m_q = re.search(r'["\']([^"\']+)["\']\s+(?:a|hacia|en)\s+["\']([^"\']+)["\']', text)
            if m_q:
                return "copy_file", {"origen": m_q.group(1), "destino": m_q.group(2)}, False
            m_files = re.search(r"(?:archivo|fichero)?\s*[\"']?([^\s\"']+)[\"']?\s+(?:a|hacia|en)\s+[\"']?([^\r\n\"']+)[\"']?", text, flags=re.IGNORECASE)
            if m_files:
                return "copy_file", {"origen": m_files.group(1), "destino": m_files.group(2)}, False
            return "copy_file", {"origen": "", "destino": ""}, True

        if any(w in lower for w in ("mueve el archivo", "mover el archivo", "traslada el archivo")) or (
            ("mueve " in lower or "mover " in lower) and (" a " in lower or " en " in lower)
        ):
            m_q = re.search(r'["\']([^"\']+)["\']\s+(?:a|hacia|en)\s+["\']([^"\']+)["\']', text)
            if m_q:
                return "move_file", {"origen": m_q.group(1), "destino": m_q.group(2)}, False
            m_files = re.search(r"(?:archivo|fichero)?\s*[\"']?([^\s\"']+)[\"']?\s+(?:a|hacia|en)\s+[\"']?([^\r\n\"']+)[\"']?", text, flags=re.IGNORECASE)
            if m_files:
                return "move_file", {"origen": m_files.group(1), "destino": m_files.group(2)}, False
            return "move_file", {"origen": "", "destino": ""}, True

        if any(w in lower for w in ("renombra el archivo", "renombrar el archivo", "cambia el nombre del archivo", "renombra", "renombrar")):
            m_q = re.search(r'["\']([^"\']+)["\']\s+(?:a|por|como)\s+["\']([^"\']+)["\']', text)
            if m_q:
                return "rename_file", {"ruta": m_q.group(1), "origen": m_q.group(1), "nuevo_nombre": m_q.group(2)}, False
            m_files = re.search(r"(?:archivo|fichero)?\s*[\"']?([^\s\"']+)[\"']?\s+(?:a|por|como)\s+[\"']?([^\r\n\"']+)[\"']?", text, flags=re.IGNORECASE)
            if m_files:
                return "rename_file", {"ruta": m_files.group(1), "origen": m_files.group(1), "nuevo_nombre": m_files.group(2)}, False
            return "rename_file", {"ruta": "", "nuevo_nombre": ""}, True

        # 4. Patrones de Cerrar Aplicación ("cierra el bloc de notas", "cerrar calculadora", "puedes cerrar")
        if any(w in lower for w in ("cierra", "cerrar", "apaga", "apagar", "deten", "detener", "termina", "terminar", "puedes cerrar", "puédes cerrar")):
            if any(v in lower for v in ("bloc de notas", "block de notas", "blog de notas", "bloc notas", "block notas", "notepad", "el bloc", "el block")):
                return "close_application", {"app_name": "notepad"}, False
            if "calculadora" in lower or "calc" in lower:
                return "close_application", {"app_name": "calc"}, False
            if "navegador" in lower or "chrome" in lower or "edge" in lower or "google" in lower or "youtube" in lower:
                return "close_application", {"app_name": "chrome"}, False
            if "paint" in lower:
                return "close_application", {"app_name": "paint"}, False
            if "cmd" in lower or "terminal" in lower or "consola" in lower:
                return "close_application", {"app_name": "cmd"}, False

            clean_tokens = [
                w for w in re.sub(r"[^\w\s]", "", lower).split()
                if w not in ("cierra", "cerrar", "apaga", "apagar", "el", "la", "los", "las", "un", "una",
                             "por", "favor", "jessyca", "jessica", "gracias", "puedes", "puédes")
            ]
            if not clean_tokens:
                return "close_application", {}, True
            return "close_application", {"app_name": " ".join(clean_tokens)}, False

        # 5. Patrones de Investigación / Multi-paso ("investiga este tema", "analiza...")
        if any(w in lower for w in ("investiga", "investigar", "informe", "reporte", "analiza", "analizar")):
            topic = re.sub(r"^(jessyca,?\s*)?(investiga(r)?|analiza(r)?)\s*(sobre|este|el|esta)?\s*(tema)?\s*", "", lower).strip()
            return "multistep_research", {"topic": topic or "tecnología"}, False

        # 6. Patrones de Búsqueda Web
        if any(w in lower for w in ("busca", "buscar", "encuentra", "localiza")):
            if "internet" in lower or "web" in lower or "google" in lower or "en línea" in lower or "en linea" in lower:
                query = re.sub(r"^(jessyca,?\s*)?(busca(r)?\s*(en|por)?\s*(internet|la web|google|en línea|en linea)\s*(sobre|de)?\s*)", "", lower).strip()
                return "browser_search", {"query": query or "búsqueda"}, False

            # Si especifica archivo o extensión común, va a búsqueda de archivos
            if any(ext in lower for ext in (".txt", ".pdf", ".docx", ".xlsx", ".py", ".md", ".json", "archivo", "fichero")):
                query = re.sub(r"^(jessyca,?\s*)?(busca(r)?\s*(el|los|un)?\s*(archivo|fichero)?\s*)", "", lower).strip()
                return "search_file", {"query": query or "*.*"}, False

            # Busca sin calificador de internet: prácticamente siempre es una búsqueda web
            query = re.sub(r"^(jessyca,?\s*)?(busca(r)?\s*(en|por)?\s*(física|cuántica|cuánticó)?\s*)", "", lower).strip()
            query = re.sub(r"^(jessyca,?\s*)?(busca(r)?\s*(mis|los|el|la)?\s*)", "", lower).strip()
            if any(academic in lower for academic in ("física", "fisica", "cuántica", "cuantica", "matemática", "matematica",
                                                      "historia", "ciencia", "tecnología", "tecnologia")):
                return "browser_search", {"query": query or lower}, False
            return "browser_search", {"query": query or "documentos"}, False

        # 7. Fallback General / Asistente
        return "general_query", {"query": text}, False

    def _discover_candidate_documents(self, session_id: str) -> list[str]:
        """Descubre documentos candidatos en sesión sin inventar archivos del repositorio."""
        session_obj = self.context_manager.get_session(session_id)
        if session_obj:
            active_doc = session_obj.get_context("active_document") or session_obj.get_context("last_summarized_document")
            if active_doc and os.path.exists(str(active_doc)):
                return [str(active_doc)]

            # Candidatos descubiertos o provistos en contexto de sesión
            ctx_cands = session_obj.get_context("candidate_documents")
            if ctx_cands and isinstance(ctx_cands, list):
                valid_ctx = [str(c) for c in ctx_cands if os.path.exists(str(c))]
                if valid_ctx:
                    return valid_ctx

        return []

    def _select_model_for_intent(self, intent: str) -> str:
        """Selecciona el modelo óptimo automáticamente según la intención."""
        if intent in ("multistep_research", "complex_reasoning", "technical_analysis"):
            return "gemma4:e4b"
        if intent in (
            "open_application", "close_application", "type_text", "search_file",
            "browser_search", "play_random_video", "control_audio", "control_clipboard",
            "send_notification", "get_display_info", "take_screenshot", "read_file",
            "create_file", "copy_file", "move_file", "rename_file", "create_folder",
            "list_files", "file_metadata", "open_folder",
        ):
            return "llama3.2"
        return "llama3.1"

    def _select_agent_for_intent(self, intent: str) -> str:
        """Selecciona el agente especialista responsable."""
        agent_map = {
            "open_application": "desktop_agent",
            "open_folder": "desktop_agent",
            "close_application": "desktop_agent",
            "type_text": "desktop_agent",
            "computer_use": "desktop_agent",
            "mouse_click": "desktop_agent",
            "play_random_video": "desktop_agent",
            "control_audio": "system_agent",
            "control_clipboard": "desktop_agent",
            "send_notification": "desktop_agent",
            "get_display_info": "system_agent",
            "take_screenshot": "desktop_agent",
            "search_file": "file_agent",
            "read_file": "file_agent",
            "create_file": "file_agent",
            "copy_file": "file_agent",
            "move_file": "file_agent",
            "rename_file": "file_agent",
            "create_folder": "file_agent",
            "list_files": "file_agent",
            "file_metadata": "file_agent",
            "delete_file": "file_agent",
            "open_browser": "browser_agent",
            "browser_open": "browser_agent",
            "browser_search": "browser_agent",
            "youtube_search": "browser_agent",
            "youtube_play": "browser_agent",
            "search_and_play": "browser_agent",
            "follow_link": "browser_agent",
            "browser_navigate": "browser_agent",
            "browser_read": "browser_agent",
            "extract_content": "browser_agent",
            "browser_download": "browser_agent",
            "download_file": "browser_agent",
            "media_control": "browser_agent",
            "pause_media": "browser_agent",
            "resume_media": "browser_agent",
            "multistep_research": "research_coordinator_agent",
            "general_query": "general_assistant_agent",
            "create_document": "document_agent",
            "read_document": "document_agent",
            "summarize_document": "document_agent",
            "convert_document": "document_agent",
            "create_diagram": "architecture_agent",
            "technical_diagram": "architecture_agent",
            "remember_fact": "memory_agent",
            "recall_fact": "memory_agent",
        }
        return agent_map.get(intent, "system_agent")

    def _select_skill_for_intent(self, intent: str) -> str:
        """Selecciona la skill resolutora."""
        skill_map = {
            "open_application": "windows.apps@1.0.0",
            "open_folder": "windows.apps@1.0.0",
            "close_application": "windows.apps@1.0.0",
            "type_text": "windows.apps@1.0.0",
            "computer_use": "windows.computer_use@1.0.0",
            "mouse_click": "windows.computer_use@1.0.0",
            "desktop_interaction": "windows.computer_use@1.0.0",
            "play_random_video": "windows.media@1.0.0",
            "control_audio": "windows.audio@1.0.0",
            "control_clipboard": "windows.clipboard@1.0.0",
            "send_notification": "windows.notifications@1.0.0",
            "get_display_info": "windows.display@1.0.0",
            "take_screenshot": "windows.screenshot@1.0.0",
            "search_file": "files.search@1.0.0",
            "read_file": "files.read@1.0.0",
            "create_file": "files.create@1.0.0",
            "copy_file": "files.copy@1.0.0",
            "move_file": "files.move@1.0.0",
            "rename_file": "files.rename@1.0.0",
            "create_folder": "files.create_folder@1.0.0",
            "list_files": "files.list@1.0.0",
            "file_metadata": "files.metadata@1.0.0",
            "delete_file": "files.delete@1.0.0",
            "open_browser": "browser.open@1.0.0",
            "browser_open": "browser.open@1.0.0",
            "browser_search": "browser.search@1.0.0",
            "youtube_search": "browser.youtube@1.0.0",
            "youtube_play": "browser.youtube@1.0.0",
            "search_and_play": "browser.youtube@1.0.0",
            "follow_link": "browser.navigate@1.0.0",
            "browser_navigate": "browser.navigate@1.0.0",
            "browser_read": "browser.read@1.0.0",
            "extract_content": "browser.read@1.0.0",
            "browser_download": "browser.download@1.0.0",
            "download_file": "browser.download@1.0.0",
            "media_control": "browser.youtube@1.0.0",
            "pause_media": "browser.youtube@1.0.0",
            "resume_media": "browser.youtube@1.0.0",
            "multistep_research": "research_skill_pipeline@1.0.0",
            "create_document": "documents.create@1.0.0",
            "read_document": "documents.read@1.0.0",
            "summarize_document": "documents.summarize@1.0.0",
            "convert_document": "documents.convert@1.0.0",
            "create_diagram": "tools.archify@2.0.0",
            "technical_diagram": "tools.archify@2.0.0",
            "grant_folder_access": "security.permissions@1.0.0",
            "revoke_folder_access": "security.permissions@1.0.0",
        }
        return skill_map.get(intent, "core.assistant@1.0.0")

    def _map_intent_to_tool(self, intent: str) -> str:
        """Mapea una intención de alto nivel a una herramienta gobernada."""
        tool_map = {
            "open_application": "windows.launch_app",
            "open_folder": "windows.launch_app",
            "close_application": "windows.close_app",
            "type_text": "windows.type_text",
            "play_random_video": "windows.media.play",
            "control_audio": "windows.audio",
            "control_clipboard": "windows.clipboard",
            "send_notification": "windows.notification",
            "get_display_info": "windows.display",
            "take_screenshot": "windows.screenshot",
            "search_file": "filesystem.search_files",
            "read_file": "filesystem.read_file",
            "create_file": "filesystem.create_file",
            "copy_file": "filesystem.copy_file",
            "move_file": "filesystem.move_file",
            "rename_file": "filesystem.rename_file",
            "create_folder": "filesystem.create_folder",
            "list_files": "filesystem.list_files",
            "file_metadata": "filesystem.metadata",
            "delete_file": "filesystem.delete_file",
            "open_browser": "browser.open",
            "browser_open": "browser.open",
            "browser_search": "browser.search",
            "youtube_search": "browser.youtube",
            "youtube_play": "browser.youtube",
            "search_and_play": "browser.youtube",
            "follow_link": "browser.navigate",
            "browser_navigate": "browser.navigate",
            "browser_read": "browser.read",
            "extract_content": "browser.read",
            "browser_download": "browser.download",
            "download_file": "browser.download",
            "media_control": "browser.youtube",
            "pause_media": "browser.youtube",
            "resume_media": "browser.youtube",
            "multistep_research": "multistep.orchestrate",
            "create_document": "documents.create",
            "read_document": "documents.read",
            "summarize_document": "documents.summarize",
            "convert_document": "documents.convert",
            "grant_folder_access": "security.grant_scope",
            "revoke_folder_access": "security.revoke_scope",
        }
        return tool_map.get(intent, "system.execute")

    def _evaluate_action_security(self, tool_name: str, parameters: dict[str, Any]) -> SecurityLevel:
        """Evalúa el nivel de riesgo de seguridad para la acción."""
        if "delete" in tool_name or "kill" in tool_name or "format" in tool_name:
            return SecurityLevel.CRITICAL if "system" in str(parameters).lower() else SecurityLevel.MEDIUM
        if "grant_scope" in tool_name:
            return SecurityLevel.MEDIUM
        return SecurityLevel.SAFE

    def _format_response_text(
        self,
        intent: str,
        sys_resp: SystemResponse,
        params: dict[str, Any],
        execution_result: Any | None = None,
        session_id: str | None = None,
    ) -> str:
        """Formatea una respuesta amigable, precisa y no falaz delegando en ResponseSynthesizer."""
        return self.response_synthesizer.format_response_text(
            intent=intent,
            sys_resp=sys_resp,
            params=params,
            execution_result=execution_result,
            session_id=session_id,
            conversational_handler=self.conversational_handler,
            context_manager=self.context_manager,
        )

    # ── MÉTODOS DE CONTROL DEL SISTEMA ──

    def cancel(self, request_id: str | None = None, reason: str = "Cancelado por el usuario") -> None:
        """Cancela una operación en curso o todas las tareas activas."""
        with self._lock:
            if request_id and request_id in self._active_tokens:
                self._active_tokens[request_id].cancel(reason=reason)
            else:
                for token in self._active_tokens.values():
                    token.cancel(reason=reason)
        logger.info(f"[LOCAL AGENT] Cancelación solicitada: {reason}")

    def emergency_stop(self) -> None:
        """Activa inmediatamente la Parada de Emergencia global."""
        self.emergency_stop_mgr.trigger_stop(
            reason="Parada de Emergencia activada desde JESSYCA Local Agent",
            source="local_agent",
        )

    def get_latest_metrics(self) -> LocalAgentMetrics:
        """Obtiene las métricas de rendimiento más recientes."""
        with self._lock:
            return self._latest_metrics

    def reset(self) -> None:
        """Limpia el estado interno para aislamiento en pruebas."""
        with self._lock:
            self.context_manager.reset_all()
            self._active_tokens.clear()
            self._latest_metrics = LocalAgentMetrics()


def get_jessyca_local_agent() -> JessycaLocalAgent:
    """Acceso helper al singleton global de JessycaLocalAgent."""
    return JessycaLocalAgent.get_instance()
