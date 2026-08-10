"""Ejecutor real seguro de herramientas de Servicios (WindowsServicesToolExecutor - Subetapa 06.5).

Ejecuta únicamente operaciones READ-ONLY de lectura e inspección de Servicios de Windows tras validar
la evidencia criptográfica AuthorizationEvidence y verificar la frontera de seguridad.
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
from tools.services.services_service import ServicesService

logger = get_logger("jessyca.tools.services.executor")


class WindowsServicesToolExecutor(IToolExecutor):
    """Ejecutor seguro de operaciones de lectura para el dominio `windows.services`."""

    def __init__(self, services_service: ServicesService | None = None) -> None:
        self.service = services_service or ServicesService()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def execute(
        self,
        request: ExecutionRequest,
        evidence: AuthorizationEvidence,
    ) -> ExecutionResult:
        """Ejecuta la operación de inspección de Servicios autorizada."""
        start_time = datetime.now(UTC)
        op = request.operation.lower()
        params = request.parameters
        req_id = request.request_id

        logger.info(f"[SERVICES EXECUTOR] Ejecutando '{request.tool_name}.{op}' para request [{req_id[:8]}]")
        self.event_bus.publish("services:query_started", {"request_id": req_id, "operation": op})

        try:
            output: object = None

            if op in ("list_services", "list", "enum"):
                limit_val = params.get("limit")
                limit_int = int(limit_val) if limit_val else None
                output = self.service.list_services(limit=limit_int).to_dict()

            elif op in ("get_service", "get", "info"):
                name_param = str(params.get("service_name") or params.get("name") or "")
                output = self.service.get_service(name_param).to_dict()

            elif op in ("get_service_status", "status"):
                name_param = str(params.get("service_name") or params.get("name") or "")
                output = self.service.get_service_status(name_param).to_dict()

            elif op in ("get_service_configuration", "config", "configuration"):
                name_param = str(params.get("service_name") or params.get("name") or "")
                output = self.service.get_service_configuration(name_param)

            else:
                raise ValueError(f"Operación de Servicios no soportada o prohibida en Subetapa 06.5: '{op}'")

            duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.SERVICE_QUERY_SUCCEEDED,
                    request_id=req_id,
                    correlation_id=request.correlation_id,
                    session_id=request.session_id,
                    tool_name=request.tool_name,
                    operation=op,
                    duration_ms=duration,
                    success=True,
                )
            )
            self.event_bus.publish("services:query_completed", {"request_id": req_id, "operation": op})

            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                request_id=req_id,
                tool_name=request.tool_name,
                operation=op,
                output=output,
                message=f"Operación de lectura de servicios '{op}' ejecutada exitosamente.",
                duration_ms=duration,
                timestamp=datetime.now(UTC),
            )

        except Exception as e:
            duration = (datetime.now(UTC) - start_time).total_seconds() * 1000
            logger.error(f"Falla durante la consulta de servicios para [{req_id}]: {e}")

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.SERVICE_QUERY_FAILED,
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
            self.event_bus.publish("services:failed", {"request_id": req_id, "operation": op, "error": str(e)})

            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                request_id=req_id,
                tool_name=request.tool_name,
                operation=op,
                output=None,
                message=f"Error en consulta de servicios '{op}': {e}",
                duration_ms=duration,
                timestamp=datetime.now(UTC),
            )
