"""Gestor de Diálogo de Acción Natural (dialogue_manager.py - Fase 52.1).

Gobierna la generación de respuestas pre-ejecución, preguntas aclaratorias desambiguadoras,
explicación de límites y formulación de resultados basados estrictamente en verificación.
"""

from __future__ import annotations

import threading
from typing import Any

from core.dialogue.action_planner import ActionPlanner
from core.dialogue.capability_awareness import CapabilityAwarenessEngine
from core.dialogue.dialogue_models import (
    CapabilityLevel,
    DialogueActionType,
    DialogueDecision,
)
from core.logger import get_logger

logger = get_logger("jessyca.dialogue.dialogue_manager")


class NaturalActionDialogueManager:
    """Coordinador conversacional para diálogo natural y conciencia de capacidades."""

    _instance: NaturalActionDialogueManager | None = None
    _lock = threading.RLock()

    def __init__(
        self,
        capability_engine: CapabilityAwarenessEngine | None = None,
        action_planner: ActionPlanner | None = None,
    ) -> None:
        self.capability_engine = capability_engine or CapabilityAwarenessEngine.get_instance()
        self.action_planner = action_planner or ActionPlanner()

    @classmethod
    def get_instance(cls) -> NaturalActionDialogueManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = NaturalActionDialogueManager()
            return cls._instance

    # ── 1. EVALUACIÓN Y DECISIÓN DIALÓGICA ──

    def evaluate_dialogue(
        self,
        user_input: str,
        intent: str,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
        is_ambiguous: bool = False,
    ) -> DialogueDecision:
        """Evalúa la solicitud y genera la decisión dialógica previa a la ejecución."""
        # 1.1 Evaluar capacidades
        assessment = self.capability_engine.assess_request(
            user_input=user_input,
            intent=intent,
            params=params,
            context=context,
        )

        # 1.2 Capacidad No Soportada (NONE)
        if assessment.level == CapabilityLevel.NONE:
            resp = assessment.explanation or "Eso todavía no puedo hacerlo directamente."
            return DialogueDecision(
                action_type=DialogueActionType.UNSUPPORTED_CAPABILITY,
                capability_level=CapabilityLevel.NONE,
                response_text=resp,
                is_terminal=True,
            )

        # 1.3 Capacidad Parcial (PARTIAL)
        if assessment.level == CapabilityLevel.PARTIAL:
            resp = assessment.explanation or "Puedo hacer una parte de eso, pero no todo."
            return DialogueDecision(
                action_type=DialogueActionType.PARTIAL_CAPABILITY,
                capability_level=CapabilityLevel.PARTIAL,
                response_text=resp,
                is_terminal=True,
            )

        # 1.4 Consulta de Capacidades ("¿Puedes...?")
        if intent == "explain_capability":
            resp = assessment.explanation or "Puedo ayudarte a abrir aplicaciones, reproducir vídeos y realizar búsquedas."
            return DialogueDecision(
                action_type=DialogueActionType.EXPLAIN_CAPABILITY,
                capability_level=CapabilityLevel.FULL,
                response_text=resp,
                is_terminal=True,
            )

        # 1.4.1 Consultas y Diálogo Conversacional (CONVERSATIONAL_REQUEST)
        if intent in ("general_query", "conversational", "greeting", "chit_chat"):
            return DialogueDecision(
                action_type=DialogueActionType.CONVERSATIONAL,
                capability_level=CapabilityLevel.FULL,
                response_text="",
                is_terminal=False,
            )

        # 1.5 Requiere Aclaración o Intención Ambigua
        if is_ambiguous or params.get("requires_clarification"):
            if params.get("immediate_response"):
                clarification_msg = str(params["immediate_response"])
            elif intent == "open_application":
                clarification_msg = "¿Podrías especificar qué aplicación deseas abrir?"
            elif intent == "close_application":
                clarification_msg = "¿Podrías especificar qué aplicación deseas cerrar?"
            elif intent == "search_file":
                clarification_msg = "¿Podrías especificar qué archivo deseas buscar?"
            else:
                clarification_msg = "¿Podrías darme más detalles sobre lo que deseas hacer?"

            expected_slot = params.get("expected_slot") or ("app_name" if "application" in intent else "target")
            return DialogueDecision(
                action_type=DialogueActionType.CLARIFICATION,
                capability_level=CapabilityLevel.FULL,
                response_text=clarification_msg,
                clarification_question=clarification_msg,
                expected_slot=expected_slot,
                is_terminal=False,
            )

        # 1.6 Construir Plan de Acción y Locución Pre-Acción
        plan = self.action_planner.build_plan(
            intent=intent,
            user_input=user_input,
            params=params,
            context=context,
        )

        return DialogueDecision(
            action_type=DialogueActionType.DIRECT_ACTION,
            capability_level=CapabilityLevel.FULL,
            response_text=plan.summary_speech,
            pre_action_speech=plan.summary_speech,
            action_plan=plan,
            is_terminal=False,
        )

    # ── 2. FORMATEO DE RESULTADO POST-EJECUCIÓN ──

    def format_post_execution_response(
        self,
        intent: str,
        success: bool,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        is_verified: bool = True,
        params: dict[str, Any] | None = None,
    ) -> str:
        """Genera una respuesta hablada basada en la verificación real del sistema operativo."""
        params_dict = params or {}
        out_dict = output or {}

        # 2.1 Fallo de ejecución o verificación
        if not success or not is_verified:
            if not is_verified:
                return f"Intenté completar la acción, pero no pude confirmar su estado en Windows: {error or 'Sin verificación confirmada'}."
            return f"Intenté hacerlo, pero no pude completar la acción: {error or 'Error en la ejecución'}."

        # 2.2 Éxito Verificado por Intención

        # Smart Media Playback ("Jessyca, báilame")
        if intent == "play_random_video":
            return "Listo, ya está reproduciéndose."

        # Búsqueda de canciones / YouTube
        if intent in ("browser_search", "youtube_search"):
            query = params_dict.get("query") or params_dict.get("topic") or "el contenido"
            if "youtube" in str(query).lower() or "morodo" in str(query).lower() or "cancion" in str(query).lower():
                return f"Encontré '{query}'. ¿Quieres que la reproduzca?"
            return f"Encontré los resultados para '{query}'."

        # Búsqueda y reproducción compuesta
        if intent == "search_and_play":
            return "Listo, ya está reproduciéndose."

        # Control de Aplicaciones
        if intent == "open_application":
            app_display = self.action_planner._format_app_display(params_dict.get("app_name", "la aplicación"))
            return f"Listo, abrí {app_display}."

        if intent == "close_application":
            app_display = self.action_planner._format_app_display(params_dict.get("app_name", "la aplicación"))
            return f"Listo, cerré {app_display}."

        return str(out_dict.get("mensaje") or "Acción completada con éxito.")
