"""Paquete de Diálogo de Acción Natural y Conciencia de Capacidades (core/dialogue - Fase 52.1)."""

from __future__ import annotations

from core.dialogue.action_planner import (
    ActionPlanner,
    ActionPlanningError,
    ActionPlanningValidationError,
)
from core.dialogue.action_recovery import (
    ActionFailureCategory,
    ActionRecoveryContext,
    ActionRecoveryState,
    RecoveryUserIntent,
    build_recovery_prompt,
    classify_failure_category,
    classify_recovery_intent,
    format_friendly_error,
)
from core.dialogue.action_sequence import (
    ActionSequence,
    ActionSequenceStatus,
    ActionStep,
    ActionStepStatus,
    SequenceFailurePolicy,
    StepPlanner,
)
from core.dialogue.capability_awareness import CapabilityAwarenessEngine
from core.dialogue.conversational_action_controller import (
    ConversationalActionController,
    ConversationalActionResult,
    ConversationalActionStatus,
    PendingActionConfirmation,
    classify_confirmation_intent,
    get_conversational_action_controller,
)
from core.dialogue.conversational_intent_continuity import (
    ActionContext,
    ContinuityResolutionResult,
    ConversationalIntentContinuityResolver,
    format_display_entity,
    get_continuity_resolver,
)
from core.dialogue.dialogue_manager import NaturalActionDialogueManager
from core.dialogue.dialogue_models import (
    ActionPlan,
    ActionPlanStep,
    CapabilityAssessment,
    CapabilityLevel,
    DialogueActionType,
    DialogueDecision,
)
from core.dialogue.feedback_builder import (
    FeedbackBuilder,
    FeedbackStatus,
    NaturalFeedbackResponse,
    get_feedback_builder,
)

__all__ = [
    "ActionContext",
    "ActionFailureCategory",
    "ActionPlan",
    "ActionPlanStep",
    "ActionPlanner",
    "ActionPlanningError",
    "ActionPlanningValidationError",
    "ActionRecoveryContext",
    "ActionRecoveryState",
    "ActionSequence",
    "ActionSequenceStatus",
    "ActionStep",
    "ActionStepStatus",
    "CapabilityAssessment",
    "CapabilityAwarenessEngine",
    "CapabilityLevel",
    "ContinuityResolutionResult",
    "ConversationalActionController",
    "ConversationalActionResult",
    "ConversationalActionStatus",
    "ConversationalIntentContinuityResolver",
    "DialogueActionType",
    "DialogueDecision",
    "FeedbackBuilder",
    "FeedbackStatus",
    "NaturalActionDialogueManager",
    "NaturalFeedbackResponse",
    "PendingActionConfirmation",
    "RecoveryUserIntent",
    "SequenceFailurePolicy",
    "StepPlanner",
    "build_recovery_prompt",
    "classify_confirmation_intent",
    "classify_failure_category",
    "classify_recovery_intent",
    "format_display_entity",
    "format_friendly_error",
    "get_continuity_resolver",
    "get_conversational_action_controller",
    "get_feedback_builder",
]
