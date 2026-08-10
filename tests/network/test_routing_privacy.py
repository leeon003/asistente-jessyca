"""Prueba de privacidad e integridad de auditoría sin filtración de rutas crudas (Subetapa 09.3)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.network_routing_models import RoutingTableRequest
from tools.network.routing_backend import FakeRoutingTableInspectionBackend
from tools.network.routing_service import RoutingTableInspectionService


def test_network_routing_audit_metadata_only_no_raw_route_leak() -> None:
    mem_sink = MemoryAuditSink()
    service = RoutingTableInspectionService(backend=FakeRoutingTableInspectionBackend())
    service.audit_logger.add_sink(mem_sink)

    req = RoutingTableRequest(address_family="IPv4")
    result = service.get_routing_table(req, request_id="req-route-priv-1")

    assert result.success is True

    events = mem_sink.get_events(tool_name="windows.network")
    assert len(events) >= 1

    audit_event = events[0]
    assert audit_event.event_type == AuditEventType.NETWORK_ROUTING_SUCCEEDED

    # INVARIANTE DE PRIVACIDAD: CERO DIRECCIONES IP O PASARELAS CRUDAS EN LA AUDITORÍA DE AUDITLOGGER
    metadata_str = str(audit_event.metadata)
    assert "192.168.1.1" not in metadata_str
    assert "0.0.0.0" not in metadata_str
    assert audit_event.metadata["total_found"] >= 1
    assert "returned_count" in audit_event.metadata
