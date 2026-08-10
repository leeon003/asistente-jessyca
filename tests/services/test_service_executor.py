"""Pruebas del ejecutor real WindowsServicesToolExecutor (Subetapa 06.5)."""

from __future__ import annotations

from server.boundary import ExecutionStatus
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest
from tools.services.backend import FakeServicesBackend
from tools.services.executor import WindowsServicesToolExecutor
from tools.services.services_service import ServicesService


def test_executor_list_services() -> None:
    fake_service = ServicesService(backend=FakeServicesBackend())
    executor = WindowsServicesToolExecutor(services_service=fake_service)

    req = ExecutionRequest(
        tool_name="windows.services",
        operation="list_services",
        parameters={"limit": 5},
    )
    ev = AuthorizationEvidence.create_valid(
        tool_name="windows.services",
        operation="list_services",
        parameters={"limit": 5},
        request_id=req.request_id,
    )

    res = executor.execute(req, ev)
    assert res.status == ExecutionStatus.SUCCESS
    assert res.output["count"] >= 2


def test_executor_get_service() -> None:
    fake_service = ServicesService(backend=FakeServicesBackend())
    executor = WindowsServicesToolExecutor(services_service=fake_service)

    req = ExecutionRequest(
        tool_name="windows.services",
        operation="get_service",
        parameters={"service_name": "wuauserv"},
    )
    ev = AuthorizationEvidence.create_valid(
        tool_name="windows.services",
        operation="get_service",
        parameters={"service_name": "wuauserv"},
        request_id=req.request_id,
    )

    res = executor.execute(req, ev)
    assert res.status == ExecutionStatus.SUCCESS
    assert res.output["service_name"] == "wuauserv"
