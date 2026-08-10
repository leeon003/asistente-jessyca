"""Servicio seguro de diagnóstico de la caché DNS local (DNSCacheInspectionService - Subetapa 09.3).

GARANTÍA ABSOLUTA DE PRIVACIDAD Y SEGURIDAD:
El AuditLogger y el EventBus reciben ÚNICAMENTE METADATOS de la inspección de la caché DNS (total_found,
returned_count, truncated, tiempo de procesamiento, backend_name).
INVARIANTE CRÍTICO: NUNCA registran las entradas DNS individuales, hostnames, IPs ni valores en auditoría.
"""

from __future__ import annotations

from datetime import UTC, datetime

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.network_routing_models import (
    DNSCacheRequest,
    DNSCacheResult,
)
from core.network_routing_security import NetworkRoutingSecurityManager
from tools.network.dns_cache_backend import (
    FakeDNSCacheInspectionBackend,
    IDNSCacheInspectionBackend,
    WindowsDNSCacheInspectionBackend,
)

logger = get_logger("jessyca.tools.network.dns_cache_service")


class DNSCacheInspectionService:
    """Servicio de orquestación y frontera de inspección de diagnóstico de la caché DNS local."""

    def __init__(
        self,
        backend: IDNSCacheInspectionBackend | None = None,
        security_manager: NetworkRoutingSecurityManager | None = None,
    ) -> None:
        settings = AppSettings()
        self.backend = backend or WindowsDNSCacheInspectionBackend()
        self.security_manager = security_manager or NetworkRoutingSecurityManager()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def get_dns_cache(
        self,
        request: DNSCacheRequest,
        request_id: str | None = None,
    ) -> DNSCacheResult:
        """Valida la solicitud y obtiene las entradas de la caché DNS local."""
        req_id = request_id or "net-dns-req-unknown"
        start_time = datetime.now(UTC)

        self.event_bus.publish("network:dns_cache_requested", {"request_id": req_id, "operation": "get_dns_cache"})

        # 1. Validación de seguridad de la solicitud (FAIL-SAFE DENY)
        validated_req = self.security_manager.validate_dns_cache_request(request)
        self.event_bus.publish("network:dns_cache_validated", {"request_id": req_id, "validated": True})

        # 2. Invocación del backend desacoplado
        self.event_bus.publish("network:dns_cache_started", {"request_id": req_id})
        raw_result = self.backend.get_dns_cache(validated_req)

        # 3. Validación, sanitización y truncamiento del resultado
        sanitized_result = self.security_manager.validate_dns_cache_result(raw_result)

        duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

        # 4. Auditoría y EventBus (ÚNICAMENTE METADATOS, PRIVACIDAD DE DNS)
        audit_meta = sanitized_result.metadata.to_dict()
        if request.record_type:
            audit_meta["record_type_filter"] = request.record_type

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.NETWORK_DNS_CACHE_SUCCEEDED,
                request_id=req_id,
                tool_name="windows.network",
                operation="get_dns_cache",
                duration_ms=duration,
                reason="Inspección de diagnóstico de la caché DNS local completada exitosamente.",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("network:dns_cache_completed", {"request_id": req_id, "metadata": audit_meta})
        return sanitized_result
