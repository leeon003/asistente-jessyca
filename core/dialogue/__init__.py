"""Paquete de Diálogo de Acción Natural y Conciencia de Capacidades (core/dialogue - Fase 52.1)."""

from __future__ import annotations

from core.dialogue.action_planner import ActionPlanner
from core.dialogue.capability_awareness import CapabilityAwarenessEngine
from core.dialogue.dialogue_manager import NaturalActionDialogueManager
from core.dialogue.dialogue_models import (
    ActionPlan,
    ActionPlanStep,
    CapabilityAssessment,
    CapabilityLevel,
    DialogueActionType,
    DialogueDecision,
)

__all__ = [
    "ActionPlan",
    "ActionPlanStep",
    "ActionPlanner",
    "CapabilityAssessment",
    "CapabilityAwarenessEngine",
    "CapabilityLevel",
    "DialogueActionType",
    "DialogueDecision",
    "NaturalActionDialogueManager",
]
