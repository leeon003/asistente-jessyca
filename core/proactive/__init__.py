"""Paquete de Inteligencia Proactiva Segura para JESSYCA 3.0 (core.proactive - Fase 44).

Exporta las clases, modelos, adaptadores de fuentes, motores de relevancia y anti-spam,
controles de usuario y pipelines gobernados por políticas de riesgo y autonomía.
"""

from __future__ import annotations

from core.proactive.anti_spam_engine import (
    AntiSpamEngine,
)
from core.proactive.event_sources import (
    ApplicationStateEventSource,
    BrowserEventSource,
    CalendarEventSource,
    EventSourceAdapter,
    EventSourceHub,
    FilesEventSource,
    GenericEventSourceAdapter,
    SchedulerEventSource,
    SystemEventsSource,
    UserInteractionEventSource,
)
from core.proactive.event_validator import (
    ProactiveEventValidationError,
    ProactiveEventValidator,
)
from core.proactive.proactive_assistant import (
    ProactiveAssistant,
    get_proactive_assistant,
)
from core.proactive.proactive_models import (
    AntiSpamDecision,
    EventSourceType,
    ProactiveActionType,
    ProactiveEvent,
    ProactiveEventType,
    ProactiveExecutionResult,
    ProactivePolicyDecision,
    ProactiveSuggestion,
    RelevanceAssessment,
    UserControlSettings,
)
from core.proactive.proactive_pipeline import (
    ProactivePipeline,
)
from core.proactive.proactive_policy import (
    ProactivePolicyEngine,
)
from core.proactive.proactive_security import (
    ProactiveSecurityGuard,
)
from core.proactive.relevance_engine import (
    RelevanceEngine,
)
from core.proactive.user_control import (
    ProactiveUserControl,
)

__all__ = [
    # Modelos y Enums
    "EventSourceType",
    "ProactiveEventType",
    "ProactiveActionType",
    "ProactiveEvent",
    "RelevanceAssessment",
    "AntiSpamDecision",
    "UserControlSettings",
    "ProactiveSuggestion",
    "ProactivePolicyDecision",
    "ProactiveExecutionResult",
    # Validadores y Seguridad
    "ProactiveEventValidator",
    "ProactiveEventValidationError",
    "ProactiveSecurityGuard",
    # Motores
    "RelevanceEngine",
    "AntiSpamEngine",
    "ProactiveUserControl",
    "ProactivePolicyEngine",
    "ProactivePipeline",
    "ProactiveAssistant",
    "get_proactive_assistant",
    # Fuentes de eventos
    "EventSourceAdapter",
    "GenericEventSourceAdapter",
    "SchedulerEventSource",
    "ApplicationStateEventSource",
    "CalendarEventSource",
    "FilesEventSource",
    "BrowserEventSource",
    "SystemEventsSource",
    "UserInteractionEventSource",
    "EventSourceHub",
]
