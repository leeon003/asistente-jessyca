"""Módulo y Framework de Habilidades (Skills) de JESSYCA 3.0 (Fases 28.0 - 28.7).

Proporciona tanto el Skill Framework modular (SkillDefinition, SkillRegistry, SkillManager,
SkillRouter, SkillRuntime, SkillSecuritySandbox) como las primeras Production Skills
(windows.apps, windows.screenshot, files.search, browser.search) y soporte retrocompatible.
"""

from __future__ import annotations

from skills.apps import AbrirAplicacion, CerrarAplicacion
from skills.apps_skill import WindowsAppsSkill
from skills.archivos import BuscarArchivo
from skills.base_skill import BaseSkill
from skills.browser_search_skill import BrowserSearchSkill
from skills.file_search_skill import FilesSearchSkill
from skills.screenshot_skill import WindowsScreenshotSkill
from skills.skill_manager import (
    SkillManager,
    get_skill_manager,
)
from skills.skill_models import (
    ALLOWED_SKILL_CAPABILITIES,
    SkillCapability,
    SkillContext,
    SkillDefinition,
    SkillManifest,
    SkillPermission,
    SkillResult,
    SkillStatus,
)
from skills.skill_registry import (
    SkillRegistry,
    get_skill_registry,
)
from skills.skill_router import (
    SkillRouteDecision,
    SkillRouter,
    get_skill_router,
)
from skills.skill_runtime import (
    SkillRuntime,
)
from skills.skill_sandbox import (
    SkillRecursionLimitError,
    SkillSandboxExecutionResult,
    SkillSandboxSecurityError,
    SkillSecuritySandbox,
    SkillSecurityViolationError,
    SkillUndeclaredToolError,
    UntrustedDataWrapper,
)
from skills.skill_validator import (
    SkillValidationError,
    SkillValidator,
)

# Catálogo oficial de Skills de Producción registradas en el sistema
SKILLS_DISPONIBLES = {
    # Production Skills 1.0 (Fase 28.7)
    "windows.apps": WindowsAppsSkill(),
    "windows.screenshot": WindowsScreenshotSkill(),
    "files.search": FilesSearchSkill(),
    "browser.search": BrowserSearchSkill(),
    # Legacy aliases retrocompatibles
    "abrir_aplicacion": AbrirAplicacion(),
    "cerrar_aplicacion": CerrarAplicacion(),
    "buscar_archivo": BuscarArchivo(),
}

# Auto-registro en el SkillRegistry global
_default_registry = get_skill_registry()
for _name, _skill_inst in SKILLS_DISPONIBLES.items():
    _default_registry.register_skill(_skill_inst)

__all__ = [
    # Legacy & Implementaciones Base
    "BaseSkill",
    "AbrirAplicacion",
    "CerrarAplicacion",
    "BuscarArchivo",
    "SKILLS_DISPONIBLES",
    # Production Skills (Fase 28.7)
    "WindowsAppsSkill",
    "WindowsScreenshotSkill",
    "FilesSearchSkill",
    "BrowserSearchSkill",
    # Skill Framework 2.0 (Fases 28.0 - 28.6)
    "SkillStatus",
    "SkillCapability",
    "ALLOWED_SKILL_CAPABILITIES",
    "SkillPermission",
    "SkillManifest",
    "SkillDefinition",
    "SkillContext",
    "SkillResult",
    "SkillValidator",
    "SkillValidationError",
    "SkillRegistry",
    "get_skill_registry",
    "SkillRouter",
    "SkillRouteDecision",
    "get_skill_router",
    "SkillRuntime",
    "SkillManager",
    "get_skill_manager",
    "SkillSecuritySandbox",
    "SkillSandboxExecutionResult",
    "UntrustedDataWrapper",
    "SkillSandboxSecurityError",
    "SkillUndeclaredToolError",
    "SkillRecursionLimitError",
    "SkillSecurityViolationError",
]
