"""Ejecutor real seguro de herramientas de archivos (WindowsFilesystemToolExecutor - Subetapa 06.2).

Ejecuta operaciones reales del sistema de archivos dentro del sandbox únicamente tras recibir
una ExecutionRequest y AuthorizationEvidence válidas y verificadas por la frontera de seguridad.
"""

from __future__ import annotations

import os
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
            is_verif = False

            if op in ("list_directory", "list", "dir"):
                path_param = str(params.get("path") or ".").strip()
                output = self.service.list_directory(path_param).to_dict()
                is_verif = True

            elif op in ("read_file", "read"):
                path_param = str(params.get("path") or "").strip()
                enc = str(params.get("encoding") or "utf-8").strip()
                output = self.service.read_file(path_param, encoding=enc).to_dict()
                is_verif = True

            elif op in ("write_file", "write"):
                path_param = str(params.get("path") or "").strip()
                content = str(params.get("content") or "")
                enc = str(params.get("encoding") or "utf-8").strip()
                write_res = self.service.write_file(path_param, content, encoding=enc)
                output = write_res.to_dict()
                target_path = write_res.path or path_param
                is_verif = os.path.exists(target_path) and os.path.isfile(target_path)

            elif op in ("create_directory", "mkdir"):
                path_param = str(params.get("path") or "").strip()
                created = self.service.create_directory(path_param)
                output = {"created_directory": created}
                is_verif = os.path.exists(created) and os.path.isdir(created)

            elif op in ("delete_file", "delete", "rm"):
                path_param = str(params.get("path") or "").strip()
                del_res = self.service.delete_file(path_param)
                output = del_res.to_dict()
                del_path = del_res.path or path_param
                is_verif = not os.path.exists(del_path)

            else:
                raise ValueError(f"Operación de archivo no soportada: '{op}'")

            # Soporte determinista de prueba para simular falta de evidencia
            if params.get("mock_unverified"):
                is_verif = False

            duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

            status_final = ExecutionStatus.SUCCESS if is_verif else ExecutionStatus.UNKNOWN
            msg_final = (
                f"Operación de archivo '{op}' ejecutada exitosamente en el sandbox."
                if is_verif
                else f"Operación de archivo '{op}' ejecutada pero no pudo verificarse evidencia observable."
            )

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.FILESYSTEM_OPERATION_SUCCEEDED if is_verif else AuditEventType.FILESYSTEM_OPERATION_FAILED,
                    request_id=req_id,
                    correlation_id=request.correlation_id,
                    session_id=request.session_id,
                    tool_name=request.tool_name,
                    operation=op,
                    duration_ms=duration,
                    success=is_verif,
                )
            )

            self.event_bus.publish("filesystem:completed", {"request_id": req_id, "operation": op, "status": status_final.value})

            return ExecutionResult(
                status=status_final,
                request_id=req_id,
                tool_name=request.tool_name,
                operation=op,
                output=output,
                message=msg_final,
                duration_ms=duration,
                is_verified=is_verif,
                evidence={"path": path_param if "path_param" in locals() else "", "verified": is_verif},
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
