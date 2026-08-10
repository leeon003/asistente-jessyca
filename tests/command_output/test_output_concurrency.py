"""Pruebas de concurrencia multi-hilo para CommandOutputSanitizer (Subetapa 07.5)."""

from __future__ import annotations

import concurrent.futures

from core.command_output import CommandOutputSanitizer


def test_concurrent_command_output_sanitization() -> None:
    sanitizer = CommandOutputSanitizer()

    def worker(worker_id: int) -> bool:
        raw_stdout = f"Worker {worker_id} password=secret_{worker_id}"
        out = sanitizer.sanitize(raw_stdout, None, request_id=f"req-{worker_id}")
        return f"secret_{worker_id}" not in out.stdout and out.redactions_count >= 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
