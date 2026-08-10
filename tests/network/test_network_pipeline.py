"""Pruebas de integración del SecureExecutionPipeline para la capability windows.network (Subetapa 09.1)."""

from __future__ import annotations

from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from server.pipeline import SecureExecutionPipeline
from tools.network.backend import FakeNetworkInspectionBackend
from tools.network.executor import WindowsNetworkToolExecutor
from tools.network.network_service import NetworkInspectionService


def test_secure_execution_pipeline_get_network_interfaces() -> None:
    pipeline = SecureExecutionPipeline()
    net_service = NetworkInspectionService(backend=FakeNetworkInspectionBackend())

    pipeline.boundary.register_executor("windows.network", WindowsNetworkToolExecutor(network_service=net_service))

    req = ExecutionRequest(
        request_id="pipeline-net-1",
        tool_name="windows.network",
        operation="get_network_interfaces",
        parameters={"include_disconnected": False},
        context=RequestContext(user="admin"),
    )

    result = pipeline.execute_request(req)

    assert result.status == ExecutionStatus.SUCCESS
    assert result.output["success"] is True
