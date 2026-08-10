"""Pruebas del ejecutor real WindowsProcessToolExecutor (Subetapa 06.3)."""

from __future__ import annotations

import os

from server.boundary import ExecutionStatus
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest
from tools.process.executor import WindowsProcessToolExecutor


def test_executor_list_processes() -> None:
    executor = WindowsProcessToolExecutor()
    req = ExecutionRequest(
        tool_name="windows.process",
        operation="list_processes",
        parameters={"limit": 10},
    )
    ev = AuthorizationEvidence.create_valid(
        tool_name="windows.process",
        operation="list_processes",
        parameters={"limit": 10},
        request_id=req.request_id,
    )

    res = executor.execute(req, ev)
    assert res.status == ExecutionStatus.SUCCESS
    assert res.output["count"] > 0


def test_executor_get_process() -> None:
    executor = WindowsProcessToolExecutor()
    current_pid = os.getpid()

    req = ExecutionRequest(
        tool_name="windows.process",
        operation="get_process",
        parameters={"pid": current_pid},
    )
    ev = AuthorizationEvidence.create_valid(
        tool_name="windows.process",
        operation="get_process",
        parameters={"pid": current_pid},
        request_id=req.request_id,
    )

    res = executor.execute(req, ev)
    assert res.status == ExecutionStatus.SUCCESS
    assert res.output["pid"] == current_pid
