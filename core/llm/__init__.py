"""Paquete de integración y abstracción Multi-LLM para Jessyca Windows MCP (core.llm).

Exporta las clases fundamentales para la gestión, registro, inferencia, enrutamiento, VRAM, visión, Tool Calling y Consenso Multi-LLM.
"""

from __future__ import annotations

from core.llm.consensus_engine import (
    DEFAULT_CONSENSUS_ENSEMBLE,
    ConsensusEngine,
    get_consensus_engine,
)
from core.llm.consensus_policy import (
    ConsensusPolicy,
    ConsensusStrategy,
)
from core.llm.consensus_result import (
    ConsensusResult,
    ConsensusStatus,
    ModelVote,
)
from core.llm.exceptions import (
    DuplicateModelError,
    InferenceError,
    LLMError,
    ModelNotFoundError,
    ModelRegistrationError,
    ProviderConnectionError,
    ProviderError,
    ProviderTimeoutError,
)
from core.llm.inference import (
    FakeLLMProvider,
    InferenceRequest,
    InferenceResponse,
    LLMProvider,
    OllamaProvider,
)
from core.llm.model_lifecycle import (
    LoadedModelInfo,
    ModelLifecycleManager,
    ModelStatus,
    get_model_lifecycle_manager,
)
from core.llm.model_manager import (
    ModelManager,
    get_model_manager,
)
from core.llm.model_profile import (
    ModelProfile,
)
from core.llm.model_registry import (
    ModelRegistry,
    get_default_built_in_profiles,
    get_model_profile,
)
from core.llm.model_router import (
    ModelRouter,
    get_model_router,
)
from core.llm.routing_policy import (
    RoutingContext,
    RoutingPolicy,
    TaskComplexity,
    TaskType,
)
from core.llm.tool_calling import (
    ToolCall,
    ToolCallAdapter,
    ToolCallParser,
    ToolCallValidationVerdict,
    ToolCallValidator,
)
from core.llm.vision_models import (
    VisionAnalysis,
    VisionObservation,
)
from core.llm.vision_provider import (
    DEFAULT_VISION_MODEL,
    VisionProvider,
)
from core.llm.vram_manager import (
    DEFAULT_RESERVED_SYSTEM_VRAM_MB,
    DEFAULT_TOTAL_VRAM_MB,
    ModelUsageRecord,
    VRAMBudgetReport,
    VRAMGovernor,
)

__all__ = [
    # Excepciones
    "LLMError",
    "ModelNotFoundError",
    "ModelRegistrationError",
    "DuplicateModelError",
    "InferenceError",
    "ProviderError",
    "ProviderConnectionError",
    "ProviderTimeoutError",
    # Perfil y Registro
    "ModelProfile",
    "ModelRegistry",
    "get_default_built_in_profiles",
    "get_model_profile",
    # Administrador
    "ModelManager",
    "get_model_manager",
    # Inferencia y Proveedores
    "InferenceRequest",
    "InferenceResponse",
    "LLMProvider",
    "OllamaProvider",
    "FakeLLMProvider",
    # Enrutamiento Dinámico
    "TaskType",
    "TaskComplexity",
    "RoutingContext",
    "RoutingPolicy",
    "ModelRouter",
    "get_model_router",
    # Ciclo de Vida y Gobernanza VRAM
    "ModelStatus",
    "LoadedModelInfo",
    "ModelLifecycleManager",
    "get_model_lifecycle_manager",
    "DEFAULT_TOTAL_VRAM_MB",
    "DEFAULT_RESERVED_SYSTEM_VRAM_MB",
    "VRAMBudgetReport",
    "ModelUsageRecord",
    "VRAMGovernor",
    # Pipeline de Visión Multimodal
    "DEFAULT_VISION_MODEL",
    "VisionAnalysis",
    "VisionObservation",
    "VisionProvider",
    # Tool Calling Robusto
    "ToolCall",
    "ToolCallValidationVerdict",
    "ToolCallParser",
    "ToolCallValidator",
    "ToolCallAdapter",
    # Consenso Multi-LLM (Fase 10)
    "ConsensusStatus",
    "ModelVote",
    "ConsensusResult",
    "ConsensusStrategy",
    "ConsensusPolicy",
    "ConsensusEngine",
    "get_consensus_engine",
    "DEFAULT_CONSENSUS_ENSEMBLE",
]
