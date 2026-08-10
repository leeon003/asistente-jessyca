"""Prueba del ciclo completo de auditoría para operaciones de caché DNS (Subetapa 09.3)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.network_routing_models import DNSCacheRequest
from tools.network.dns_cache_backend import FakeDNSCacheInspectionBackend
from tools.network.dns_cache_service import DNSCacheInspectionService


def test_dns_cache_full_audit_sequence() -> None:
    sink = MemoryAuditSink()
    service = DNSCacheInspectionService(backend=FakeDNSCacheInspectionBackend())
    service.audit_logger.add_sink(sink)

    req = DNSCacheRequest(record_type="A")
    res = service.get_dns_cache(req, request_id="net-dns-audit-seq-1")

    assert res.success is True

    events = sink.get_events(tool_name="windows.network")
    event_types = [e.event_type for e in events]

    assert AuditEventType.NETWORK_DNS_CACHE_SUCCEEDED in event_types
