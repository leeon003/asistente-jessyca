"""Pruebas de integración end-to-end de herramientas de Servicios con SecureExecutionPipeline (Subetapa 06.5)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from server.app import JessycaMCPServer
from server.boundary import ExecutionStatus
from server.pipeline import SecureExecutionPipeline
from tools.services.backend import FakeServicesBackend
from tools.services.executor import WindowsServicesToolExecutor
from tools.services.services_service import ServicesService


def test_end_to_end_services_pipeline_execution() -> None:
    mem_sink = MemoryAuditSink()
    pipeline = SecureExecutionPipeline()
    pipeline.audit_logger.add_sink(mem_sink)

    fake_service = ServicesService(backend=FakeServicesBackend())
    exec_inst = WindowsServicesToolExecutor(services_service=fake_service)
    pipeline.boundary.register_executor("windows.services", exec_inst)

    server = JessycaMCPServer(pipeline=pipeline)
    server.start()

    # Consultar servicio a través del servidor MCP
    res = server.handle_request(
        {
            "tool_name": "windows.services",
            "operation": "get_service",
            "parameters": {"service_name": "wuauserv"},
        }
    )

    assert res.status == ExecutionStatus.SUCCESS
    assert res.output["service_name"] == "wuauserv"

    # Verificar registro de eventos de auditoría de servicios
    events = mem_sink.get_events(tool_name="windows.services")
    event_types = [e.event_type for e in events]

    assert AuditEventType.SERVICE_NAME_VALIDATED in event_types
    assert AuditEventType.SERVICE_QUERY_SUCCEEDED in event_types

    server.shutdown()
