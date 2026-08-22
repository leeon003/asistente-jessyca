"""Módulo de Colaboración Avanzada Multi-Entidad (core.collaboration - Fase 37)."""

from __future__ import annotations

from core.collaboration.collaboration_engine import CollaborationEngine
from core.collaboration.collaboration_models import (
    CollaborationContext,
    CollaborationContract,
    CollaborationMetrics,
    CollaborationResult,
    CollaborationRole,
    CollaborationState,
    DelegationTargetType,
)
from core.collaboration.collaboration_policy import (
    CollaborationPolicy,
    DelegationVerdict,
)

__all__ = [
    "CollaborationContext",
    "CollaborationContract",
    "CollaborationEngine",
    "CollaborationMetrics",
    "CollaborationPolicy",
    "CollaborationResult",
    "CollaborationRole",
    "CollaborationState",
    "DelegationTargetType",
    "DelegationVerdict",
]
