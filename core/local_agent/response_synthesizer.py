"""Sintetizador y Constructor Canónico de Respuestas de JESSYCA (response_synthesizer.py - Fase 10).

Responsabilidad acotada extraída de JessycaLocalAgent:
1. Construcción determinista y homogénea de instancias `JessycaResponse`.
2. Formateo verídico y no falaz de texto de respuesta según veredictos de ejecución física.
3. Síntesis y normalización de texto hablado (spoken_text / TTS) libre de marcado visual.
4. Cálculo consistente de latencias y metadatos de auditoría/experiencia.

Conserva 100% de compatibilidad con contratos existentes de JessycaResponse.
"""

from __future__ import annotations

import re
import time
from typing import Any

from core.local_agent.local_agent_models import (
    AgentExecutionState,
    JessycaRequest,
    JessycaResponse,
    LocalAgentMetrics,
)
from core.security_architecture import SecurityLevel
from core.system.system_coordinator import SystemResponse


class ResponseSynthesizer:
    """Constructor y formateador desacoplado de respuestas para el Agente Local."""

    def __init__(self) -> None:
        pass

    def synthesize_spoken_text(self, response_text: str | None) -> str:
        """Limpia el texto para habla natural (TTS), eliminando markdown y artefactos visuales."""
        if not response_text:
            return ""
        text = response_text.strip()
        # Eliminar enlaces markdown: [texto](url) -> texto
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        # Eliminar bloques de código o backticks
        text = re.sub(r"```[a-zA-Z]*\n?|```", "", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        # Eliminar asteriscos de negrita/cursiva
        text = re.sub(r"\*{1,3}([^\*]+)\*{1,3}", r"\1", text)
        # Eliminar viñetas markdown
        text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
        # Colapsar espacios múltiples
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def format_response_text(
        self,
        intent: str,
        sys_resp: SystemResponse,
        params: dict[str, Any],
        execution_result: Any | None = None,
        session_id: str | None = None,
        conversational_handler: Any | None = None,
        context_manager: Any | None = None,
    ) -> str:
        """Formatea una respuesta amigable, precisa y no falaz."""
        # 1. Si existe un ExecutionResult formal (open/close app, file, media, etc.)
        if execution_result is not None:
            app = params.get("app_name") or params.get("target") or "la aplicación"
            app_lower = str(app).lower()
            if any(v in app_lower for v in ("bloc de notas", "block de notas", "blog de notas", "bloc notas", "block notas", "notepad")):
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

            st_raw = getattr(execution_result, "status", None)
            st_val = st_raw.value if hasattr(st_raw, "value") else str(st_raw)
            st_upper = st_val.upper()

            if st_upper in ("SUCCEEDED", "SUCCESS"):
                if intent == "open_application":
                    if params.get("text_to_write"):
                        return f"Listo, abrí {app_display} y escribí '{params['text_to_write']}'."
                    return f"Listo, abrí {app_display}."
                elif intent == "type_text":
                    txt_val = params.get("text") or params.get("text_to_write") or ""
                    return f"Listo, escribí '{txt_val}' en {app_display}."
                elif intent == "close_application":
                    return f"Listo, cerré {app_display}."
                elif intent == "play_random_video":
                    return "Claro, ya está reproduciéndose el baile."
                elif intent in ("youtube_play", "search_and_play", "browser_search") and (intent in ("youtube_play", "search_and_play") or params.get("action") == "play"):
                    query_clean = params.get("query") or "la música"
                    return f"Listo, está reproduciendo {query_clean}."
                elif intent in ("open_browser", "browser_open"):
                    site_name = params.get("site") or "el navegador"
                    return f"Listo, abrí {site_name} en el navegador."
                elif intent == "browser_search":
                    query_clean = params.get("query") or "la búsqueda"
                    return f"Listo, busqué '{query_clean}' en el navegador."
                return str(getattr(execution_result, "message", None) or "Acción completada con éxito.")

            elif st_upper in ("UNKNOWN",):
                if intent in ("open_browser", "browser_open"):
                    site_name = params.get("site") or params.get("app_name") or "la página"
                    return f"Intenté abrir {site_name}, pero no pude confirmar que se haya abierto correctamente."
                elif intent == "open_application":
                    return f"Intenté abrir {app_display}, pero no pude confirmar que se haya abierto correctamente."
                elif intent == "close_application":
                    return f"Intenté cerrar {app_display}, pero no pude confirmar el cierre."
                elif intent == "type_text":
                    return f"Intenté escribir en {app_display}, pero no pude confirmar la escritura."
                elif intent == "browser_search":
                    query_clean = params.get("query") or "la búsqueda"
                    return f"Intenté buscar '{query_clean}' en el navegador, pero no pude confirmar que la búsqueda se haya realizado."
                elif intent in ("youtube_play", "search_and_play") or (intent == "browser_search" and params.get("action") == "play"):
                    query_clean = params.get("query") or "la música"
                    return f"Intenté reproducir {query_clean} en YouTube, pero no pude confirmar que la reproducción haya comenzado."
                elif intent == "youtube_search":
                    query_clean = params.get("query") or "la búsqueda"
                    return f"Intenté buscar '{query_clean}' en YouTube, pero no pude confirmar que la búsqueda se haya realizado."
                elif any(k in intent for k in ("file", "archivo", "delete", "create", "write", "move", "copy")):
                    return "Intenté realizar la acción sobre los archivos, pero no pude confirmar el resultado en el sistema."
                return str(getattr(execution_result, "message", None) or "No pude confirmar el resultado de la acción.")

            elif st_upper in ("VERIFICATION_FAILED",):
                if intent == "open_application":
                    return f"Intenté abrir {app_display}, pero Windows no confirmó que se haya abierto."
                elif intent == "type_text":
                    return f"No se pudo escribir en {app_display} porque la ventana no respondió o no se pudo verificar."
                elif intent == "close_application":
                    return f"Intenté cerrar {app_display}, pero no se pudo confirmar el cierre."
                elif intent == "play_random_video":
                    return "Encontré el vídeo, pero no pude iniciar su reproducción."
                elif intent in ("youtube_play", "search_and_play", "browser_search"):
                    return "Logré abrir YouTube, pero no pude iniciar la reproducción."
                elif any(k in intent for k in ("file", "archivo", "delete", "create", "write", "move", "copy")):
                    return "La acción sobre el archivo no pudo ser verificada en el sistema."
                return f"La acción sobre {app_display} no pudo ser verificada en Windows."

            elif st_upper in ("DENIED", "BLOCKED"):
                return "No puedo ejecutar esa acción porque la política de seguridad no la autoriza."
            elif st_upper in ("CANCELLED",):
                return "Operación cancelada."
            else:
                if intent in ("youtube_play", "search_and_play"):
                    err_code = getattr(execution_result, "error_code", None)
                    if err_code == "SEARCH_FAILED":
                        return "No pude encontrar la canción en YouTube."
                    elif err_code == "PLAYBACK_FAILED":
                        return "Logré abrir YouTube, pero no pude iniciar la reproducción."
                    return str(getattr(execution_result, "message", None) or "No pude iniciar la reproducción.")
                elif intent == "play_random_video":
                    err_code = getattr(execution_result, "error_code", None)
                    if err_code == "DIRECTORY_NOT_FOUND":
                        return "No encuentro la carpeta de vídeos de baile configurada."
                    elif err_code == "NO_VIDEOS_FOUND":
                        return "No encontré ningún vídeo de baile en la carpeta configurada."
                    elif err_code == "PLAYBACK_FAILED":
                        return "Encontré el vídeo, pero no pude iniciar su reproducción."
                    return str(getattr(execution_result, "message", None) or "No pude iniciar la reproducción del baile.")
                return f"No pude completar la acción: {getattr(execution_result, 'message', None) or 'Error en la ejecución'}."

        out_data = sys_resp.output if isinstance(sys_resp.output, dict) else {}
        raw_ev = out_data.get("evidence") if isinstance(out_data, dict) else None
        if isinstance(raw_ev, dict) and raw_ev.get("is_verified") is False:
            return "La acción se ejecutó, pero no pude confirmar el resultado en el sistema."

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
        if intent == "general_query" and conversational_handler is not None and context_manager is not None:
            return conversational_handler.generate_response(
                user_input=str(params.get("query", "")),
                session_id=session_id or "default",
                params=params,
                context_manager=context_manager,
            )

        if any(w in intent for w in ("file", "delete", "app", "kill", "process", "window")):
            return "La acción se procesó, pero no pude confirmar el resultado observable en el sistema."

        return "He procesado tu solicitud."

    def build_response(
        self,
        request_id: str,
        session_id: str,
        success: bool,
        status: AgentExecutionState,
        response_text: str,
        spoken_text: str | None = None,
        intent: str | None = None,
        selected_model: str | None = None,
        selected_agent: str | None = None,
        selected_skill: str | None = None,
        selected_graph: str | None = None,
        tools_executed: list[str] | None = None,
        security_verdict: str | None = None,
        security_level: SecurityLevel | None = None,
        output_data: Any | None = None,
        error: str | None = None,
        metrics: LocalAgentMetrics | None = None,
        start_time: float | None = None,
        requires_confirmation: bool = False,
        requires_elevation: bool = False,
        requires_clarification: bool = False,
        clarification_question: str | None = None,
        confirmation_prompt: Any | None = None,
        action_intent_contract: Any | None = None,
    ) -> JessycaResponse:
        """Fabrica canónica de JessycaResponse con cálculo automático de latencia y habla sintetizada."""
        current_metrics = metrics or LocalAgentMetrics(task_id=request_id, correlation_id=request_id)
        if start_time is not None:
            current_metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000

        resolved_spoken = spoken_text if spoken_text is not None else self.synthesize_spoken_text(response_text)

        return JessycaResponse(
            request_id=request_id,
            session_id=session_id,
            success=success,
            status=status,
            response_text=response_text,
            spoken_text=resolved_spoken,
            intent=intent,
            selected_model=selected_model,
            selected_agent=selected_agent,
            selected_skill=selected_skill,
            selected_graph=selected_graph,
            tools_executed=tools_executed or [],
            security_verdict=security_verdict,
            security_level=security_level,
            output_data=output_data,
            error=error,
            metrics=current_metrics,
            requires_confirmation=requires_confirmation,
            requires_clarification=requires_clarification,
            clarification_question=clarification_question,
            action_intent_contract=action_intent_contract,
        )

    def build_stopped_response(
        self,
        req: JessycaRequest,
        metrics: LocalAgentMetrics,
        start_time: float,
        reason: str = "Parada de Emergencia activa. Operación bloqueada.",
    ) -> JessycaResponse:
        """Construye respuesta para parada de emergencia."""
        return self.build_response(
            request_id=req.request_id,
            session_id=req.session_id,
            success=False,
            status=AgentExecutionState.STOPPED,
            response_text=reason,
            security_verdict="DENY",
            error="Emergency Stop active",
            metrics=metrics,
            start_time=start_time,
        )

    def build_interrupted_response(
        self,
        req: JessycaRequest,
        metrics: LocalAgentMetrics,
        start_time: float,
        reason: str = "Operación cancelada por el usuario.",
    ) -> JessycaResponse:
        """Construye respuesta cuando la operación es abortada por un CancellationToken."""
        metrics.interruption_handled = True
        return self.build_response(
            request_id=req.request_id,
            session_id=req.session_id,
            success=False,
            status=AgentExecutionState.INTERRUPTED,
            response_text=reason,
            spoken_text=reason,
            error="Operation cancelled",
            metrics=metrics,
            start_time=start_time,
        )

    def build_cancelled_response(
        self,
        req: JessycaRequest,
        metrics: LocalAgentMetrics,
        start_time: float,
        reason: str = "Entendido, operación cancelada.",
        intent: str = "cancel_task",
    ) -> JessycaResponse:
        """Construye respuesta conversacional de confirmación de cancelación solicitada por el usuario."""
        return self.build_response(
            request_id=req.request_id,
            session_id=req.session_id,
            success=True,
            status=AgentExecutionState.COMPLETED,
            response_text=reason,
            spoken_text=reason,
            intent=intent,
            metrics=metrics,
            start_time=start_time,
        )

    def build_closing_response(
        self,
        req: JessycaRequest,
        metrics: LocalAgentMetrics,
        start_time: float,
        closing_text: str = "¡Hasta luego! Que tengas un excelente día.",
    ) -> JessycaResponse:
        """Construye respuesta para cierre normal de conversación."""
        return self.build_response(
            request_id=req.request_id,
            session_id=req.session_id,
            success=True,
            status=AgentExecutionState.COMPLETED,
            response_text=closing_text,
            spoken_text=closing_text,
            intent="close_conversation",
            metrics=metrics,
            start_time=start_time,
        )

    def build_clarification_response(
        self,
        req: JessycaRequest,
        metrics: LocalAgentMetrics,
        start_time: float,
        question: str,
        intent: str | None = None,
    ) -> JessycaResponse:
        """Construye respuesta cuando se requiere aclaración de parámetros."""
        return self.build_response(
            request_id=req.request_id,
            session_id=req.session_id,
            success=False,
            status=AgentExecutionState.WAITING_CLARIFICATION,
            response_text=question,
            spoken_text=question,
            intent=intent,
            requires_clarification=True,
            clarification_question=question,
            metrics=metrics,
            start_time=start_time,
        )

    def build_confirmation_response(
        self,
        req: JessycaRequest,
        metrics: LocalAgentMetrics,
        start_time: float,
        prompt_text: str,
        prompt_obj: Any | None = None,
        intent: str | None = None,
        selected_agent: str | None = None,
        selected_skill: str | None = None,
        requires_elevation: bool = False,
    ) -> JessycaResponse:
        """Construye respuesta cuando una acción requiere confirmación del usuario."""
        return self.build_response(
            request_id=req.request_id,
            session_id=req.session_id,
            success=False,
            status=AgentExecutionState.WAITING_CONFIRMATION,
            response_text=prompt_text,
            spoken_text=prompt_text,
            intent=intent,
            selected_agent=selected_agent,
            selected_skill=selected_skill,
            security_verdict="REQUIRES_CONFIRMATION",
            requires_confirmation=True,
            requires_elevation=requires_elevation,
            confirmation_prompt=prompt_obj,
            metrics=metrics,
            start_time=start_time,
        )


_global_response_synthesizer: ResponseSynthesizer | None = None


def get_response_synthesizer() -> ResponseSynthesizer:
    """Obtiene o inicializa el ResponseSynthesizer singleton."""
    global _global_response_synthesizer
    if _global_response_synthesizer is None:
        _global_response_synthesizer = ResponseSynthesizer()
    return _global_response_synthesizer
