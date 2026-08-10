"""Prueba del ciclo completo de auditoría para operaciones de conexiones de red (Subetapa 09.2)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.network_connection_models import NetworkConnectionRequest
from tools.network.connection_backend import FakeNetworkConnectionInspectionBackend
from tools.network.connection_service import NetworkConnectionInspectionService


def test_connection_full_audit_sequence() -> None:
    sink = MemoryAuditSink()
    service = NetworkConnectionInspectionService(backend=FakeNetworkConnectionInspectionBackend())
    service.audit_logger.add_sink(sink)

    req = NetworkConnectionRequest(protocol="TCP")
    res = service.get_active_connections(req, request_id="net-conn-audit-seq-1")

    assert res.success is True

    events = sink.get_events(tool_name="windows.network")
    event_types = [e.event_type for e in events]

    assert AuditEventType.NETWORK_CONNECTIONS_SUCCEEDED in event_types
