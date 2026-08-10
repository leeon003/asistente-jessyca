"""Pruebas de concurrencia multi-hilo para SecureCommandParser (Subetapa 07.2)."""

from __future__ import annotations

import concurrent.futures

from core.command_parser import SecureCommandParser


def test_concurrent_command_parsing() -> None:
    parser = SecureCommandParser()

    def worker(worker_id: int) -> bool:
        if worker_id % 2 == 0:
            res = parser.parse("git status")
            return res.is_valid is True
        else:
            res = parser.parse("echo hello && calc.exe")
            return res.is_valid is False

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
