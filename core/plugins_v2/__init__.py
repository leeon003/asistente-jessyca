"""Paquete del Ecosistema de Plugins 2.0 para JESSYCA (core.plugins_v2 - Fase 28).

Exporta las clases, modelos y validadores del ecosistema formal de plugins.
"""

from __future__ import annotations

from core.plugins_v2.ecosystem_manager import (
    PluginEcosystemManager,
    get_plugin_ecosystem_manager,
)
from core.plugins_v2.ecosystem_models import (
    PluginManifest2,
    PluginStatus,
    PluginToolDeclaration,
    PluginValidationReport,
    ValidationStageResult,
)
from core.plugins_v2.ecosystem_validator import (
    FORBIDDEN_PERMISSIONS,
    PluginEcosystemValidationError,
    PluginEcosystemValidator,
)

__all__ = [
    "PluginStatus",
    "PluginToolDeclaration",
    "PluginManifest2",
    "ValidationStageResult",
    "PluginValidationReport",
    "FORBIDDEN_PERMISSIONS",
    "PluginEcosystemValidationError",
    "PluginEcosystemValidator",
    "PluginEcosystemManager",
    "get_plugin_ecosystem_manager",
]
