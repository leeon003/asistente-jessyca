"""Tests de Concurrencia y Estabilidad: ORCA + ADE (Fase 1)."""

from __future__ import annotations

import concurrent.futures
import pytest

from core.orca_ade.adapter import OrcaAdeAdapter
from core.orca_ade.models import OrcaAdeMode, ProposalActionType
from lab.orca_ade.sandbox import OrcaWorktreeSandbox


class TestOrcaAdeConcurrency:
    """Verifica el comportamiento seguro bajo concurrencia de propuestas y worktrees."""

    def test_concurrent_proposals_thread_safety(self) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)

        def worker_task(worker_id: int) -> bool:
            prop = adapter.create_proposal(
                capability="worktree_isolation",
                action_type=ProposalActionType.CREATE_WORKTREE,
                title=f"Worker {worker_id} task",
                description=f"Concurrent proposal from thread {worker_id}",
            )
            res = adapter.evaluate_proposal(prop, jde_decision_override="ALLOW")
            return res.status == "ALLOWED" and res.side_effects_produced == 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_task, i) for i in range(20)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 20
        assert all(results)

    def test_concurrent_worktree_sandbox_operations(self) -> None:
        sandbox = OrcaWorktreeSandbox()
        try:
            def create_wt(index: int) -> bool:
                wt = sandbox.create_worktree(f"wt_worker_{index}", f"branch_{index}")
                return wt.is_active

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(create_wt, i) for i in range(10)]
                results = [f.result() for f in concurrent.futures.as_completed(futures)]

            assert len(results) == 10
            assert all(results)
            assert len(sandbox.list_worktrees()) == 10
        finally:
            sandbox.cleanup_all()
