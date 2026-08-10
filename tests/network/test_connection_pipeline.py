"""Pruebas de integración del SecureExecutionPipeline para operaciones de conexiones de red (Subetapa 09.2)."""

from __future__ import annotations

from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from server.pipeline import SecureExecutionPipeline
from tools.network.connection_backend import FakeNetworkConnectionInspectionBackend
from tools.network.connection_service import NetworkConnectionInspectionService
from tools.network.executor import WindowsNetworkToolExecutor


def test_secure_execution_pipeline_active_connections_and_listening_ports() -> None:
    pipeline = SecureExecutionPipeline()
    conn_service = NetworkConnectionInspectionService(backend=FakeNetworkConnectionInspectionBackend())

    pipeline.boundary.register_executor("windows.network", WindowsNetworkToolExecutor(connection_service=conn_service))

    # 1. get_active_connections
    req1 = ExecutionRequest(
        request_id="pipeline-conn-1",
        tool_name="windows.network",
        operation="get_active_connections",
        parameters={"protocol": "TCP"},
        context=RequestContext(user="admin"),
    )
    result1 = pipeline.execute_request(req1)
    assert result1.status == ExecutionStatus.SUCCESS

    # 2. get_listening_ports
    req2 = ExecutionRequest(
        request_id="pipeline-port-1",
        tool_name="windows.network",
        operation="get_listening_ports",
        parameters={},
        context=RequestContext(user="admin"),
    )
    result2 = pipeline.execute_request(req2)
    assert result2.status == ExecutionStatus.SUCCESS
