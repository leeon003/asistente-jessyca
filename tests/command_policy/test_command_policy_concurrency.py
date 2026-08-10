"""Pruebas de concurrencia multi-hilo para CommandPolicyManager (Subetapa 07.1)."""

from __future__ import annotations

import concurrent.futures

from core.command_policy import CommandPolicyManager
from core.permission_manager import PermissionDecision


def test_concurrent_command_policy_evaluations() -> None:
    mgr = CommandPolicyManager()

    def worker(worker_id: int) -> bool:
        if worker_id % 2 == 0:
            res = mgr.evaluate_command("git", ["status"])
            return res.decision == PermissionDecision.ALLOW
        else:
            res = mgr.evaluate_command("echo", ["hello & calc"])
            return res.decision == PermissionDecision.DENY

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
