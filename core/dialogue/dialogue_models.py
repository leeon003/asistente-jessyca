"""Modelos de datos formales para el Diálogo de Acción Natural y Conciencia de Capacidades (Fase 52.1).

Define:
- CapabilityLevel (FULL, PARTIAL, NONE)
- DialogueActionType (DIRECT_ACTION, CLARIFICATION, PARTIAL_CAPABILITY, UNSUPPORTED_CAPABILITY, etc.)
- CapabilityAssessment
- ActionPlan y ActionPlanStep
- DialogueDecision
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CapabilityLevel(StrEnum):
    """Nivel de cobertura de capacidades del sistema para una petición."""

    FULL = "FULL"
    PARTIAL = "PARTIAL"
    NONE = "NONE"


class DialogueActionType(StrEnum):
    """Tipo de acción o respuesta conversacional requerida."""

    CONVERSATIONAL = "CONVERSATIONAL"
    DIRECT_ACTION = "DIRECT_ACTION"
    CLARIFICATION = "CLARIFICATION"
    PARTIAL_CAPABILITY = "PARTIAL_CAPABILITY"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    EXPLAIN_CAPABILITY = "EXPLAIN_CAPABILITY"
    EXECUTION_SUCCESS = "EXECUTION_SUCCESS"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class CapabilityAssessment(BaseModel):
    """Resultado de la evaluación de capacidades del sistema frente a una orden."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    intent: str
    level: CapabilityLevel = CapabilityLevel.NONE
    supported: bool = False
    supported_aspects: list[str] = Field(default_factory=list)
    unsupported_aspects: list[str] = Field(default_factory=list)
    explanation: str | None = None
    requires_clarification: bool = False
    clarification_prompt: str | None = None
    skill_id: str | None = None
    tool_name: str | None = None


class ActionPlanStep(BaseModel):
    """Paso individual estructurado dentro de un plan de acción."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    step_number: int = 1
    intent: str
    skill_id: str
    tool_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class ActionPlan(BaseModel):
    """Plan de acción estructurado para peticiones simples o compuestas."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    plan_id: str = Field(default_factory=lambda: f"plan-{uuid.uuid4().hex[:8]}")
    intent: str
    steps: list[ActionPlanStep] = Field(default_factory=list)
    summary_speech: str = ""
    is_composite: bool = False


class DialogueDecision(BaseModel):
    """Decisión dialógica previa a la ejecución o formulación de respuesta conversacional."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    action_type: DialogueActionType
    capability_level: CapabilityLevel
    response_text: str
    pre_action_speech: str | None = None
    clarification_question: str | None = None
    expected_slot: str | None = None
    action_plan: ActionPlan | None = None
    is_terminal: bool = False
