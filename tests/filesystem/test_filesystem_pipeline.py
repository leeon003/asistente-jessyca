"""Pruebas de integración end-to-end de herramientas de archivos con SecureExecutionPipeline (Subetapa 06.2)."""

from __future__ import annotations

from pathlib import Path

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.confirmation import ConfirmationStatus, MockConfirmationProvider
from server.app import JessycaMCPServer
from server.boundary import ExecutionStatus
from server.pipeline import SecureExecutionPipeline
from tools.filesystem.filesystem_service import FilesystemService
from tools.filesystem.path_security import PathSecurityManager


def test_end_to_end_filesystem_pipeline_execution(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    sec = PathSecurityManager(sandbox_root=sandbox)
    service = FilesystemService(path_security_manager=sec)

    mem_sink = MemoryAuditSink()
    pipeline = SecureExecutionPipeline()
    pipeline.audit_logger.add_sink(mem_sink)

    # Registrar servicio personalizado en el ejecutor del pipeline
    from tools.filesystem.executor import WindowsFilesystemToolExecutor

    exec_inst = WindowsFilesystemToolExecutor(filesystem_service=service)
    pipeline.boundary.register_executor("windows.files", exec_inst)

    server = JessycaMCPServer(pipeline=pipeline)
    server.start()

    # 1. Ejecutar write_file a través de handle_request con confirmación APPROVED
    provider = MockConfirmationProvider(ConfirmationStatus.APPROVED)
    res_write = server.handle_request(
        {
            "tool_name": "windows.files",
            "operation": "write_file",
            "parameters": {"path": "hello.txt", "content": "Hello World Jessyca"},
        },
        confirmation_provider=provider,
    )

    assert res_write.status == ExecutionStatus.SUCCESS
    assert (sandbox / "hello.txt").read_text(encoding="utf-8") == "Hello World Jessyca"

    # 2. Leer el archivo a través del servidor MCP
    res_read = server.handle_request(
        {
            "tool_name": "windows.files",
            "operation": "read_file",
            "parameters": {"path": "hello.txt"},
        }
    )

    assert res_read.status == ExecutionStatus.SUCCESS
    assert res_read.output["content"] == "Hello World Jessyca"

    # Verificar registro de eventos de auditoría del sistema de archivos
    events = mem_sink.get_events(tool_name="windows.files")
    event_types = [e.event_type for e in events]

    assert AuditEventType.FILESYSTEM_PATH_VALIDATED in event_types
    assert AuditEventType.FILESYSTEM_OPERATION_SUCCEEDED in event_types

    server.shutdown()
