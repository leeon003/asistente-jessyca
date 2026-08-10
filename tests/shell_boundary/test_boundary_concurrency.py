"""Pruebas de concurrencia multi-hilo para fronteras de shell (Subetapa 07.3)."""

from __future__ import annotations

import concurrent.futures

from core.cmd_boundary import CMDExecutionBoundary
from core.powershell_boundary import PowerShellExecutionBoundary


def test_concurrent_shell_boundary_evaluations() -> None:
    ps_b = PowerShellExecutionBoundary()
    cmd_b = CMDExecutionBoundary()

    def worker(worker_id: int) -> bool:
        if worker_id % 2 == 0:
            res = ps_b.validate_and_build("powershell.exe", ["Get-Process"], f"req-{worker_id}")
            return res.is_valid is True
        else:
            res = cmd_b.validate_and_build("cmd.exe", ["/c", "dir"], f"req-{worker_id}")
            return res.is_valid is False

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
