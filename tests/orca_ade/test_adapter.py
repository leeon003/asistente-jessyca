"""Tests del Adapter de Integración de ORCA + ADE: ciclo de vida y contratos."""

from __future__ import annotations

import asyncio
import pytest

from core.integration.models import IntegrationContext, IntegrationStatus
from core.orca_ade.adapter import OrcaAdeAdapter
from core.orca_ade.models import OrcaAdeMode, ProposalActionType
from core.security import RiskLevel


class TestOrcaAdeAdapter:
    """Pruebas funcionales del adapter y control de modos."""

    def test_rejection_of_active_mode_in_phase1(self) -> None:
        with pytest.raises(RuntimeError, match="ACTIVE is strictly forbidden in Phase 1"):
            OrcaAdeAdapter(mode="ACTIVE")

        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        with pytest.raises(RuntimeError, match="ACTIVE is strictly forbidden in Phase 1"):
            adapter.set_mode("ACTIVE")

    def test_lifecycle_and_health_check(self) -> None:
        async def _test() -> None:
            adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
            init_ok = await adapter.initialize()
            assert init_ok is True
            assert adapter.status == IntegrationStatus.READY

            health = await adapter.health_check()
            assert health.is_healthy is True
            assert health.details["mode"] == "LAB"

            await adapter.shutdown()
            assert adapter.status == IntegrationStatus.AVAILABLE

        asyncio.run(_test())

    def test_mode_switching_between_lab_and_off(self) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        assert adapter.mode == OrcaAdeMode.LAB

        adapter.set_mode(OrcaAdeMode.OFF)
        assert adapter.mode == OrcaAdeMode.OFF
        assert adapter.status == IntegrationStatus.DISABLED

        adapter.set_mode(OrcaAdeMode.SHADOW)
        assert adapter.mode == OrcaAdeMode.SHADOW
        assert adapter.status == IntegrationStatus.READY

    def test_proposal_contract_generation(self) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        proposal = adapter.create_proposal(
            capability="worktree_isolation",
            action_type=ProposalActionType.CREATE_WORKTREE,
            title="Create task branch",
            description="Isolate task in temporary worktree",
            estimated_risk=RiskLevel.SAFE,
        )
        assert proposal.proposal_id.startswith("orca_prop_")
        assert proposal.action_type == ProposalActionType.CREATE_WORKTREE
        assert proposal.estimated_risk == RiskLevel.SAFE
        p_dict = proposal.to_dict()
        assert p_dict["action_type"] == "CREATE_WORKTREE"

    def test_adapter_execute_with_jde_allow(self) -> None:
        async def _test() -> None:
            adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
            ctx = IntegrationContext(
                session_id="session_test",
                parameters={"task_id": "t1"},
                metadata={"jde_decision": "ALLOW"},
            )
            res = await adapter.execute("worktree_isolation", ctx)
            assert res.executed is True
            assert res.verified is True
            assert res.output["status"] == "ALLOWED"

        asyncio.run(_test())

    def test_adapter_execute_when_off(self) -> None:
        async def _test() -> None:
            adapter = OrcaAdeAdapter(mode=OrcaAdeMode.OFF)
            ctx = IntegrationContext(session_id="session_test")
            res = await adapter.execute("worktree_isolation", ctx)
            assert res.executed is False
            assert "is OFF" in str(res.error)

        asyncio.run(_test())
