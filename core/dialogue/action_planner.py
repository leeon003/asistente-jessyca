"""Planificador de Acciones Conversacionales y Compuestas (action_planner.py - Fase 52.1).

Construye planes de acción estructurados para órdenes simples y compuestas,
evitando preguntas redundantes cuando el usuario proporciona todas las instrucciones en una sola petición.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from core.dialogue.dialogue_models import (
    ActionPlan,
    ActionPlanStep,
)
from core.logger import get_logger

logger = get_logger("jessyca.dialogue.action_planner")


class ActionPlanner:
    """Constructor determinista de planes de acción para el ciclo conversacional."""

    def build_plan(
        self,
        intent: str,
        user_input: str,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ActionPlan:
        """Genera un ActionPlan ordenado a partir de la intención y parámetros extraídos."""
        lower = user_input.strip().lower()
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"

        # 1. Caso Compuesto: "Busca y reproduce X" / "Busca X y ponla"
        compound_match = re.match(
            r"^(?:jessyca,?\s*|jessica,?\s*)?(?:busca\s+y\s+(?:reproduce|pon|escucha)|pon\s+y\s+busca)\s+(.+)$",
            lower,
        )
        if compound_match or ("busca" in lower and any(p in lower for p in ("reproduce", "pon", "ponla", "reprodúcela", "reproducela"))):
            query = params.get("query") or params.get("topic")
            if not query:
                # Extraer consulta del texto
                cleaned_query = re.sub(r"^(?:jessyca,?\s*|jessica,?\s*)?(?:busca\s+y\s+reproduce|busca\s+y\s+pon|busca)\s+", "", lower)
                cleaned_query = re.sub(r"\s+y\s+(?:reprodúcela|reproducela|ponla|dale play)$", "", cleaned_query).strip()
                query = cleaned_query or "música"

            steps = [
                ActionPlanStep(
                    step_number=1,
                    intent="browser_search",
                    skill_id="browser.search@1.0.0",
                    tool_name="browser.search",
                    parameters={"query": query, "motor": "youtube"},
                    description=f"Buscar '{query}' en YouTube",
                ),
                ActionPlanStep(
                    step_number=2,
                    intent="browser_open",
                    skill_id="browser.open@1.0.0",
                    tool_name="browser.open",
                    parameters={"url": f"https://www.youtube.com/results?search_query={query}"},
                    description=f"Abrir y reproducir '{query}'",
                ),
            ]
            return ActionPlan(
                plan_id=plan_id,
                intent="search_and_play",
                steps=steps,
                summary_speech="Claro, voy a buscarla y reproducirla.",
                is_composite=True,
            )

        # 2. Caso Smart Media Playback ("Jessyca, báilame")
        if intent == "play_random_video":
            steps = [
                ActionPlanStep(
                    step_number=1,
                    intent="play_random_video",
                    skill_id="windows.media@1.0.0",
                    tool_name="windows.media.play",
                    parameters={"accion": "play_random_video"},
                    description="Seleccionar y reproducir un vídeo aleatorio de D:\\bailes de ia",
                )
            ]
            return ActionPlan(
                plan_id=plan_id,
                intent=intent,
                steps=steps,
                summary_speech="Listo, te pongo un bailecito.",
                is_composite=False,
            )

        # 3. Caso Abrir Aplicación
        if intent == "open_application":
            app_name = params.get("app_name", "la aplicación")
            app_display = self._format_app_display(app_name)
            steps = [
                ActionPlanStep(
                    step_number=1,
                    intent="open_application",
                    skill_id="windows.apps@1.0.0",
                    tool_name="windows.launch_app",
                    parameters={"accion": "abrir", "nombre_app": app_name},
                    description=f"Abrir {app_display}",
                )
            ]
            return ActionPlan(
                plan_id=plan_id,
                intent=intent,
                steps=steps,
                summary_speech=f"Claro, te abro {app_display}.",
                is_composite=False,
            )

        # 4. Caso Cerrar Aplicación
        if intent == "close_application":
            app_name = params.get("app_name", "la aplicación")
            app_display = self._format_app_display(app_name)
            steps = [
                ActionPlanStep(
                    step_number=1,
                    intent="close_application",
                    skill_id="windows.apps@1.0.0",
                    tool_name="windows.close_app",
                    parameters={"accion": "cerrar", "nombre_app": app_name},
                    description=f"Cerrar {app_display}",
                )
            ]
            return ActionPlan(
                plan_id=plan_id,
                intent=intent,
                steps=steps,
                summary_speech=f"Listo, voy a cerrar {app_display}.",
                is_composite=False,
            )

        # 5. Caso Búsqueda en Navegador / YouTube
        if intent == "browser_search":
            query = params.get("query") or params.get("search_query") or user_input
            steps = [
                ActionPlanStep(
                    step_number=1,
                    intent="browser_search",
                    skill_id="browser.search@1.0.0",
                    tool_name="browser.search",
                    parameters={"query": query},
                    description=f"Buscar '{query}'",
                )
            ]
            return ActionPlan(
                plan_id=plan_id,
                intent=intent,
                steps=steps,
                summary_speech=f"Perfecto, voy a buscar '{query}'.",
                is_composite=False,
            )

        # 6. Petición Conversacional (sin pasos de ejecución)
        if intent in ("general_query", "conversational", "greeting", "chit_chat"):
            return ActionPlan(
                plan_id=plan_id,
                intent=intent,
                steps=[],
                summary_speech="",
                is_composite=False,
            )

        # 7. Plan genérico por defecto para acciones
        return ActionPlan(
            plan_id=plan_id,
            intent=intent,
            steps=[
                ActionPlanStep(
                    step_number=1,
                    intent=intent,
                    skill_id="core.assistant@1.0.0",
                    tool_name="system.execute",
                    parameters=params,
                    description=f"Ejecutar acción {intent}",
                )
            ],
            summary_speech="Claro, lo hago.",
            is_composite=False,
        )

    def _format_app_display(self, app_name: str) -> str:
        """Formatea el nombre de la aplicación con su artículo natural en español."""
        app_lower = str(app_name).lower().strip()
        if "bloc de notas" in app_lower or "notepad" in app_lower:
            return "el Bloc de notas"
        if "calculadora" in app_lower or "calc" in app_lower:
            return "la Calculadora"
        if "chrome" in app_lower:
            return "Google Chrome"
        if "edge" in app_lower:
            return "Microsoft Edge"
        if "paint" in app_lower:
            return "Paint"
        if "cmd" in app_lower or "terminal" in app_lower:
            return "la consola"
        return f"'{app_name}'"
