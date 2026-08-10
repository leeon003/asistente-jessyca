"""Pruebas de integración del SecureExecutionPipeline para la caché DNS (Subetapa 09.3)."""

from __future__ import annotations

from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from server.pipeline import SecureExecutionPipeline
from tools.network.dns_cache_backend import FakeDNSCacheInspectionBackend
from tools.network.dns_cache_service import DNSCacheInspectionService
from tools.network.executor import WindowsNetworkToolExecutor


def test_secure_execution_pipeline_get_dns_cache() -> None:
    pipeline = SecureExecutionPipeline()
    dns_service = DNSCacheInspectionService(backend=FakeDNSCacheInspectionBackend())

    pipeline.boundary.register_executor("windows.network", WindowsNetworkToolExecutor(dns_cache_service=dns_service))

    req = ExecutionRequest(
        request_id="pipeline-dns-1",
        tool_name="windows.network",
        operation="get_dns_cache",
        parameters={"record_type": "A"},
        context=RequestContext(user="admin"),
    )
    result = pipeline.execute_request(req)
    assert result.status == ExecutionStatus.SUCCESS
