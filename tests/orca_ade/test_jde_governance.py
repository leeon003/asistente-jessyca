"""Tests de Subordinación y Gobernanza Única del JDE: ORCA + ADE (Fase 1)."""

from __future__ import annotations

import pytest

from core.orca_ade.adapter import OrcaAdeAdapter
from core.orca_ade.models import OrcaAdeMode, ProposalActionType
from core.security import RiskLevel


class TestOrcaAdeJdeGovernance:
    """Verifica que JDE sea la única autoridad decisoria y prevalezca siempre."""

    def test_jde_allow_authorizes_proposal(self) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        proposal = adapter.create_proposal(
            capability="worktree_isolation",
            action_type=ProposalActionType.CREATE_WORKTREE,
            title="Safe refactoring proposal",
            description="Isolate refactor in branch",
            estimated_risk=RiskLevel.SAFE,
        )
        res = adapter.evaluate_proposal(proposal, jde_decision_override="ALLOW")
        assert res.status == "ALLOWED"
        assert res.jde_decision == "ALLOW"
        assert res.side_effects_produced == 0

    def test_jde_deny_blocks_proposal(self) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        proposal = adapter.create_proposal(
            capability="worktree_isolation",
            action_type=ProposalActionType.CREATE_WORKTREE,
            title="Refactoring proposal",
            description="Task rejected by JDE policy",
            estimated_risk=RiskLevel.SAFE,
        )
        res = adapter.evaluate_proposal(proposal, jde_decision_override="DENY")
        assert res.status == "DENIED"
        assert res.jde_decision == "DENY"

    def test_missing_governance_decision_requires_governance(self) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        proposal = adapter.create_proposal(
            capability="worktree_isolation",
            action_type=ProposalActionType.CREATE_WORKTREE,
            title="Proposal without JDE override",
            description="Pending authority evaluation",
            estimated_risk=RiskLevel.SAFE,
        )
        # Sin decisión explícita, se requiere gobernanza y el status es DENIED
        res = adapter.evaluate_proposal(proposal, jde_decision_override=None)
        assert res.status == "DENIED"
        assert res.jde_decision == "GOVERNANCE_REQUIRED"

    def test_jde_decision_always_prevails(self) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        proposal = adapter.create_proposal(
            capability="parallel_agent_dispatch",
            action_type=ProposalActionType.COORDINATE_SUBTASKS,
            title="Parallel dispatch",
            description="Orca suggests 4 agents",
            estimated_risk=RiskLevel.SAFE,
        )
        # JDE dictamina DENY por restricción de recursos
        res = adapter.evaluate_proposal(proposal, jde_decision_override="DENY")
        assert res.status == "DENIED"
