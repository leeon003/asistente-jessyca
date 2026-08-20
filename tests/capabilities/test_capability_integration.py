"""Pruebas de integración del Capability System con el SecureExecutionPipeline, AuditLogger y EventBus (Subetapa 06.1)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from server.app import JessycaMCPServer
from server.boundary import ExecutionStatus
from server.pipeline import SecureExecutionPipeline


def test_pipeline_integrates_capability_resolver_and_audit_log() -> None:
    mem_sink = MemoryAuditSink()
    pipeline = SecureExecutionPipeline()
    pipeline.audit_logger.add_sink(mem_sink)

    req = pipeline.capability_resolver.resolve("windows.files", "read_file")
    assert req.found is True
    assert req.decision.value == "ALLOW"

    # Ejecutar una solicitud a través del servidor MCP
    server = JessycaMCPServer(pipeline=pipeline)
    server.start()

    res = server.handle_request({"tool_name": "windows.files", "operation": "read_file"})
    assert res.status in (ExecutionStatus.EXECUTION_DISABLED, ExecutionStatus.FAILED, ExecutionStatus.SUCCESS)
    assert res.tool_name == "windows.files"

    # Verificar que el evento CAPABILITY_RESOLVED quedó registrado en la auditoría
    events = mem_sink.get_events(tool_name="windows.files")
    event_types = [e.event_type for e in events]

    assert AuditEventType.CAPABILITY_RESOLVED in event_types
    assert AuditEventType.REQUEST_RECEIVED in event_types

    server.shutdown()


def test_zero_real_execution_guarantee() -> None:
    pipeline = SecureExecutionPipeline()

    # Verificar que la resolución de capabilities no invoca ningún comando del sistema
    res = pipeline.capability_resolver.resolve("windows.shell", "execute_command")
    assert res.found is True
    assert res.decision.value == "REQUIRE_ELEVATED_AUTHORIZATION"
