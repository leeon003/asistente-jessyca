"""Pruebas de integración end-to-end de herramientas del Registro con SecureExecutionPipeline (Subetapa 06.4)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from server.app import JessycaMCPServer
from server.boundary import ExecutionStatus
from server.pipeline import SecureExecutionPipeline
from tools.registry.backend import FakeRegistryBackend
from tools.registry.executor import WindowsRegistryToolExecutor
from tools.registry.registry_service import RegistryService


def test_end_to_end_registry_pipeline_execution() -> None:
    mem_sink = MemoryAuditSink()
    pipeline = SecureExecutionPipeline()
    pipeline.audit_logger.add_sink(mem_sink)

    fake_service = RegistryService(backend=FakeRegistryBackend())
    exec_inst = WindowsRegistryToolExecutor(registry_service=fake_service)
    pipeline.boundary.register_executor("windows.registry", exec_inst)

    server = JessycaMCPServer(pipeline=pipeline)
    server.start()

    # Consultar valor del Registro a través del servidor MCP
    res = server.handle_request(
        {
            "tool_name": "windows.registry",
            "operation": "get_registry_value",
            "parameters": {"hive": "HKCU", "key_path": "Software\\JessycaMCP", "value_name": "Version"},
        }
    )

    assert res.status == ExecutionStatus.SUCCESS
    assert res.output["value_data"] == "0.6.4"

    # Verificar registro de eventos de auditoría del Registro
    events = mem_sink.get_events(tool_name="windows.registry")
    event_types = [e.event_type for e in events]

    assert AuditEventType.REGISTRY_PATH_VALIDATED in event_types
    assert AuditEventType.REGISTRY_QUERY_SUCCEEDED in event_types

    server.shutdown()
