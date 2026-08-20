"""Servicio seguro de diagnóstico de adaptadores de red (NetworkInspectionService - Subetapa 09.1).

GARANTÍA ABSOLUTA DE PRIVACIDAD Y SEGURIDAD:
El AuditLogger y el EventBus reciben ÚNICAMENTE METADATOS de la inspección de red (conteo de interfaces,
conteo de IPs IPv4/IPv6, conteo de gateways/DNS, tiempo de procesamiento, backend).
INVARIANTE CRÍTICO: NUNCA registran la topología cruda de red ni las direcciones IP o MAC en auditoría.
"""

from __future__ import annotations

from datetime import UTC, datetime

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.network_models import (
    NetworkInterfaceRequest,
    NetworkInterfacesResult,
)
from core.network_security import NetworkSecurityManager
from tools.network.backend import (
    INetworkInspectionBackend,
    WindowsNetworkInspectionBackend,
)

logger = get_logger("jessyca.tools.network.network_service")


class NetworkInspectionService:
    """Servicio de orquestación y frontera de inspección de diagnóstico de adaptadores de red."""

    def __init__(
        self,
        backend: INetworkInspectionBackend | None = None,
        security_manager: NetworkSecurityManager | None = None,
    ) -> None:
        settings = AppSettings()
        self.backend = backend or WindowsNetworkInspectionBackend()
        self.security_manager = security_manager or NetworkSecurityManager()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def get_network_interfaces(
        self,
        request: NetworkInterfaceRequest,
        request_id: str | None = None,
    ) -> NetworkInterfacesResult:
        """Valida la solicitud, consulta el backend de red y formatea la respuesta de forma segura."""
        req_id = request_id or "net-req-unknown"
        start_time = datetime.now(UTC)

        self.event_bus.publish("network:inspection_requested", {"request_id": req_id})

        # 1. Validación de seguridad de la solicitud (FAIL-SAFE DENY)
        validated_req = self.security_manager.validate_request(request)
        self.event_bus.publish("network:inspection_validated", {"request_id": req_id, "validated": True})

        # 2. Invocación del backend desacoplado
        self.event_bus.publish("network:inspection_started", {"request_id": req_id})
        raw_result = self.backend.get_network_interfaces(validated_req)

        # 3. Validación, límites y sanitización del resultado
        sanitized_result = self.security_manager.validate_result(raw_result)

        duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

        # 4. Auditoría y EventBus (ÚNICAMENTE METADATOS, PRIVACIDAD DE DATOS DE RED)
        audit_meta = sanitized_result.metadata.to_dict()

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.NETWORK_INSPECTION_SUCCEEDED,
                request_id=req_id,
                tool_name="windows.network",
                operation="get_network_interfaces",
                duration_ms=duration,
                reason="Inspección de diagnóstico de adaptadores de red completada exitosamente.",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("network:inspection_completed", {"request_id": req_id, "metadata": audit_meta})
        return sanitized_result
