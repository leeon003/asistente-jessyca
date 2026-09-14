"""Planificador de Acciones Conversacionales y Compuestas (action_planner.py - Fases 52.1 y 64.2.1).

Construye planes de acción estructurados y contratos ActionIntentContract fuertemente tipados
para órdenes simples, compuestas y operaciones sobre el sistema operativo.

INVARIANTE FUNDAMENTAL DE PLANIFICACIÓN (Fase 64.2.1):
PLANIFICAR != EJECUTAR
La planificación construye exclusivamente la intención, la especificación de ejecución
(ExecutionSpec) y las compuertas de seguridad (ExecutionGate).
Bajo ninguna circunstancia invoca Skills, modifica procesos del SO ni declara falsos éxitos.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from core.action_intent_contract import (
    ActionIntent,
    ActionIntentContract,
    ExecutionGate,
    ExecutionSpec,
    PreActionFeedback,
)
from core.dialogue.dialogue_models import (
    ActionPlan,
    ActionPlanStep,
)
from core.logger import get_logger

logger = get_logger("jessyca.dialogue.action_planner")


class ActionPlanningError(Exception):
    """Error base de planificación de acciones."""

    pass


class ActionPlanningValidationError(ActionPlanningError, ValueError):
    """Error emitido cuando los parámetros, skills o compuertas de una acción son inválidos."""

    pass


class ActionPlanner:
    """Constructor determinista y validador de planes de acción y contratos de intención."""

    # Catálogo canónico de Skills de producción reconocidas en JESSYCA
    KNOWN_SKILLS: frozenset[str] = frozenset({
        "windows.apps",
        "windows.media",
        "windows.screenshot",
        "windows.clipboard",
        "windows.notifications",
        "windows.audio",
        "windows.display",
        "files.search",
        "files.read",
        "files.create",
        "files.copy",
        "files.move",
        "files.rename",
        "files.organize",
        "browser.open",
        "browser.search",
        "browser.navigate",
        "browser.read",
        "browser.download",
        "documents.read",
        "documents.create",
        "documents.summarize",
        "documents.convert",
        "core.assistant",
        "system.execute",
        "desktop_agent",
        "file_agent",
        "browser_agent",
    })

    def is_skill_available(self, skill_id: str) -> bool:
        """Verifica si un identificador de skill existe y está disponible en el catálogo."""
        clean = (skill_id or "").split("@")[0].strip()
        if not clean:
            return False

        if clean in self.KNOWN_SKILLS:
            return True

        # Consulta dinámica al SkillRegistry si está disponible
        try:
            from skills.skill_registry import get_skill_registry
            registry = get_skill_registry()
            if registry.lookup(clean) or registry.lookup(skill_id):
                return True
        except Exception:
            pass

        return False

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
            app_name = params.get("app_name") or params.get("nombre_app") or "la aplicación"
            app_display = self._format_app_display(str(app_name))
            steps = [
                ActionPlanStep(
                    step_number=1,
                    intent="open_application",
                    skill_id="windows.apps@1.0.0",
                    tool_name="windows.launch_app",
                    parameters={"accion": "abrir", "nombre_app": str(app_name)},
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
            app_name = params.get("app_name") or params.get("nombre_app") or "la aplicación"
            app_display = self._format_app_display(str(app_name))
            steps = [
                ActionPlanStep(
                    step_number=1,
                    intent="close_application",
                    skill_id="windows.apps@1.0.0",
                    tool_name="windows.close_app",
                    parameters={"accion": "cerrar", "nombre_app": str(app_name)},
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

        # 5. Caso Captura de Pantalla (windows.screenshot)
        if intent in ("screenshot", "capture_screenshot", "take_screenshot", "pantalla"):
            steps = [
                ActionPlanStep(
                    step_number=1,
                    intent="capture_screenshot",
                    skill_id="windows.screenshot@1.0.0",
                    tool_name="desktop.screenshot",
                    parameters={"prompt": params.get("prompt", "Describe lo que ves en mi pantalla.")},
                    description="Capturar y analizar la pantalla del usuario",
                )
            ]
            return ActionPlan(
                plan_id=plan_id,
                intent="capture_screenshot",
                steps=steps,
                summary_speech="Listo, tomo una captura de pantalla.",
                is_composite=False,
            )

        # 6. Caso Búsqueda en Navegador / YouTube
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

        # 7. Petición Conversacional (sin pasos de ejecución)
        if intent in ("general_query", "conversational", "greeting", "chit_chat"):
            return ActionPlan(
                plan_id=plan_id,
                intent=intent,
                steps=[],
                summary_speech="",
                is_composite=False,
            )

        # 8. Plan genérico por defecto para acciones
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

    def plan_action(
        self,
        intent: str,
        user_input: str = "",
        params: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        confidence: float = 1.0,
        request_id: str | None = None,
        session_id: str | None = None,
        idempotency_key: str | None = None,
        risk_level: str | None = None,
        requires_confirmation: bool | None = None,
        skill_id: str | None = None,
        tool_name: str | None = None,
    ) -> ActionIntentContract:
        """Planifica y valida una acción produciendo un ActionIntentContract inmutable.

        Aplica validaciones estrictas:
        - Rechaza intenciones sin identificador o vacías.
        - Rechaza valores de confidence fuera de [0.0, 1.0].
        - Rechaza skills inexistentes o no registradas.
        - Rechaza operaciones vacías o malformadas.
        - Rechaza argumentos incompatibles o ausentes según la intención.
        - Ajusta el ExecutionGate según nivel de riesgo, confirmación y confidence.
        - Garantiza execution_report=None y post_action_feedback=None (separación planificar/ejecutar).
        """
        # ── 1. Validación de Identificador de Intención ───────────────────────
        if not intent or not isinstance(intent, str) or not intent.strip():
            raise ActionPlanningValidationError("El identificador de la intención (intent) no puede ser nulo o vacío.")
        clean_intent = intent.strip()

        # ── 2. Validación de Confidence ──────────────────────────────────────
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ActionPlanningValidationError(
                f"Confidence inválida: {confidence}. Debe ser un valor numérico."
            )
        if confidence < 0.0 or confidence > 1.0:
            raise ActionPlanningValidationError(
                f"Confidence inválida: {confidence}. Debe estar en el rango [0.0, 1.0]."
            )
        clamped_confidence = float(confidence)

        parameters = dict(params or {})
        ctx = dict(context or {})

        # ── 3. Validación de Skill y Tool explícitos ─────────────────────────
        if skill_id is not None:
            clean_skill = str(skill_id).strip()
            if not clean_skill:
                raise ActionPlanningValidationError("El skill_id especificado no puede ser una cadena vacía.")
            if not self.is_skill_available(clean_skill):
                raise ActionPlanningValidationError(
                    f"Skill inexistente o no disponible en el sistema: '{clean_skill}'."
                )

        if tool_name is not None:
            clean_tool = str(tool_name).strip()
            if not clean_tool:
                raise ActionPlanningValidationError(
                    "La operación solicitada (tool_name) no puede ser una cadena vacía."
                )

        # ── 4. Validación de Argumentos según la Intención ───────────────────
        if clean_intent in ("open_application", "close_application"):
            app_name = parameters.get("app_name") or parameters.get("nombre_app")
            if not app_name or not str(app_name).strip():
                raise ActionPlanningValidationError(
                    f"Argumentos incompatibles o incompletos: la acción '{clean_intent}' requiere el parámetro 'app_name'."
                )

        if clean_intent == "browser_search":
            query = parameters.get("query") or parameters.get("search_query") or user_input.strip()
            if not query or not str(query).strip() or query == clean_intent:
                if not parameters.get("query") and not parameters.get("topic"):
                    raise ActionPlanningValidationError(
                        "Argumentos incompatibles o incompletos: la acción 'browser_search' requiere un término de búsqueda ('query')."
                    )

        # ── 5. Construcción del ActionPlan Subyacente ─────────────────────────
        plan = self.build_plan(
            intent=clean_intent,
            user_input=user_input or clean_intent,
            params=parameters,
            context=ctx,
        )

        # ── 6. Resolución de Skill y Tool para ExecutionSpec ──────────────────
        resolved_skill = skill_id
        resolved_tool = tool_name

        if plan.steps:
            first_step = plan.steps[0]
            if not resolved_skill:
                resolved_skill = first_step.skill_id
            if not resolved_tool:
                resolved_tool = first_step.tool_name

        # Validar que el skill resuelto exista
        if resolved_skill and not self.is_skill_available(resolved_skill):
            raise ActionPlanningValidationError(
                f"Skill resuelta inexistente o no disponible: '{resolved_skill}'."
            )

        if resolved_skill and (not resolved_tool or not str(resolved_tool).strip()):
            raise ActionPlanningValidationError(
                f"Operación vacía o inválida para la skill '{resolved_skill}'."
            )

        # ── 7. Evaluación de ExecutionGate (Riesgo, Confirmación, Ambigüedad) ─
        is_low_confidence = clamped_confidence < 0.70
        is_ambiguous = bool(ctx.get("is_ambiguous") or parameters.get("is_ambiguous"))

        needs_clarif = is_low_confidence or is_ambiguous or bool(parameters.get("requires_clarification"))
        clarif_prompt: str | None = None
        if needs_clarif:
            if is_low_confidence:
                clarif_prompt = (
                    f"La confianza en la acción '{clean_intent}' es baja ({clamped_confidence:.2f}). "
                    f"¿Podrías confirmar qué deseas hacer?"
                )
            else:
                clarif_prompt = (
                    parameters.get("clarification_question")
                    or ctx.get("clarification_prompt")
                    or "¿Podrías darme más detalles sobre lo que deseas hacer?"
                )

        # Resolución de nivel de riesgo
        resolved_risk = (
            risk_level
            or ctx.get("risk_level")
            or parameters.get("risk_level")
            or ("DANGEROUS" if clean_intent in ("delete_file", "kill_process", "format_disk") else "SAFE")
        )

        explicit_confirm = (
            requires_confirmation
            if requires_confirmation is not None
            else bool(parameters.get("requires_confirmation") or ctx.get("requires_confirmation"))
        )
        needs_confirm = explicit_confirm or str(resolved_risk).upper() in ("DANGEROUS", "CRITICAL", "HIGH")

        confirm_prompt: str | None = None
        if needs_confirm:
            target_desc = resolved_tool or clean_intent
            confirm_prompt = (
                ctx.get("confirmation_prompt")
                or f"Detecté una acción sensible: '{target_desc}'. ¿Confirmas su ejecución?"
            )

        can_execute = not needs_clarif and not needs_confirm

        execution_gate = ExecutionGate(
            can_execute=can_execute,
            needs_clarification=needs_clarif,
            clarification_prompt=clarif_prompt,
            needs_confirmation=needs_confirm,
            risk_level=str(resolved_risk),
            confirmation_prompt=confirm_prompt,
        )

        # ── 8. PreActionFeedback ─────────────────────────────────────────────
        summary_speech = plan.summary_speech or f"Voy a ejecutar {clean_intent}."
        pre_action_feedback = PreActionFeedback(acknowledgement_speech=summary_speech)

        # ── 9. ExecutionSpec ─────────────────────────────────────────────────
        execution_spec: ExecutionSpec | None = None
        resolved_idemp = idempotency_key or ctx.get("idempotency_key") or f"idemp-{uuid.uuid4().hex[:12]}"
        if resolved_skill:
            execution_spec = ExecutionSpec(
                skill_id=str(resolved_skill),
                tool_name=str(resolved_tool) if resolved_tool else None,
                idempotency_key=str(resolved_idemp),
            )

        # ── 10. ActionIntent ─────────────────────────────────────────────────
        target_val = (
            parameters.get("app_name")
            or parameters.get("nombre_app")
            or parameters.get("target")
            or parameters.get("query")
            or parameters.get("topic")
        )
        action_intent = ActionIntent(
            intent_name=clean_intent,
            confidence=clamped_confidence,
            is_ambiguous=is_ambiguous,
            input_modality=ctx.get("modality", "text"),
            target=str(target_val).strip() if target_val else None,
            parameters=parameters,
            missing_slots=[ctx["expected_slot"]] if ctx.get("expected_slot") else [],
        )

        # ── 11. Retorno de ActionIntentContract Inmutable ────────────────────
        resolved_req_id = request_id or ctx.get("request_id") or f"req-plan-{uuid.uuid4().hex[:8]}"
        resolved_sess_id = session_id or ctx.get("session_id") or "session-default"

        return ActionIntentContract(
            request_id=resolved_req_id,
            session_id=resolved_sess_id,
            action_intent=action_intent,
            execution_gate=execution_gate,
            pre_action_feedback=pre_action_feedback,
            execution_spec=execution_spec,
            execution_report=None,
            post_action_feedback=None,
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


__all__ = [
    "ActionPlanner",
    "ActionPlanningError",
    "ActionPlanningValidationError",
]
