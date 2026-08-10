"""Pruebas del ProcessService utilizando psutil en Windows (Subetapa 06.3)."""

from __future__ import annotations

import os

import pytest

from tools.process.errors import InvalidPIDError, ProcessNotFoundError
from tools.process.process_service import ProcessService


def test_list_processes_returns_active_processes() -> None:
    service = ProcessService()
    res = service.list_processes(limit=50)

    assert res.count > 0
    assert len(res.processes) <= 50

    pids = [p.pid for p in res.processes]
    # El PID del proceso actual de Python debe estar en la lista si cabe
    current_pid = os.getpid()
    assert current_pid in pids or res.truncated is True


def test_get_process_current_python_process() -> None:
    service = ProcessService()
    current_pid = os.getpid()

    info = service.get_process(current_pid)
    assert info.pid == current_pid
    assert info.name.lower().startswith("python") or info.name != ""


def test_get_process_invalid_or_non_existent_pid() -> None:
    service = ProcessService()

    with pytest.raises(InvalidPIDError):
        service.get_process(-100)

    with pytest.raises(InvalidPIDError):
        service.get_process("abc_invalid_pid")

    with pytest.raises(ProcessNotFoundError):
        # 999999 es un PID virtualmente inexistente
        service.get_process(999999)
