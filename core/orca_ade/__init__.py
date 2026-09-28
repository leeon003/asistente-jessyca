"""Submódulo de Integración de ORCA + ADE (Fase 2 — Controlled Integration).

Exporta los contratos y adaptadores experimentales y gobernados subordinados a JDE.
"""

from __future__ import annotations

from core.orca_ade.adapter import OrcaAdeAdapter
from core.orca_ade.models import (
    AgentLifecycle,
    AgentState,
    CommandSecurityGuard,
    NetworkSecurityGuard,
    OrcaAdeEvaluationResult,
    OrcaAdeMode,
    OrcaAdeProposal,
    OrcaPermission,
    OrcaResultContract,
    OrcaTaskContract,
    ProposalActionType,
    validate_agent_permissions,
)
from core.orca_ade.orchestrator import OrcaGovernedOrchestrator
from core.orca_ade.shadow import OrcaAdeShadowEvaluator, ShadowEvaluationRecord

__all__ = [
    "OrcaAdeAdapter",
    "OrcaAdeMode",
    "OrcaAdeProposal",
    "ProposalActionType",
    "OrcaAdeEvaluationResult",
    "OrcaAdeShadowEvaluator",
    "ShadowEvaluationRecord",
    "OrcaGovernedOrchestrator",
    "OrcaTaskContract",
    "OrcaResultContract",
    "AgentLifecycle",
    "AgentState",
    "OrcaPermission",
    "validate_agent_permissions",
    "CommandSecurityGuard",
    "NetworkSecurityGuard",
]
