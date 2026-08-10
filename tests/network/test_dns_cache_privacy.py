"""Prueba de privacidad e integridad de auditoría sin filtración de registros DNS crudos (Subetapa 09.3)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.network_routing_models import DNSCacheRequest
from tools.network.dns_cache_backend import FakeDNSCacheInspectionBackend
from tools.network.dns_cache_service import DNSCacheInspectionService


def test_network_dns_cache_audit_metadata_only_no_raw_dns_leak() -> None:
    mem_sink = MemoryAuditSink()
    service = DNSCacheInspectionService(backend=FakeDNSCacheInspectionBackend())
    service.audit_logger.add_sink(mem_sink)

    req = DNSCacheRequest(record_type="A")
    result = service.get_dns_cache(req, request_id="req-dns-priv-1")

    assert result.success is True

    events = mem_sink.get_events(tool_name="windows.network")
    assert len(events) >= 1

    audit_event = events[0]
    assert audit_event.event_type == AuditEventType.NETWORK_DNS_CACHE_SUCCEEDED

    # INVARIANTE DE PRIVACIDAD: CERO HOSTNAMES O DIRECCIONES IP CRUDAS EN LA AUDITORÍA DE AUDITLOGGER
    metadata_str = str(audit_event.metadata)
    assert "google.com" not in metadata_str
    assert "142.250.190.46" not in metadata_str
    assert audit_event.metadata["total_found"] >= 1
    assert "returned_count" in audit_event.metadata
