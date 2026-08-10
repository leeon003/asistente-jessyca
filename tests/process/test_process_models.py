"""Pruebas de los modelos inmutables de procesos (Subetapa 06.3)."""

from __future__ import annotations

import pytest

from tools.process.models import (
    ProcessInfo,
    ProcessListResult,
    ProcessTerminationResult,
)


def test_process_info_immutability_and_dict() -> None:
    info = ProcessInfo(
        pid=1234,
        parent_pid=100,
        name="test.exe",
        executable_path="C:\\test.exe",
        status="running",
        username="user",
        creation_time=1000.0,
        memory_usage=5000,
        cpu_percent=1.5,
    )

    assert info.pid == 1234
    assert info.name == "test.exe"

    with pytest.raises(AttributeError):
        info.pid = 9999  # type: ignore

    d = info.to_dict()
    assert d["pid"] == 1234
    assert d["name"] == "test.exe"


def test_process_list_result_and_termination_result() -> None:
    info = ProcessInfo(
        pid=100,
        parent_pid=None,
        name="app.exe",
        executable_path="",
        status="running",
        username="",
        creation_time=100.0,
        memory_usage=100,
        cpu_percent=0.0,
    )
    res_list = ProcessListResult(count=1, truncated=False, processes=(info,))
    assert res_list.count == 1
    assert res_list.to_dict()["count"] == 1

    res_term = ProcessTerminationResult(
        pid=100,
        process_name="app.exe",
        success=True,
        status="TERMINATED",
        reason="OK",
    )
    assert res_term.success is True
    assert res_term.to_dict()["pid"] == 100
