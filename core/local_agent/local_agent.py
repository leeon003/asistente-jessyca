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

import re
import threading
import time
from collections.abc import Callable
from typing import Any, ClassVar

from core.audit_logger import AuditLogger, get_audit_logger
from core.cancellation import CancellationToken
from core.collaboration.collaboration_engine import CollaborationEngine
from core.control_plane.models import AgentBudget
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.interaction.interaction_models import (
    ConfirmationPrompt,
)
from core.interaction.trusted_interaction_engine import TrustedInteractionEngine
from core.llm.model_router import ModelRouter, get_model_router
from core.local_agent.conversation_context import ConversationContextManager
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    InputModality,
    JessycaRequest,
    JessycaResponse,
    LocalAgentMetrics,
)
from core.local_agent.multimodal_interface import MultimodalProcessor
from core.local_agent.voice_interface import LocalVoiceInterface
from core.logger import get_logger
from core.permission_manager import PermissionManager
from core.risk_engine import RiskEngine
from core.security_architecture import SecurityLevel
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
    ) -> None:
        self._lock = threading.RLock()
        self.emergency_stop_mgr = emergency_stop or get_emergency_stop_manager()
        self.audit_logger = audit_logger or get_audit_logger()
        self.risk_engine = risk_engine or RiskEngine()
        self.permission_manager = permission_manager or PermissionManager()
        self.model_router = model_router or get_model_router()
        self.skill_manager = skill_manager or get_skill_manager()
        self.collaboration_engine = collaboration_engine or CollaborationEngine()
        self.interaction_engine = interaction_engine or TrustedInteractionEngine(emergency_stop=self.emergency_stop_mgr)
        self.context_manager = context_manager or ConversationContextManager()
        self.voice_interface = voice_interface or LocalVoiceInterface(emergency_stop=self.emergency_stop_mgr)
        self.coordinator = coordinator or SystemCoordinator4(
            collaboration_engine=self.collaboration_engine,
            emergency_stop=self.emergency_stop_mgr,
            audit_logger=self.audit_logger,
        )

        self._active_tokens: dict[str, CancellationToken] = {}
        self._latest_metrics: LocalAgentMetrics = LocalAgentMetrics()

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
    ) -> JessycaResponse:
        """Punto de entrada universal y unificado para cualquier interacción con JESSYCA."""
        if isinstance(request, str):
            req = JessycaRequest(user_input=request, modality=InputModality.TEXT)
        else:
            req = request

        return self._execute_unified_pipeline(
            req=req,
            cancellation_token=cancellation_token,
            user_confirmation_callback=user_confirmation_callback,
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
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                return JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=False,
                    status=AgentExecutionState.STOPPED,
                    response_text="Parada de Emergencia activa. Operación bloqueada.",
                    security_verdict="DENY",
                    error="Emergency Stop active",
                    metrics=metrics,
                )

            if token.is_cancelled:
                metrics.interruption_handled = True
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                return JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=False,
                    status=AgentExecutionState.INTERRUPTED,
                    response_text="Operación cancelada por el usuario.",
                    error="Operation cancelled",
                    metrics=metrics,
                )

            # ── PASO 1: PROCESAMIENTO MULTIMODAL & UNTRUSTED DATA SANITIZATION ──
            is_mm_valid, mm_err, mm_context = MultimodalProcessor.process_request(req)
            if not is_mm_valid:
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                return JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=False,
                    status=AgentExecutionState.FAILED,
                    response_text=f"Entrada multimodal inválida: {mm_err}",
                    error=mm_err,
                    metrics=metrics,
                )

            user_text = req.user_input.strip()

            # ── PASO 1.5: QUALITY GATE Y COMPLETITUD DE TRANSCRIPCIÓN ──
            from core.local_agent.quality_analyzer import (
                IntentCompleteness,
                IntentCompletenessChecker,
                TranscriptQualityAnalyzer,
            )

            # Analizar calidad de transcripción
            q_analyzer = TranscriptQualityAnalyzer()
            q_res = q_analyzer.analyze(user_text)
            if not q_res.is_acceptable:
                clarification_msg = q_res.suggested_prompt or "No te entendí bien. ¿Puedes repetirlo?"
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                return JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=False,
                    status=AgentExecutionState.AWAITING_CLARIFICATION,
                    response_text=clarification_msg,
                    spoken_text=clarification_msg,
                    intent="unknown",
                    requires_clarification=True,
                    clarification_question=clarification_msg,
                    metrics=metrics,
                )

            # Analizar completitud de la orden
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
                return JessycaResponse(
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

            # Usar texto normalizado limpio
            user_text = q_res.normalized_text

            # ── PASO 1.8: DETECCIÓN DE CIERRE DE CONVERSACIÓN ──
            if user_text.lower() in ("adiós", "adios", "salir", "exit", "quit", "cerrar conversación", "cerrar sesion", "cerrar sesión", "hasta luego", "bye", "terminar"):
                self.context_manager.close_session(req.session_id)
                closing_text = "¡Hasta luego! Que tengas un excelente día."
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                return JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=True,
                    status=AgentExecutionState.COMPLETED,
                    response_text=closing_text,
                    spoken_text=closing_text,
                    intent="close_conversation",
                    metrics=metrics,
                )

            # ── PASO 2: ANÁLISIS DE INTENCIÓN Y RESOLUCIÓN DE CONTEXTO ──
            t_intent_0 = time.perf_counter()
            intent, extracted_params, is_ambiguous = self._resolve_intent_and_slots(user_text, req.session_id)
            metrics.intent_latency_ms = (time.perf_counter() - t_intent_0) * 1000

            # Manejo de cancelación conversacional o interrupción ("Olvídalo", "Déjame hablar", "Pausa")
            if intent in ("cancel_task", "interrupt_assistant"):
                default_msg = "Te escucho, dime." if intent == "interrupt_assistant" else "Entendido, operación cancelada."
                cancel_msg = extracted_params.get("immediate_response") or default_msg
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                return JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=True,
                    status=AgentExecutionState.COMPLETED,
                    response_text=cancel_msg,
                    spoken_text=cancel_msg,
                    intent=intent,
                    metrics=metrics,
                )

            # Manejo de respuesta inmediata de diálogo contextual (ej. "¿Qué números quieres sumar?", "¿Para qué día?", "¿Qué quieres incluir?")
            if (intent in ("math_sum", "write_list") or (intent == "set_alarm" and is_ambiguous)) and extracted_params.get("immediate_response") and is_ambiguous:
                clarification_msg = extracted_params["immediate_response"]
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                return JessycaResponse(
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
                )

            # Manejo de diálogo contextual completado (ej. resultado matemático, alarma configurada, respuesta afirmativa, lista completada, consulta general)
            if (intent in ("math_calculation", "set_alarm", "write_list") or (intent == "general_query" and extracted_params.get("immediate_response"))) and extracted_params.get("immediate_response") and not is_ambiguous:
                resp_msg = extracted_params["immediate_response"]
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                return JessycaResponse(
                    request_id=req.request_id,
                    session_id=req.session_id,
                    success=True,
                    status=AgentExecutionState.COMPLETED,
                    response_text=resp_msg,
                    spoken_text=resp_msg,
                    intent=intent,
                    tools_executed=(),
                    metrics=metrics,
                )

            # Manejo de Aclaración si la intención es ambigua o faltan parámetros críticos
            if is_ambiguous:
                clarification_msg = extracted_params.get("immediate_response") or "¿Podrías especificar qué archivo o aplicación deseas que revise?"
                self.context_manager.set_pending_clarification(
                    session_id=req.session_id,
                    question=clarification_msg,
                    expected_slot="target",
                    original_intent=intent,
                )
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                return JessycaResponse(
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
                )

            # ── PASO 3: ENRUTAMIENTO DE MODELO Y AGENTE ──
            t_model_0 = time.perf_counter()
            # Selección automática de modelo según la complejidad del intent
            selected_model = self._select_model_for_intent(intent)
            metrics.model_inference_latency_ms = (time.perf_counter() - t_model_0) * 1000

            t_agent_0 = time.perf_counter()
            selected_agent = self._select_agent_for_intent(intent)
            selected_skill = self._select_skill_for_intent(intent)
            metrics.agent_routing_latency_ms = (time.perf_counter() - t_agent_0) * 1000

            # ── PASO 4: PLANIFICACIÓN AUTOMÁTICA Y SKILL GRAPH ──
            t_plan_0 = time.perf_counter()
            selected_graph = f"graph_{intent}"
            metrics.planning_latency_ms = (time.perf_counter() - t_plan_0) * 1000

            # ── PASO 5: EVALUACIÓN DE SEGURIDAD Y CONFIRMACIÓN HUMANA ──
            proposed_tool = self._map_intent_to_tool(intent)
            sec_level = self._evaluate_action_security(proposed_tool, extracted_params)

            # Si es acción de riesgo o peligrosa -> Exigir confirmación
            if sec_level in (SecurityLevel.MEDIUM, SecurityLevel.HIGH, SecurityLevel.CRITICAL) or "delete" in proposed_tool or "kill" in proposed_tool:
                # Comprobar si ya fue confirmada contextualmente en este turno
                if extracted_params.get("is_confirmed") is True:
                    user_approved = True
                else:
                    confirm_prompt = ConfirmationPrompt(
                        task_id=req.request_id,
                        action_name=proposed_tool,
                        relevant_parameters=extracted_params,
                        risk_level=sec_level,
                        objective=f"Confirmación requerida para ejecutar acción sensible '{proposed_tool}'.",
                    )
                    self.interaction_engine.register_confirmation(confirm_prompt)

                    user_approved = False
                    if user_confirmation_callback is not None:
                        try:
                            user_approved = user_confirmation_callback(confirm_prompt)
                        except Exception as ex:
                            logger.error(f"Error en callback de confirmación: {ex}")
                            user_approved = False

                if not user_approved:
                    confirm_text = f"Detecté una acción sensible: '{proposed_tool}'. ¿Confirmas su ejecución?"
                    session = self.context_manager.get_or_create_session(req.session_id)
                    session.set_pending_confirmation(
                        intent=intent,
                        tool=proposed_tool,
                        parameters=extracted_params,
                        prompt=confirm_text,
                        security_level=sec_level.value,
                    )
                    metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                    return JessycaResponse(
                        request_id=req.request_id,
                        session_id=req.session_id,
                        success=True,
                        status=AgentExecutionState.AWAITING_CONFIRMATION,
                        response_text=confirm_text,
                        spoken_text=confirm_text,
                        intent=intent,
                        selected_model=selected_model,
                        selected_agent=selected_agent,
                        selected_skill=selected_skill,
                        selected_graph=selected_graph,
                        security_level=sec_level,
                        requires_confirmation=True,
                        metrics=metrics,
                    )

            # ── PASO 6: EJECUCIÓN SEGURA Y VERIFICACIÓN POST-EJECUCIÓN REAL ──
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

            # 6.1 Ejecución directa verificada de aplicaciones de Windows
            elif intent in ("open_application", "close_application"):
                accion_app = "abrir" if intent == "open_application" else "cerrar"
                app_name = extracted_params.get("app_name", "notepad")
                skill_res = self.skill_manager.execute_skill(
                    "windows.apps",
                    parameters={"accion": accion_app, "nombre_app": app_name},
                )

                raw_evidence = skill_res.output.get("evidence") if isinstance(skill_res.output, dict) else None
                evidence_obj = None
                if raw_evidence:
                    evidence_obj = ExecutionEvidence(
                        verification_type=raw_evidence.get("verification_type", "process"),
                        target=raw_evidence.get("target", app_name),
                        is_verified=bool(raw_evidence.get("is_verified", False)),
                        details=raw_evidence.get("details", {}),
                    )

                is_skill_ok = bool(skill_res.success and isinstance(skill_res.output, dict) and skill_res.output.get("exito"))
                is_verif_ok = bool(evidence_obj and evidence_obj.is_verified)

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

                execution_result = ExecutionResult(
                    status=exec_status,
                    action=intent,
                    target=app_name,
                    message=skill_res.output.get("mensaje") if isinstance(skill_res.output, dict) else skill_res.error,
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

            # 6.2 Flujo Coordinado Multidimensional
            else:
                sys_resp = self.coordinator.execute_user_request(
                    user_input=user_text,
                    parameters=extracted_params,
                    budget=AgentBudget(max_iterations=5, global_timeout_seconds=30.0),
                    correlation_id=req.request_id,
                )
                exec_success = sys_resp.success

            metrics.execution_latency_ms = (time.perf_counter() - t_exec_0) * 1000

            # ── PASO 7: CONSOLIDACIÓN DE RESPUESTA Y ACTUALIZACIÓN CONTEXTUAL ──
            if intent == "math_calculation" and extracted_params.get("immediate_response"):
                response_text = extracted_params["immediate_response"]
            else:
                response_text = self._format_response_text(intent, sys_resp, extracted_params, execution_result=execution_result)

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

            return JessycaResponse(
                request_id=req.request_id,
                session_id=req.session_id,
                success=exec_success,
                status=AgentExecutionState.COMPLETED if exec_success else AgentExecutionState.FAILED,
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
            )

        finally:
            with self._lock:
                self._active_tokens.pop(req.request_id, None)

    # ── MÉTODOS AUXILIARES DE RESOLUCIÓN Y ENRUTAMIENTO ──

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
            return pending["original_intent"], {"target": text, "app_name": text, "query": text}, False

        # 2. Patrones Peligrosos / Sensibles ("elimina archivo", "borrar")
        if any(w in lower for w in ("elimina", "eliminar", "borra", "borrar", "destruye")):
            path = re.sub(r"^(jessyca,?\s*)?(elimina(r)?|borra(r)?)\s*(el\s*archivo\s*(temporal)?)?\s*", "", lower).strip()
            return "delete_file", {"path": path or "C:\\Data\\temp.tmp"}, False

        # 3. Patrones de Abrir Aplicación ("abre el bloc de notas", "iniciar calculadora")
        if any(w in lower for w in ("abre", "abrir", "inicia", "iniciar", "ejecuta", "lanza")):
            if "bloc de notas" in lower or "notepad" in lower:
                return "open_application", {"app_name": "notepad"}, False
            if "calculadora" in lower or "calc" in lower:
                return "open_application", {"app_name": "calc"}, False
            if "navegador" in lower or "chrome" in lower or "edge" in lower:
                return "open_application", {"app_name": "chrome"}, False
            if "paint" in lower:
                return "open_application", {"app_name": "paint"}, False
            if "cmd" in lower or "terminal" in lower or "consola" in lower:
                return "open_application", {"app_name": "cmd"}, False

            clean_tokens = [
                w for w in re.sub(r"[^\w\s]", "", lower).split()
                if w not in ("abre", "abrir", "inicia", "el", "la", "los", "las", "un", "una", "por", "favor", "jessyca", "jessica", "gracias")
            ]
            if not clean_tokens:
                return "open_application", {}, True
            return "open_application", {"app_name": " ".join(clean_tokens)}, False

        # 4. Patrones de Cerrar Aplicación ("cierra el bloc de notas", "cerrar calculadora")
        if any(w in lower for w in ("cierra", "cerrar", "apaga", "apagar", "deten", "detener", "termina", "terminar")):
            if "bloc de notas" in lower or "notepad" in lower:
                return "close_application", {"app_name": "notepad"}, False
            if "calculadora" in lower or "calc" in lower:
                return "close_application", {"app_name": "calc"}, False
            if "navegador" in lower or "chrome" in lower or "edge" in lower:
                return "close_application", {"app_name": "chrome"}, False
            if "paint" in lower:
                return "close_application", {"app_name": "paint"}, False
            if "cmd" in lower or "terminal" in lower or "consola" in lower:
                return "close_application", {"app_name": "cmd"}, False

            clean_tokens = [
                w for w in re.sub(r"[^\w\s]", "", lower).split()
                if w not in ("cierra", "cerrar", "apaga", "apagar", "el", "la", "los", "las", "un", "una", "por", "favor", "jessyca", "jessica", "gracias")
            ]
            if not clean_tokens:
                return "close_application", {}, True
            return "close_application", {"app_name": " ".join(clean_tokens)}, False

        # 5. Patrones de Investigación / Multi-paso ("investiga este tema", "analiza...")
        if any(w in lower for w in ("investiga", "investigar", "informe", "reporte", "analiza", "analizar")):
            topic = re.sub(r"^(jessyca,?\s*)?(investiga(r)?|analiza(r)?)\s*(sobre|este|el|esta)?\s*(tema)?\s*", "", lower).strip()
            return "multistep_research", {"topic": topic or "tecnología"}, False

        # 6. Patrones de Búsqueda Web vs Archivos Locales
        if any(w in lower for w in ("busca", "buscar", "encuentra", "localiza")):
            if "internet" in lower or "web" in lower or "google" in lower:
                query = re.sub(r"^(jessyca,?\s*)?(busca(r)?\s*(en|por)?\s*(internet|la web|google)\s*(sobre|de)?\s*)", "", lower).strip()
                return "browser_search", {"query": query or "IA"}, False

            query = re.sub(r"^(jessyca,?\s*)?(busca(r)?\s*(mis|los|el|la)?\s*)", "", lower).strip()
            return "search_file", {"query": query or "documentos"}, False

        # 7. Fallback General / Asistente
        return "general_query", {"query": text}, False

    def _select_model_for_intent(self, intent: str) -> str:
        """Selecciona el modelo óptimo automáticamente según la intención."""
        if intent in ("multistep_research", "complex_reasoning"):
            return "qwen2.5-coder:7b"
        if intent in ("open_application", "close_application", "search_file", "browser_search"):
            return "llama3.2:3b"
        return "auto-routed"

    def _select_agent_for_intent(self, intent: str) -> str:
        """Selecciona el agente especialista responsable."""
        agent_map = {
            "open_application": "desktop_agent",
            "close_application": "desktop_agent",
            "search_file": "file_agent",
            "browser_search": "browser_agent",
            "multistep_research": "research_coordinator_agent",
            "delete_file": "file_agent",
            "general_query": "general_assistant_agent",
        }
        return agent_map.get(intent, "system_agent")

    def _select_skill_for_intent(self, intent: str) -> str:
        """Selecciona la skill resolutora."""
        skill_map = {
            "open_application": "windows.apps@1.0.0",
            "close_application": "windows.apps@1.0.0",
            "search_file": "files.search@1.0.0",
            "browser_search": "browser.search@1.0.0",
            "multistep_research": "research_skill_pipeline@1.0.0",
            "delete_file": "files.delete@1.0.0",
        }
        return skill_map.get(intent, "core.assistant@1.0.0")

    def _map_intent_to_tool(self, intent: str) -> str:
        """Mapea una intención de alto nivel a una herramienta gobernada."""
        tool_map = {
            "open_application": "windows.launch_app",
            "close_application": "windows.close_app",
            "search_file": "filesystem.search_files",
            "browser_search": "browser.search",
            "multistep_research": "multistep.orchestrate",
            "delete_file": "filesystem.delete_file",
        }
        return tool_map.get(intent, "system.execute")

    def _evaluate_action_security(self, tool_name: str, parameters: dict[str, Any]) -> SecurityLevel:
        """Evalúa el nivel de riesgo de seguridad para la acción."""
        if "delete" in tool_name or "kill" in tool_name or "format" in tool_name:
            return SecurityLevel.CRITICAL if "system" in str(parameters).lower() else SecurityLevel.MEDIUM
        return SecurityLevel.SAFE

    def _format_response_text(
        self,
        intent: str,
        sys_resp: SystemResponse,
        params: dict[str, Any],
        execution_result: Any | None = None,
    ) -> str:
        """Formatea una respuesta amigable, precisa y no falaz."""
        # 1. Si existe un ExecutionResult formal (open/close app, file, etc.)
        if execution_result is not None:
            from core.execution.execution_verifier import ExecutionStatus

            app = params.get("app_name") or params.get("target") or "la aplicación"
            app_lower = str(app).lower()
            if "bloc de notas" in app_lower or "notepad" in app_lower:
                app_display = "el Bloc de notas"
            elif "calculadora" in app_lower or "calc" in app_lower:
                app_display = "la Calculadora"
            elif "chrome" in app_lower:
                app_display = "Google Chrome"
            elif "edge" in app_lower:
                app_display = "Microsoft Edge"
            elif "navegador" in app_lower or "browser" in app_lower:
                app_display = "el navegador"
            elif "paint" in app_lower:
                app_display = "Paint"
            elif "cmd" in app_lower or "terminal" in app_lower:
                app_display = "la consola"
            else:
                app_display = f"'{app}'"

            if execution_result.status == ExecutionStatus.SUCCEEDED:
                if intent == "open_application":
                    return f"Listo, abrí {app_display}."
                elif intent == "close_application":
                    return f"Listo, cerré {app_display}."
                return str(execution_result.message or "Acción completada con éxito.")

            elif execution_result.status == ExecutionStatus.VERIFICATION_FAILED:
                if intent == "open_application":
                    return f"Intenté abrir {app_display}, pero Windows no confirmó que se haya abierto."
                elif intent == "close_application":
                    return f"Intenté cerrar {app_display}, pero no se pudo confirmar el cierre."
                return f"La acción sobre {app_display} no pudo ser verificada en Windows."

            elif execution_result.status == ExecutionStatus.DENIED:
                return "No puedo ejecutar esa acción porque la política de seguridad no la autoriza."
            elif execution_result.status == ExecutionStatus.CANCELLED:
                return "Operación cancelada."
            else:
                return f"No pude completar la acción sobre {app_display}: {execution_result.message or 'Error en la ejecución'}."

        if not sys_resp.success:
            return f"No pude completar la solicitud: {sys_resp.error or 'Error desconocido'}."

        if intent == "search_file":
            query = params.get("query", "los archivos")
            return f"He buscado {query} en tus documentos."
        if intent == "browser_search":
            query = params.get("query", "tu búsqueda")
            return f"He completado la búsqueda sobre '{query}' en el navegador."
        if intent == "multistep_research":
            topic = params.get("topic", "el tema solicitado")
            return f"He investigado sobre '{topic}' y consolidado los resultados."

        # Consultas generales informativas
        if intent == "general_query":
            q_lower = str(params.get("query", "")).lower()
            if any(k in q_lower for k in ("que puedes hacer", "qué puedes hacer", "describe todo", "quien eres", "quién eres", "capacidades", "ayuda")):
                return (
                    "Soy Jessyca, tu asistente local e inteligente para Windows. Puedo abrir y cerrar aplicaciones de escritorio "
                    "(como el Bloc de notas o la Calculadora), buscar y organizar archivos, realizar investigaciones web multi-paso, "
                    "y gestionar tareas del sistema de forma segura."
                )
            if any(k in q_lower for k in ("hola", "buenos dias", "buenas tardes", "buenas noches", "hey")):
                return "¡Hola! Soy Jessyca. ¿En qué te puedo ayudar hoy?"

        return "He completado tu solicitud con éxito."

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
