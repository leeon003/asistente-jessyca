"""Tests de Manejo de Fallos y Fallback: ORCA + ADE (Fase 1)."""

from __future__ import annotations

import asyncio
import pytest

from core.integration.models import IntegrationContext
from core.orca_ade.adapter import OrcaAdeAdapter
from core.orca_ade.models import OrcaAdeMode, ProposalActionType


class TestOrcaAdeFailures:
    """Verifica que el sistema falle de forma segura y controlada."""

    def test_unsupported_capability_fails_gracefully(self) -> None:
        async def _test() -> None:
            adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
            ctx = IntegrationContext(session_id="test_fail")
            res = await adapter.execute("unsupported_capability", ctx)
            assert res.executed is False
            assert "not supported" in str(res.error)

        asyncio.run(_test())

    def test_empty_or_null_path_fails_validation(self) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        with pytest.raises(ValueError, match="cannot be empty"):
            adapter.validate_and_confine_path("")

    def test_null_byte_path_fails_validation(self) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        with pytest.raises(ValueError, match="Null bytes"):
            adapter.validate_and_confine_path("dir\x00ectory")

    def test_evaluation_when_mode_is_off_returns_skipped(self) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.OFF)
        proposal = adapter.create_proposal(
            capability="worktree_isolation",
            action_type=ProposalActionType.CREATE_WORKTREE,
            title="Disabled test",
            description="Should skip",
        )
        res = adapter.evaluate_proposal(proposal)
        assert res.status == "SKIPPED"
        assert "currently OFF" in res.errors[0]
