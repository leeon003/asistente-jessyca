"""Modelos formales de datos para el motor de intenciones agéntico (core/intent/models.py).

Inspirado en los patrones de SAI Rust (Plan Mode y Descomposición Multi-Acción):
- Clasificación entre conversación, acción simple y plan multi-paso.
- Soporte para planes acíclicos gobernados.
- Contrato compatible hacia atrás con la tupla (intent, params, is_ambiguous).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class IntentType(StrEnum):
    """Categorías formales de intención del usuario."""

    CONVERSATION = "conversation"
    SINGLE_ACTION = "single_action"
    MULTI_STEP_PLAN = "multi_step_plan"
    CLARIFICATION_NEEDED = "clarification_needed"
    RESEARCH = "research"
    CANCELLATION = "cancellation"
    CONFIRMATION = "confirmation"


@dataclass(frozen=True)
class PlannedActionStep:
    """Paso unitario inmutable dentro de un plan de ejecución."""

    step_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    skill_name: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    expected_outcome: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "skill_name": self.skill_name,
            "parameters": dict(self.parameters),
            "description": self.description,
            "depends_on": list(self.depends_on),
            "expected_outcome": self.expected_outcome,
        }


@dataclass(frozen=True)
class UserGoalInterpretation:
    """Interpretación estructurada y formal de la meta del usuario."""

    intent_type: IntentType
    goal_summary: str
    spoken_feedback: str
    steps: tuple[PlannedActionStep, ...] = field(default_factory=tuple)
    is_ambiguous: bool = False
    clarification_question: str | None = None
    resolved_entities: dict[str, Any] = field(default_factory=dict)
    raw_confidence: float = 1.0
    plan_id: str = field(default_factory=lambda: f"plan-{uuid.uuid4().hex[:10]}")

    @property
    def is_executable(self) -> bool:
        return self.intent_type in (IntentType.SINGLE_ACTION, IntentType.MULTI_STEP_PLAN, IntentType.RESEARCH) and len(self.steps) > 0 and not self.requires_clarification

    @property
    def is_multistep(self) -> bool:
        return self.intent_type == IntentType.MULTI_STEP_PLAN and len(self.steps) > 1

    @property
    def requires_clarification(self) -> bool:
        return self.is_ambiguous or self.intent_type == IntentType.CLARIFICATION_NEEDED

    @property
    def confidence(self) -> float:
        return self.raw_confidence

    @property
    def primary_intent(self) -> str:
        if self.intent_type == IntentType.CONVERSATION:
            return "general_query"
        if self.intent_type == IntentType.CLARIFICATION_NEEDED:
            return "clarification_request"
        if self.intent_type == IntentType.RESEARCH:
            return "multistep_research"
        if self.intent_type == IntentType.CANCELLATION:
            return "cancel_task"
        if self.intent_type == IntentType.CONFIRMATION:
            return "confirm_action"
        if self.is_multistep:
            return "multistep_compound"
        if self.steps:
            skill = self.steps[0].skill_name
            # Normalizar a intenciones conocidas si es necesario
            if skill == "windows.apps":
                return "open_application"
            elif skill == "browser.search":
                return "browser_search"
            elif skill == "browser.open":
                return "open_browser"
            elif skill == "browser.youtube":
                return "youtube_search"
            elif skill == "system.volume" or skill == "windows.audio":
                return "control_audio"
            elif skill == "files.create":
                return "create_file"
            elif skill == "files.read":
                return "read_file"
            return skill
        return "general_query"

    @property
    def domains_involved(self) -> tuple[str, ...]:
        domains = set()
        for s in self.steps:
            if "." in s.skill_name:
                domains.add(s.skill_name.split(".")[0])
        return tuple(sorted(domains))

    @property
    def unified_parameters(self) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for s in self.steps:
            params.update(s.parameters)
        return params

    def to_legacy_tuple(self) -> tuple[str, dict[str, Any], bool]:
        """Convierte la interpretación a la tupla histórica (intent, params, is_ambiguous).

        Garantiza compatibilidad 100% con el pipeline actual de JessycaLocalAgent.
        """
        if self.intent_type == IntentType.CONVERSATION:
            return "general_query", {"query": self.goal_summary}, False

        if self.intent_type == IntentType.CANCELLATION:
            return "cancel_task", {"immediate_response": self.spoken_feedback or "Operación cancelada."}, False

        if self.intent_type == IntentType.CONFIRMATION:
            return "confirm_action", {"confirmed": True}, False

        if self.intent_type == IntentType.RESEARCH:
            return (
                "multistep_research",
                {
                    "topic": self.goal_summary,
                    "query": self.goal_summary,
                    "synthesized_answer": self.spoken_feedback,
                    "steps": [s.to_dict() for s in self.steps],
                },
                False,
            )

        if self.intent_type == IntentType.CLARIFICATION_NEEDED:
            return (
                "clarification_request",
                {
                    "immediate_response": self.clarification_question or "¿Puedes darme más detalles?",
                    "is_ambiguous": True,
                },
                True,
            )

        if not self.steps:
            return "general_query", {"query": self.goal_summary}, self.is_ambiguous

        # Si es un plan de múltiples pasos
        if self.is_multistep:
            return (
                "multistep_compound",
                {
                    "steps": [s.to_dict() for s in self.steps],
                    "__multistep_plan__": [s.to_dict() for s in self.steps],
                    "__plan_id__": self.plan_id,
                    "__goal_summary__": self.goal_summary,
                },
                self.is_ambiguous,
            )

        # Si es de un solo paso:
        first_step = self.steps[0]
        legacy_intent = self.primary_intent
        params = dict(first_step.parameters)
        return legacy_intent, params, self.is_ambiguous


__all__ = [
    "IntentType",
    "PlannedActionStep",
    "UserGoalInterpretation",
]
