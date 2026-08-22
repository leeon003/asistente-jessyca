"""Paquete de Agente Local Unificado de JESSYCA (core.local_agent - Fase 45).

Exporta las clases, modelos e interfaces para la experiencia de usuario unificada.
"""

from __future__ import annotations

from core.local_agent.conversation_context import (
    ConversationContextManager,
)
from core.local_agent.conversation_models import (
    ContextItem,
    ConversationSession,
    ConversationStatus,
    DialogueState,
    ShortTermMemory,
    TurnRole,
)
from core.local_agent.local_agent import (
    JessycaLocalAgent,
    get_jessyca_local_agent,
)
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    ConversationTurn,
    InputModality,
    JessycaRequest,
    JessycaResponse,
    LocalAgentMetrics,
)
from core.local_agent.multimodal_interface import (
    MultimodalProcessor,
)
from core.local_agent.voice_interface import (
    LocalVoiceInterface,
)

__all__ = [
    # Modelos y Enums
    "InputModality",
    "AgentExecutionState",
    "LocalAgentMetrics",
    "JessycaRequest",
    "ConversationTurn",
    "JessycaResponse",
    "ContextItem",
    "ConversationSession",
    "ShortTermMemory",
    "ConversationStatus",
    "DialogueState",
    "TurnRole",
    # Módulos y Adaptadores
    "ConversationContextManager",
    "MultimodalProcessor",
    "LocalVoiceInterface",
    "JessycaLocalAgent",
    "get_jessyca_local_agent",
]
