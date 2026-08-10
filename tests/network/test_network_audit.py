"""Prueba del ciclo completo de auditoría para get_network_interfaces (Subetapa 09.1)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.network_models import NetworkInterfaceRequest
from tools.network.backend import FakeNetworkInspectionBackend
from tools.network.network_service import NetworkInspectionService


def test_network_inspection_full_audit_sequence() -> None:
    sink = MemoryAuditSink()
    service = NetworkInspectionService(backend=FakeNetworkInspectionBackend())
    service.audit_logger.add_sink(sink)

    req = NetworkInterfaceRequest(include_disconnected=True)
    res = service.get_network_interfaces(req, request_id="net-audit-seq-1")

    assert res.success is True

    events = sink.get_events(tool_name="windows.network")
    event_types = [e.event_type for e in events]

    assert AuditEventType.NETWORK_INSPECTION_SUCCEEDED in event_types
