"""Pruebas de concurrencia y seguridad en accesos multi-hilo (Subetapa 06.2)."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path

from tools.filesystem.filesystem_service import FilesystemService
from tools.filesystem.path_security import PathSecurityManager


def test_concurrent_write_and_read(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    sec = PathSecurityManager(sandbox_root=sandbox)
    service = FilesystemService(path_security_manager=sec)

    def worker(worker_id: int) -> bool:
        filename = f"worker_{worker_id}.txt"
        service.write_file(filename, f"Data from worker {worker_id}")
        res = service.read_file(filename)
        return res.content == f"Data from worker {worker_id}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
    assert len(list(sandbox.glob("worker_*.txt"))) == 20
