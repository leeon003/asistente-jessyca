"""Modelos de Datos para el Controlled Tool Planner (Etapas 19.0 y 19.1).

GARANTÍA DE SEGURIDAD:
El Planner ÚNICAMENTE propone, ordena, compara y descarta herramientas.
NO tiene autoridad de ejecución, concesión de permisos, elevación de autonomía ni alteración de políticas.
Conoce capacidades, riesgos, permisos, disponibilidad y limitaciones de sólo lectura.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk


@dataclass(frozen=True)
class PlanningContext:
    """Contexto de planificación que delimita el alcance, nivel de autonomía y origen de la tarea."""

    user_intent: str
    current_autonomy_level: AutonomyLevel = AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED
    is_scheduled: bool = False
    is_plugin: bool = False
    plugin_id: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_intent": self.user_intent,
            "current_autonomy_level": self.current_autonomy_level.label,
            "is_scheduled": self.is_scheduled,
            "is_plugin": self.is_plugin,
            "plugin_id": self.plugin_id,
            "session_id": self.session_id,
        }


@dataclass(frozen=True)
class MemoryEvidence:
    """Evidencia contextual inmutable proveniente de la memoria (preferencias, historial, etc.)."""

    evidence_id: str
    fact_or_preference: str
    category: str = "general"
    confidence: float = 1.0
    source: str = "memory"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "fact_or_preference": self.fact_or_preference,
            "category": self.category,
            "confidence": round(self.confidence, 2),
            "source": self.source,
        }


@dataclass(frozen=True)
class ToolCandidate:
    """Candidata a herramienta evaluada por el planner con conocimiento completo de capacidades y limitaciones."""

    tool_name: str
    operation: str
    capability: str
    score: float
    match_reason: str
    minimum_autonomy_level: AutonomyLevel = AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION
    declared_risk: TaskActionRisk = TaskActionRisk.LOW_RISK
    reversibility: str = "REVERSIBLE"
    requires_confirmation: bool = False
    audit_requirement: str = "BASIC"
    limitations: str = ""
    is_available: bool = True
    is_authorized: bool = True
    is_safe_alternative: bool = False
    discard_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "operation": self.operation,
            "capability": self.capability,
            "score": round(self.score, 2),
            "match_reason": self.match_reason,
            "minimum_autonomy_level": self.minimum_autonomy_level.label,
            "declared_risk": self.declared_risk.value,
            "reversibility": self.reversibility,
            "requires_confirmation": self.requires_confirmation,
            "audit_requirement": self.audit_requirement,
            "limitations": self.limitations,
            "is_available": self.is_available,
            "is_authorized": self.is_authorized,
            "is_safe_alternative": self.is_safe_alternative,
            "discard_reason": self.discard_reason,
        }


@dataclass(frozen=True)
class ProposedStep:
    """Paso propuesto por el planner dentro de un plan declarativo."""

    step_id: str
    tool_name: str
    operation: str
    parameters: dict[str, Any] = field(default_factory=dict)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    rationale: str = ""
    evidence_used: tuple[str, ...] = field(default_factory=tuple)
    discarded_alternatives: tuple[str, ...] = field(default_factory=tuple)
    minimum_autonomy_level: AutonomyLevel = AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION
    declared_risk: TaskActionRisk = TaskActionRisk.LOW_RISK
    reversibility: str = "REVERSIBLE"
    requires_confirmation: bool = False
    limitations: str = ""
    is_safe_alternative: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "parameters": self.parameters,
            "dependencies": list(self.dependencies),
            "rationale": self.rationale,
            "evidence_used": list(self.evidence_used),
            "discarded_alternatives": list(self.discarded_alternatives),
            "minimum_autonomy_level": self.minimum_autonomy_level.label,
            "declared_risk": self.declared_risk.value,
            "reversibility": self.reversibility,
            "requires_confirmation": self.requires_confirmation,
            "limitations": self.limitations,
            "is_safe_alternative": self.is_safe_alternative,
        }


@dataclass(frozen=True)
class ToolPlanProposal:
    """Propuesta inmutable de plan estructurado generada por el Controlled Tool Planner.

    REGLA FUNDAMENTAL:
    Este objeto es ÚNICAMENTE una propuesta declarativa.
    Debe ser validado por AutonomyPolicy antes de ser ejecutado por el SecureExecutionPipeline.
    """

    plan_id: str
    intent: str
    context: dict[str, Any]
    evidence_applied: tuple[MemoryEvidence, ...]
    proposed_steps: tuple[ProposedStep, ...]
    discarded_tools_summary: dict[str, str] = field(default_factory=dict)
    planning_context: PlanningContext | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        intent: str,
        context: dict[str, Any],
        evidence_applied: list[MemoryEvidence],
        proposed_steps: list[ProposedStep],
        discarded_tools_summary: dict[str, str] | None = None,
        planning_context: PlanningContext | None = None,
        plan_id: str | None = None,
    ) -> "ToolPlanProposal":
        return cls(
            plan_id=plan_id or f"plan_{uuid.uuid4().hex[:12]}",
            intent=intent,
            context=dict(context),
            evidence_applied=tuple(evidence_applied),
            proposed_steps=tuple(proposed_steps),
            discarded_tools_summary=dict(discarded_tools_summary or {}),
            planning_context=planning_context,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "intent": self.intent,
            "context_keys": list(self.context.keys()),
            "evidence_applied": [e.to_dict() for e in self.evidence_applied],
            "proposed_steps": [s.to_dict() for s in self.proposed_steps],
            "discarded_tools_summary": self.discarded_tools_summary,
            "planning_context": self.planning_context.to_dict() if self.planning_context else None,
            "created_at": self.created_at.isoformat(),
        }
