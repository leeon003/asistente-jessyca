"""Ejecutor real seguro de herramientas de procesos (WindowsProcessToolExecutor - Subetapa 06.3).

Ejecuta operaciones reales sobre procesos Windows únicamente tras verificar AuthorizationEvidence
y enforzar la validación de Procesos Protegidos y Protección contra Reutilización de PID (PID Reuse Protection).
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
from tools.process.process_service import ProcessService

logger = get_logger("jessyca.tools.process.executor")


class WindowsProcessToolExecutor(IToolExecutor):
    """Ejecutor real seguro para herramientas del dominio `windows.process`."""

    def __init__(self, process_service: ProcessService | None = None) -> None:
        self.service = process_service or ProcessService()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def execute(
        self,
        request: ExecutionRequest,
        evidence: AuthorizationEvidence,
    ) -> ExecutionResult:
        """Ejecuta la operación de procesos autorizada."""
        start_time = datetime.now(UTC)
        op = request.operation.lower()
        params = request.parameters
        req_id = request.request_id

        logger.info(f"[PROCESS EXECUTOR] Ejecutando '{request.tool_name}.{op}' para request [{req_id[:8]}]")
        self.event_bus.publish("process:query_started" if "list" in op or "get" in op else "process:requested", {"request_id": req_id, "operation": op})

        try:
            output: object = None

            if op in ("list_processes", "list", "ps"):
                limit_val = params.get("limit")
                limit_int = int(limit_val) if limit_val else None
                output = self.service.list_processes(limit=limit_int).to_dict()

                self.audit_logger.log_audit_event(
                    AuditEvent(
                        event_type=AuditEventType.PROCESS_QUERY_SUCCEEDED,
                        request_id=req_id,
                        correlation_id=request.correlation_id,
                        session_id=request.session_id,
                        tool_name=request.tool_name,
                        operation=op,
                        success=True,
                    )
                )

            elif op in ("get_process", "get_process_by_pid", "get"):
                pid_param = params.get("pid")
                output = self.service.get_process(pid_param).to_dict()

                self.audit_logger.log_audit_event(
                    AuditEvent(
                        event_type=AuditEventType.PROCESS_QUERY_SUCCEEDED,
                        request_id=req_id,
                        correlation_id=request.correlation_id,
                        session_id=request.session_id,
                        tool_name=request.tool_name,
                        operation=op,
                        metadata={"pid": pid_param},
                        success=True,
                    )
                )

            elif op in ("terminate_process", "terminate", "kill"):
                pid_param = params.get("pid")
                expected_name = params.get("process_name")
                exp_time = params.get("creation_time")

                expected_creation_time = float(exp_time) if exp_time is not None else None
                expected_name_str = str(expected_name) if expected_name else None

                res_term = self.service.terminate_process(
                    pid=pid_param,
                    expected_name=expected_name_str,
                    expected_creation_time=expected_creation_time,
                )
                output = res_term.to_dict()

                self.audit_logger.log_audit_event(
                    AuditEvent(
                        event_type=AuditEventType.PROCESS_TERMINATION_SUCCEEDED,
                        request_id=req_id,
                        correlation_id=request.correlation_id,
                        session_id=request.session_id,
                        tool_name=request.tool_name,
                        operation=op,
                        metadata={"pid": pid_param, "process_name": res_term.process_name},
                        success=True,
                    )
                )
                self.event_bus.publish("process:termination_completed", {"request_id": req_id, "pid": pid_param})

            else:
                raise ValueError(f"Operación de procesos no soportada: '{op}'")

            duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                request_id=req_id,
                tool_name=request.tool_name,
                operation=op,
                output=output,
                message=f"Operación de procesos '{op}' ejecutada exitosamente.",
                duration_ms=duration,
                timestamp=datetime.now(UTC),
            )

        except Exception as e:
            duration = (datetime.now(UTC) - start_time).total_seconds() * 1000
            logger.error(f"Falla durante la ejecución de proceso para [{req_id}]: {e}")

            fail_event_type = (
                AuditEventType.PROCESS_TERMINATION_FAILED
                if op in ("terminate_process", "terminate", "kill")
                else AuditEventType.PROCESS_QUERY_FAILED
            )

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=fail_event_type,
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
            self.event_bus.publish("process:failed", {"request_id": req_id, "operation": op, "error": str(e)})

            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                request_id=req_id,
                tool_name=request.tool_name,
                operation=op,
                output=None,
                message=f"Error en operación de proceso '{op}': {e}",
                duration_ms=duration,
                timestamp=datetime.now(UTC),
            )
