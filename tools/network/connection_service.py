"""Servicio seguro de diagnóstico de conexiones de red y puertos (NetworkConnectionInspectionService - Subetapa 09.2).

GARANTÍA ABSOLUTA DE PRIVACIDAD Y SEGURIDAD:
El AuditLogger y el EventBus reciben ÚNICAMENTE METADATOS de la inspección de conexiones (total_found,
returned_count, truncated, tiempo de procesamiento, backend).
INVARIANTE CRÍTICO: NUNCA registran las conexiones individuales, IPs, puertos ni nombres de proceso en auditoría.
"""

from __future__ import annotations

from datetime import UTC, datetime

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.network_connection_models import (
    NetworkConnectionRequest,
    NetworkConnectionsResult,
)
from core.network_connection_security import NetworkConnectionSecurityManager
from tools.network.connection_backend import (
    FakeNetworkConnectionInspectionBackend,
    INetworkConnectionInspectionBackend,
    WindowsNetworkConnectionInspectionBackend,
)

logger = get_logger("jessyca.tools.network.connection_service")


class NetworkConnectionInspectionService:
    """Servicio de orquestación y frontera de inspección de diagnóstico de conexiones de red y puertos."""

    def __init__(
        self,
        backend: INetworkConnectionInspectionBackend | None = None,
        security_manager: NetworkConnectionSecurityManager | None = None,
    ) -> None:
        settings = AppSettings()
        self.backend = backend or WindowsNetworkConnectionInspectionBackend()
        self.security_manager = security_manager or NetworkConnectionSecurityManager()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def get_active_connections(
        self,
        request: NetworkConnectionRequest,
        request_id: str | None = None,
    ) -> NetworkConnectionsResult:
        """Valida la solicitud y obtiene la lista de conexiones de red activas."""
        req_id = request_id or "net-conn-req-unknown"
        start_time = datetime.now(UTC)

        self.event_bus.publish("network:connections_requested", {"request_id": req_id, "operation": "get_active_connections"})

        # 1. Validación de seguridad de la solicitud (FAIL-SAFE DENY)
        validated_req = self.security_manager.validate_request(request)
        self.event_bus.publish("network:connections_validated", {"request_id": req_id, "validated": True})

        # 2. Invocación del backend desacoplado
        self.event_bus.publish("network:connections_started", {"request_id": req_id})
        raw_result = self.backend.get_active_connections(validated_req)

        # 3. Validación, sanitización de proceso y truncamiento del resultado
        sanitized_result = self.security_manager.validate_result(raw_result)

        duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

        # 4. Auditoría y EventBus (ÚNICAMENTE METADATOS, PRIVACIDAD DE DATOS DE RED)
        audit_meta = sanitized_result.metadata.to_dict()
        if request.protocol:
            audit_meta["protocol_filter"] = request.protocol

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.NETWORK_CONNECTIONS_SUCCEEDED,
                request_id=req_id,
                tool_name="windows.network",
                operation="get_active_connections",
                duration_ms=duration,
                reason="Inspección de diagnóstico de conexiones de red activas completada exitosamente.",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("network:connections_completed", {"request_id": req_id, "metadata": audit_meta})
        return sanitized_result

    def get_listening_ports(
        self,
        request: NetworkConnectionRequest,
        request_id: str | None = None,
    ) -> NetworkConnectionsResult:
        """Valida la solicitud y obtiene la lista de puertos en escucha y sockets bindados."""
        req_id = request_id or "net-port-req-unknown"
        start_time = datetime.now(UTC)

        self.event_bus.publish("network:connections_requested", {"request_id": req_id, "operation": "get_listening_ports"})

        # 1. Validación de seguridad de la solicitud (FAIL-SAFE DENY)
        validated_req = self.security_manager.validate_request(request)
        self.event_bus.publish("network:connections_validated", {"request_id": req_id, "validated": True})

        # 2. Invocación del backend desacoplado
        self.event_bus.publish("network:connections_started", {"request_id": req_id})
        raw_result = self.backend.get_listening_ports(validated_req)

        # 3. Validación, sanitización de proceso y truncamiento del resultado
        sanitized_result = self.security_manager.validate_result(raw_result)

        duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

        # 4. Auditoría y EventBus (ÚNICAMENTE METADATOS, PRIVACIDAD DE DATOS DE RED)
        audit_meta = sanitized_result.metadata.to_dict()
        if request.protocol:
            audit_meta["protocol_filter"] = request.protocol

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.NETWORK_CONNECTIONS_SUCCEEDED,
                request_id=req_id,
                tool_name="windows.network",
                operation="get_listening_ports",
                duration_ms=duration,
                reason="Inspección de diagnóstico de puertos en escucha completada exitosamente.",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("network:connections_completed", {"request_id": req_id, "metadata": audit_meta})
        return sanitized_result
