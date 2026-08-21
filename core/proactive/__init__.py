"""Paquete de Asistencia Proactiva Segura para JESSYCA 3.0 (core.proactive - Fase 27).

Exporta las clases y modelos para la gestión de eventos proactivos gobernados por políticas de riesgo.
"""

from __future__ import annotations

from core.proactive.event_validator import (
    ProactiveEventValidationError,
    ProactiveEventValidator,
)
from core.proactive.proactive_assistant import (
    ProactiveAssistant,
    get_proactive_assistant,
)
from core.proactive.proactive_models import (
    ProactiveActionType,
    ProactiveEvent,
    ProactiveEventType,
    ProactiveExecutionResult,
    ProactivePolicyDecision,
)
from core.proactive.proactive_policy import (
    ProactivePolicyEngine,
)

__all__ = [
    "ProactiveEventType",
    "ProactiveActionType",
    "ProactiveEvent",
    "ProactivePolicyDecision",
    "ProactiveExecutionResult",
    "ProactiveEventValidator",
    "ProactiveEventValidationError",
    "ProactivePolicyEngine",
    "ProactiveAssistant",
    "get_proactive_assistant",
]
