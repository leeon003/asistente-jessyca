"""Pruebas de integración end-to-end de herramientas de procesos con SecureExecutionPipeline (Subetapa 06.3)."""

from __future__ import annotations

import os

from core.audit_logger import AuditEventType, MemoryAuditSink
from server.app import JessycaMCPServer
from server.boundary import ExecutionStatus
from server.pipeline import SecureExecutionPipeline


def test_end_to_end_process_pipeline_execution() -> None:
    mem_sink = MemoryAuditSink()
    pipeline = SecureExecutionPipeline()
    pipeline.audit_logger.add_sink(mem_sink)

    server = JessycaMCPServer(pipeline=pipeline)
    server.start()

    current_pid = os.getpid()

    # 1. Consultar proceso actual a través de la API del servidor MCP
    res_get = server.handle_request(
        {
            "tool_name": "windows.process",
            "operation": "get_process",
            "parameters": {"pid": current_pid},
        }
    )

    assert res_get.status == ExecutionStatus.SUCCESS
    assert res_get.output["pid"] == current_pid

    # 2. Listar procesos a través de la API del servidor MCP
    res_list = server.handle_request(
        {
            "tool_name": "windows.process",
            "operation": "list_processes",
            "parameters": {"limit": 5},
        }
    )

    assert res_list.status == ExecutionStatus.SUCCESS
    assert res_list.output["count"] > 0

    # Verificar registro de eventos de auditoría de procesos
    events = mem_sink.get_events(tool_name="windows.process")
    event_types = [e.event_type for e in events]

    assert AuditEventType.PROCESS_QUERY_SUCCEEDED in event_types

    server.shutdown()
