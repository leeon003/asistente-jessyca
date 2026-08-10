"""Prueba del ciclo completo de auditoría para operaciones de ruteo IP (Subetapa 09.3)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.network_routing_models import RoutingTableRequest
from tools.network.routing_backend import FakeRoutingTableInspectionBackend
from tools.network.routing_service import RoutingTableInspectionService


def test_routing_full_audit_sequence() -> None:
    sink = MemoryAuditSink()
    service = RoutingTableInspectionService(backend=FakeRoutingTableInspectionBackend())
    service.audit_logger.add_sink(sink)

    req = RoutingTableRequest(address_family="IPv4")
    res = service.get_routing_table(req, request_id="net-route-audit-seq-1")

    assert res.success is True

    events = sink.get_events(tool_name="windows.network")
    event_types = [e.event_type for e in events]

    assert AuditEventType.NETWORK_ROUTING_SUCCEEDED in event_types
