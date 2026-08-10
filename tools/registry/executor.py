"""Ejecutor real seguro de herramientas del Registro (WindowsRegistryToolExecutor - Subetapa 06.4).

Ejecuta únicamente operaciones READ-ONLY de lectura e inspección del Registro de Windows tras validar
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
from tools.registry.registry_service import RegistryService

logger = get_logger("jessyca.tools.registry.executor")


class WindowsRegistryToolExecutor(IToolExecutor):
    """Ejecutor seguro de operaciones de lectura para el dominio `windows.registry`."""

    def __init__(self, registry_service: RegistryService | None = None) -> None:
        self.service = registry_service or RegistryService()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def execute(
        self,
        request: ExecutionRequest,
        evidence: AuthorizationEvidence,
    ) -> ExecutionResult:
        """Ejecuta la operación de inspección del Registro autorizada."""
        start_time = datetime.now(UTC)
        op = request.operation.lower()
        params = request.parameters
        req_id = request.request_id

        logger.info(f"[REGISTRY EXECUTOR] Ejecutando '{request.tool_name}.{op}' para request [{req_id[:8]}]")
        self.event_bus.publish("registry:query_started", {"request_id": req_id, "operation": op})

        try:
            output: object = None

            hive_param = str(params.get("hive") or "HKEY_CURRENT_USER")
            key_path_param = str(params.get("key_path") or params.get("path") or "")

            if op in ("list_registry_subkeys", "list_subkeys", "list_keys"):
                limit_val = params.get("limit")
                limit_int = int(limit_val) if limit_val else None
                subkeys = self.service.list_subkeys(hive_param, key_path_param, limit=limit_int)
                output = {"subkeys": [s.to_dict() for s in subkeys]}

            elif op in ("get_registry_key", "get_key", "key_info"):
                output = self.service.get_key_info(hive_param, key_path_param).to_dict()

            elif op in ("list_registry_values", "list_values"):
                limit_val = params.get("limit")
                limit_int = int(limit_val) if limit_val else None
                values = self.service.list_values(hive_param, key_path_param, limit=limit_int)
                output = {"values": [v.to_dict() for v in values]}

            elif op in ("get_registry_value", "get_value"):
                value_name = str(params.get("value_name") or params.get("name") or "")
                output = self.service.get_value(hive_param, key_path_param, value_name).to_dict()

            else:
                raise ValueError(f"Operación del Registro no soportada o prohibida en Subetapa 06.4: '{op}'")

            duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.REGISTRY_QUERY_SUCCEEDED,
                    request_id=req_id,
                    correlation_id=request.correlation_id,
                    session_id=request.session_id,
                    tool_name=request.tool_name,
                    operation=op,
                    metadata={"hive": hive_param, "key_path": key_path_param},
                    duration_ms=duration,
                    success=True,
                )
            )
            self.event_bus.publish("registry:query_completed", {"request_id": req_id, "operation": op})

            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                request_id=req_id,
                tool_name=request.tool_name,
                operation=op,
                output=output,
                message=f"Operación de lectura del Registro '{op}' ejecutada exitosamente.",
                duration_ms=duration,
                timestamp=datetime.now(UTC),
            )

        except Exception as e:
            duration = (datetime.now(UTC) - start_time).total_seconds() * 1000
            logger.error(f"Falla durante la consulta del Registro para [{req_id}]: {e}")

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.REGISTRY_QUERY_FAILED,
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
            self.event_bus.publish("registry:failed", {"request_id": req_id, "operation": op, "error": str(e)})

            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                request_id=req_id,
                tool_name=request.tool_name,
                operation=op,
                output=None,
                message=f"Error en consulta del Registro '{op}': {e}",
                duration_ms=duration,
                timestamp=datetime.now(UTC),
            )
