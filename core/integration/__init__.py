"""Capa de Integraciones (Integration Hub / Adapter Layer) para JESSYCA 4.0.

Exporta el contrato formal para adapters de tecnologías externas, el registro desacoplado,
la frontera de seguridad y el hub central de ejecución con fallback.
"""

from core.integration.adapter import IntegrationAdapter
from core.integration.hub import IntegrationHub, get_integration_hub
from core.integration.models import (
    IntegrationCapability,
    IntegrationContext,
    IntegrationExecutionResult,
    IntegrationHealth,
    IntegrationInfo,
    IntegrationStatus,
)
from core.integration.registry import IntegrationRegistry, get_integration_registry
from core.integration.security_boundary import (
    IntegrationSecurityBoundary,
    sanitize_context_parameters,
)

__all__ = [
    "IntegrationAdapter",
    "IntegrationCapability",
    "IntegrationContext",
    "IntegrationExecutionResult",
    "IntegrationHealth",
    "IntegrationHub",
    "IntegrationInfo",
    "IntegrationRegistry",
    "IntegrationSecurityBoundary",
    "IntegrationStatus",
    "get_integration_hub",
    "get_integration_registry",
    "sanitize_context_parameters",
]
