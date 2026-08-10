"""Prueba de privacidad e integridad de auditoría sin filtración de topología cruda de red (Subetapa 09.1)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.network_models import NetworkInterfaceRequest
from tools.network.backend import FakeNetworkInspectionBackend
from tools.network.network_service import NetworkInspectionService


def test_network_inspection_audit_metadata_only_no_raw_network_leak() -> None:
    mem_sink = MemoryAuditSink()
    service = NetworkInspectionService(backend=FakeNetworkInspectionBackend())
    service.audit_logger.add_sink(mem_sink)

    req = NetworkInterfaceRequest(include_disconnected=True)
    result = service.get_network_interfaces(req, request_id="req-net-priv-1")

    assert result.success is True

    events = mem_sink.get_events(tool_name="windows.network")
    assert len(events) >= 1

    audit_event = events[0]
    assert audit_event.event_type == AuditEventType.NETWORK_INSPECTION_SUCCEEDED

    # INVARIANTE DE PRIVACIDAD: CERO DIRECCIONES IP O MAC EN LA AUDITORÍA DE AUDITLOGGER
    metadata_str = str(audit_event.metadata)
    assert "192.168.1.100" not in metadata_str
    assert "00-11-22-33-44-55" not in metadata_str
    assert audit_event.metadata["interface_count"] >= 1
    assert "ipv4_count" in audit_event.metadata
