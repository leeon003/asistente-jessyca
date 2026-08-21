"""Módulo y Framework de Habilidades (Skills) de JESSYCA 3.0 (Fase 28.0).

Proporciona tanto el Skill Framework modular (SkillDefinition, SkillRegistry, SkillManager,
SkillRouter, SkillRuntime, SkillContext, SkillResult) como las implementaciones retrocompatibles
(BaseSkill, AbrirAplicacion, CerrarAplicacion, BuscarArchivo, SKILLS_DISPONIBLES).
"""

from __future__ import annotations

from skills.apps import AbrirAplicacion, CerrarAplicacion
from skills.archivos import BuscarArchivo
from skills.base_skill import BaseSkill
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

# Registro retrocompatible de skills disponibles en el sistema
SKILLS_DISPONIBLES = {
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
    # Skill Framework 2.0 (Fases 28.0 - 28.5)
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
