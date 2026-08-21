"""Módulo central del Sistema de Niveles de Autonomía (Autonomy Level Model - Etapa 16.2).

Contiene:
- AutonomyLevel: Niveles formales de autonomía (LEVEL_0 a LEVEL_4, sin LEVEL_5).
- AutonomyDecision: Representación inmutable de decisiones de autonomía.
- AutonomyPolicy: Evaluador determinista de políticas con soporte de perfiles declarados.
- AutonomyGovernor: Gobernador singleton thread-safe de estado y prevención de escalado.
- CapabilityAutonomyProfile: Declaración formal por-capability de minimum_level, risk,
  confirmation, reversibility y audit_requirement.
- CapabilityAutonomyRegistry: Catálogo oficial de perfiles de sólo lectura en runtime.
"""

from core.autonomy.autonomous_task_manager import AutonomousTaskManager
from core.autonomy.autonomous_task_models import (
    AutonomousTaskDefinition,
    AutonomousTaskStatus,
)
from core.autonomy.autonomy_decision import AutonomyDecision, AutonomyDecisionValue
from core.autonomy.autonomy_governor import AutonomyGovernor, get_autonomy_governor
from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk
from core.autonomy.autonomy_policy import (
    AutonomyEscalationError,
    AutonomyEvaluationContext,
    AutonomyPolicy,
)
from core.autonomy.capability_autonomy_profile import (
    AuditRequirement,
    CapabilityAutonomyProfile,
    ConfirmationRequirement,
    ReversibilityClass,
)
from core.autonomy.capability_autonomy_registry import (
    CapabilityAutonomyRegistry,
    CapabilityProfileNotFoundError,
    CapabilityRegistryLockedError,
    get_capability_autonomy_registry,
)

__all__ = [
    # Autonomous Tasks (Fase 15)
    "AutonomousTaskDefinition",
    "AutonomousTaskStatus",
    "AutonomousTaskManager",
    # Level model
    "AutonomyLevel",
    "TaskActionRisk",
    # Decision
    "AutonomyDecisionValue",
    "AutonomyDecision",
    # Policy
    "AutonomyPolicy",
    "AutonomyEvaluationContext",
    "AutonomyEscalationError",
    # Governor
    "AutonomyGovernor",
    "get_autonomy_governor",
    # Capability profiles
    "CapabilityAutonomyProfile",
    "ConfirmationRequirement",
    "ReversibilityClass",
    "AuditRequirement",
    # Registry
    "CapabilityAutonomyRegistry",
    "get_capability_autonomy_registry",
    "CapabilityProfileNotFoundError",
    "CapabilityRegistryLockedError",
]
