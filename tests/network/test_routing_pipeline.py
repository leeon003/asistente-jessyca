"""Pruebas de integración del SecureExecutionPipeline para la tabla de ruteo IP (Subetapa 09.3)."""

from __future__ import annotations

from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from server.pipeline import SecureExecutionPipeline
from tools.network.executor import WindowsNetworkToolExecutor
from tools.network.routing_backend import FakeRoutingTableInspectionBackend
from tools.network.routing_service import RoutingTableInspectionService


def test_secure_execution_pipeline_get_routing_table() -> None:
    pipeline = SecureExecutionPipeline()
    r_service = RoutingTableInspectionService(backend=FakeRoutingTableInspectionBackend())

    pipeline.boundary.register_executor("windows.network", WindowsNetworkToolExecutor(routing_service=r_service))

    req = ExecutionRequest(
        request_id="pipeline-route-1",
        tool_name="windows.network",
        operation="get_routing_table",
        parameters={"address_family": "IPv4"},
        context=RequestContext(user="admin"),
    )
    result = pipeline.execute_request(req)
    assert result.status == ExecutionStatus.SUCCESS
