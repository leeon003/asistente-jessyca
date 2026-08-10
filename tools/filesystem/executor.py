"""Ejecutor real seguro de herramientas de archivos (WindowsFilesystemToolExecutor - Subetapa 06.2).

Ejecuta operaciones reales del sistema de archivos dentro del sandbox únicamente tras recibir
una ExecutionRequest y AuthorizationEvidence válidas y verificadas por la frontera de seguridad.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.logger import get_logger
from server.boundary import ExecutionResult, ExecutionStatus
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest
from server.executor import IToolExecutor
from tools.filesystem.filesystem_service import FilesystemService

logger = get_logger("jessyca.tools.filesystem.executor")


class WindowsFilesystemToolExecutor(IToolExecutor):
    """Ejecutor real seguro para herramientas de sistema de archivos (`windows.files`)."""

    def __init__(self, filesystem_service: FilesystemService | None = None) -> None:
        self.service = filesystem_service or FilesystemService()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def execute(
        self,
        request: ExecutionRequest,
        evidence: AuthorizationEvidence,
    ) -> ExecutionResult:
        """Ejecuta la operación de archivo autorizada dentro del sandbox."""
        start_time = datetime.now(UTC)
        op = request.operation.lower()
        params = request.parameters
        req_id = request.request_id

        logger.info(f"[FILESYSTEM EXECUTOR] Ejecutando '{request.tool_name}.{op}' para request [{req_id[:8]}]")
        self.event_bus.publish("filesystem:started", {"request_id": req_id, "operation": op})

        try:
            output: object = None

            if op in ("list_directory", "list", "dir"):
                path_param = str(params.get("path") or ".").strip()
                output = self.service.list_directory(path_param).to_dict()

            elif op in ("read_file", "read"):
                path_param = str(params.get("path") or "").strip()
                enc = str(params.get("encoding") or "utf-8").strip()
                output = self.service.read_file(path_param, encoding=enc).to_dict()

            elif op in ("write_file", "write"):
                path_param = str(params.get("path") or "").strip()
                content = str(params.get("content") or "")
                enc = str(params.get("encoding") or "utf-8").strip()
                output = self.service.write_file(path_param, content, encoding=enc).to_dict()

            elif op in ("create_directory", "mkdir"):
                path_param = str(params.get("path") or "").strip()
                created = self.service.create_directory(path_param)
                output = {"created_directory": created}

            elif op in ("delete_file", "delete", "rm"):
                path_param = str(params.get("path") or "").strip()
                output = self.service.delete_file(path_param).to_dict()

            else:
                raise ValueError(f"Operación de archivo no soportada: '{op}'")

            duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.FILESYSTEM_OPERATION_SUCCEEDED,
                    request_id=req_id,
                    correlation_id=request.correlation_id,
                    session_id=request.session_id,
                    tool_name=request.tool_name,
                    operation=op,
                    duration_ms=duration,
                    success=True,
                )
            )

            self.event_bus.publish("filesystem:completed", {"request_id": req_id, "operation": op, "status": "SUCCESS"})

            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                request_id=req_id,
                tool_name=request.tool_name,
                operation=op,
                output=output,
                message=f"Operación de archivo '{op}' ejecutada exitosamente en el sandbox.",
                duration_ms=duration,
                timestamp=datetime.now(UTC),
            )

        except Exception as e:
            duration = (datetime.now(UTC) - start_time).total_seconds() * 1000
            logger.error(f"Falla durante la ejecución de archivo para [{req_id}]: {e}")

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.FILESYSTEM_OPERATION_FAILED,
                    request_id=req_id,
                    correlation_id=request.correlation_id,
                    session_id=request.session_id,
                    tool_name=request.tool_name,
                    operation=op,
                    error_message=str(e),
                    duration_ms=duration,
                    success=False,
                )
            )

            self.event_bus.publish("filesystem:failed", {"request_id": req_id, "operation": op, "error": str(e)})

            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                request_id=req_id,
                tool_name=request.tool_name,
                operation=op,
                output=None,
                message=f"Error en operación de archivo '{op}': {e}",
                duration_ms=duration,
                timestamp=datetime.now(UTC),
            )
