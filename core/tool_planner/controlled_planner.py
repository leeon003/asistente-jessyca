"""Controlled Tool Planner (Etapas 19.0 y 19.1).

GARANTÍAS INMUTABLES DE SEGURIDAD:
1. El planner ÚNICAMENTE tiene autoridad para:
   - Proponer (propose)
   - Ordenar (order)
   - Comparar (compare)
   - Descartar (discard)
2. El planner TIENE PROHIBIDO:
   - Ejecutar directamente herramientas
   - Conceder permisos
   - Cambiar niveles de riesgo
   - Cambiar niveles de autonomía
   - Modificar políticas de seguridad
3. Capacidad de sugerir ALTERNATIVAS SEGURAS cuando una herramienta primaria no está autorizada.
"""

from __future__ import annotations

import re
from typing import Any

from core.autonomy.autonomy_governor import get_autonomy_governor
from core.exceptions import MCPError
from core.logger import get_logger
from core.tool_planner.comparator import ToolCandidateComparator
from core.tool_planner.discovery import ToolDiscoveryService
from core.tool_planner.models import (
    MemoryEvidence,
    PlanningContext,
    ProposedStep,
    ToolPlanProposal,
)
from core.workflow.models import WorkflowDefinition, WorkflowSource, WorkflowStep

logger = get_logger("jessyca.planner.controlled")


class PlannerAuthorityViolationError(MCPError):
    """Error emitido cuando el Planner intenta ejercer autoridad indebida (ejecución, permisos, autonomía)."""

    pass


class ControlledToolPlanner:
    """Planner de herramientas controlado con conocimiento integral de capacidades y autoridad de sólo propuesta."""

    def __init__(
        self,
        discovery_service: ToolDiscoveryService | None = None,
        comparator: ToolCandidateComparator | None = None,
    ) -> None:
        self.discovery = discovery_service or ToolDiscoveryService()
        self.comparator = comparator or ToolCandidateComparator()

    def plan(
        self,
        intent: str,
        context: dict[str, Any] | None = None,
        memory_evidence: list[MemoryEvidence] | None = None,
        subtasks_hints: list[dict[str, Any]] | None = None,
        planning_context: PlanningContext | None = None,
    ) -> ToolPlanProposal:
        """Genera un plan de herramientas declarativo evaluando capacidades, riesgos y permisos."""
        ctx = context or {}
        evidence = memory_evidence or []

        # Determinar PlanningContext efectivo
        if planning_context is None:
            governor = get_autonomy_governor()
            p_ctx = PlanningContext(
                user_intent=intent,
                current_autonomy_level=governor.current_level,
                session_id=str(ctx.get("session_id", "")),
            )
        else:
            p_ctx = planning_context

        logger.info(
            f"[CONTROLLED PLANNER] Generando plan para intent: '{intent}' "
            f"(nivel: {p_ctx.current_autonomy_level.label}, scheduled={p_ctx.is_scheduled}, plugin={p_ctx.is_plugin})"
        )

        proposed_steps: list[ProposedStep] = []
        discarded_summary: dict[str, str] = {}

        hints = subtasks_hints or self._decompose_intent(intent)

        for idx, hint in enumerate(hints, 1):
            step_id = hint.get("step_id", f"step_{idx:02d}")
            req_capability = hint.get("capability")
            hint_keywords = hint.get("keywords", []) or self._extract_keywords(hint.get("description", intent))

            # 1. Tool Discovery con evaluación de capacidades y contexto de autonomía
            candidates = self.discovery.discover_candidates(
                intent_keywords=hint_keywords,
                required_capability=req_capability,
                planning_context=p_ctx,
            )

            # 2. Compare & Rank (con propuesta de alternativas seguras si la primaria no está autorizada)
            best_tool, discarded = self.comparator.evaluate_and_rank(candidates, evidence)

            for d in discarded:
                discarded_summary[f"{step_id}:{d.tool_name}.{d.operation}"] = d.discard_reason or "Descartada"

            if best_tool is not None:
                step = ProposedStep(
                    step_id=step_id,
                    tool_name=best_tool.tool_name,
                    operation=best_tool.operation,
                    parameters=hint.get("parameters", {}),
                    dependencies=tuple(hint.get("dependencies", ())),
                    rationale=f"Herramienta '{best_tool.capability}' seleccionada: {best_tool.match_reason}",
                    evidence_used=tuple(ev.evidence_id for ev in evidence if best_tool.tool_name.lower() in ev.fact_or_preference.lower()),
                    discarded_alternatives=tuple(f"{d.tool_name}.{d.operation}" for d in discarded),
                    minimum_autonomy_level=best_tool.minimum_autonomy_level,
                    declared_risk=best_tool.declared_risk,
                    reversibility=best_tool.reversibility,
                    requires_confirmation=best_tool.requires_confirmation,
                    limitations=best_tool.limitations,
                    is_safe_alternative=best_tool.is_safe_alternative,
                )
                proposed_steps.append(step)
            else:
                logger.warning(f"[CONTROLLED PLANNER] No se encontró herramienta adecuada ni alternativa segura para el paso '{step_id}'")

        proposal = ToolPlanProposal.create(
            intent=intent,
            context=ctx,
            evidence_applied=evidence,
            proposed_steps=proposed_steps,
            discarded_tools_summary=discarded_summary,
            planning_context=p_ctx,
        )

        logger.info(f"[CONTROLLED PLANNER] Plan propuesto generado exitosamente con {len(proposed_steps)} pasos.")
        return proposal

    def to_workflow_definition(self, proposal: ToolPlanProposal) -> WorkflowDefinition:
        """Convierte una propuesta de plan en una WorkflowDefinition formal para entrega al Security Pipeline y Executor."""
        wf_steps = [
            WorkflowStep(
                step_id=s.step_id,
                name=f"Ejecutar {s.tool_name}.{s.operation}",
                tool_name=s.tool_name,
                operation=s.operation,
                parameters=s.parameters,
                dependencies=s.dependencies,
                risk_level=s.declared_risk,
                required_autonomy_level=s.minimum_autonomy_level,
                requires_confirmation=s.requires_confirmation,
            )
            for s in proposal.proposed_steps
        ]
        return WorkflowDefinition.create(
            name=f"Workflow para '{proposal.intent[:40]}'",
            steps=wf_steps,
            owner_source=WorkflowSource.USER,
            description=f"Generado a partir de propuesta {proposal.plan_id}",
        )

    # ─── INVARIANTES DE SEGURIDAD ABSOLUTA (BARRERAS CONTRA ESCALADA DE AUTORIDAD) ───

    def execute(self, *args: Any, **kwargs: Any) -> None:
        """PROHIBIDO: El planner no puede ejecutar directamente herramientas."""
        raise PlannerAuthorityViolationError(
            "[PLANNER AUTHORITY VIOLATION] El Planner NO tiene autoridad para ejecutar herramientas. "
            "La ejecución debe realizarse fuera del planner a través de AutonomyPolicy y SecureExecutionPipeline."
        )

    def grant_permission(self, *args: Any, **kwargs: Any) -> None:
        """PROHIBIDO: El planner no puede conceder permisos."""
        raise PlannerAuthorityViolationError(
            "[PLANNER AUTHORITY VIOLATION] El Planner NO tiene autoridad para conceder permisos."
        )

    def set_risk_level(self, *args: Any, **kwargs: Any) -> None:
        """PROHIBIDO: El planner no puede modificar niveles de riesgo."""
        raise PlannerAuthorityViolationError(
            "[PLANNER AUTHORITY VIOLATION] El Planner NO tiene autoridad para alterar niveles de riesgo."
        )

    def set_autonomy_level(self, *args: Any, **kwargs: Any) -> None:
        """PROHIBIDO: El planner no puede alterar el nivel de autonomía."""
        raise PlannerAuthorityViolationError(
            "[PLANNER AUTHORITY VIOLATION] El Planner NO tiene autoridad para modificar el nivel de autonomía."
        )

    def modify_policy(self, *args: Any, **kwargs: Any) -> None:
        """PROHIBIDO: El planner no puede modificar políticas de seguridad."""
        raise PlannerAuthorityViolationError(
            "[PLANNER AUTHORITY VIOLATION] El Planner NO tiene autoridad para modificar políticas de seguridad."
        )

    # ─── MÉTODOS AUXILIARES DE DESCOMPOSICIÓN ───

    def _decompose_intent(self, intent: str) -> list[dict[str, Any]]:
        """Descompone intenciones compuestas simples (ej: 'leer X y luego escribir Y')."""
        keywords = self._extract_keywords(intent)
        return [{"step_id": "step_01", "description": intent, "keywords": keywords}]

    def _extract_keywords(self, text: str) -> list[str]:
        """Extrae palabras clave representativas de un texto."""
        tokens = re.findall(r"\b[a-zA-ZáéíóúÁÉÍÓÚñÑ_]{3,}\b", text.lower())
        stopwords = {"para", "luego", "como", "con", "por", "que", "una", "los", "las", "del", "este", "esta"}
        return [t for t in tokens if t not in stopwords]
