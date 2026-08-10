"""Servicio seguro de diagnóstico de la tabla de ruteo IP (RoutingTableInspectionService - Subetapa 09.3).

GARANTÍA ABSOLUTA DE PRIVACIDAD Y SEGURIDAD:
El AuditLogger y el EventBus reciben ÚNICAMENTE METADATOS de la inspección de ruteo (total_found,
returned_count, truncated, tiempo de procesamiento, backend_name).
INVARIANTE CRÍTICO: NUNCA registran las rutas individuales, destinos, pasarelas ni nombres de interfaz en auditoría.
"""

from __future__ import annotations

from datetime import UTC, datetime

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.network_routing_models import (
    RoutingTableRequest,
    RoutingTableResult,
)
from core.network_routing_security import NetworkRoutingSecurityManager
from tools.network.routing_backend import (
    FakeRoutingTableInspectionBackend,
    IRoutingTableInspectionBackend,
    WindowsRoutingTableInspectionBackend,
)

logger = get_logger("jessyca.tools.network.routing_service")


class RoutingTableInspectionService:
    """Servicio de orquestación y frontera de inspección de diagnóstico de la tabla de ruteo IP."""

    def __init__(
        self,
        backend: IRoutingTableInspectionBackend | None = None,
        security_manager: NetworkRoutingSecurityManager | None = None,
    ) -> None:
        settings = AppSettings()
        self.backend = backend or WindowsRoutingTableInspectionBackend()
        self.security_manager = security_manager or NetworkRoutingSecurityManager()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def get_routing_table(
        self,
        request: RoutingTableRequest,
        request_id: str | None = None,
    ) -> RoutingTableResult:
        """Valida la solicitud y obtiene la tabla de ruteo IP del sistema."""
        req_id = request_id or "net-route-req-unknown"
        start_time = datetime.now(UTC)

        self.event_bus.publish("network:routing_requested", {"request_id": req_id, "operation": "get_routing_table"})

        # 1. Validación de seguridad de la solicitud (FAIL-SAFE DENY)
        validated_req = self.security_manager.validate_routing_request(request)
        self.event_bus.publish("network:routing_validated", {"request_id": req_id, "validated": True})

        # 2. Invocación del backend desacoplado
        self.event_bus.publish("network:routing_started", {"request_id": req_id})
        raw_result = self.backend.get_routing_table(validated_req)

        # 3. Validación, sanitización y truncamiento del resultado
        sanitized_result = self.security_manager.validate_routing_result(raw_result)

        duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

        # 4. Auditoría y EventBus (ÚNICAMENTE METADATOS, PRIVACIDAD DE ROUTING)
        audit_meta = sanitized_result.metadata.to_dict()
        if request.address_family:
            audit_meta["address_family"] = request.address_family

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.NETWORK_ROUTING_SUCCEEDED,
                request_id=req_id,
                tool_name="windows.network",
                operation="get_routing_table",
                duration_ms=duration,
                reason="Inspección de diagnóstico de la tabla de ruteo IP completada exitosamente.",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("network:routing_completed", {"request_id": req_id, "metadata": audit_meta})
        return sanitized_result
