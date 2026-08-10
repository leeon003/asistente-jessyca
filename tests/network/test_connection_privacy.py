"""Prueba de privacidad e integridad de auditoría sin filtración de conexiones crudas de red (Subetapa 09.2)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.network_connection_models import NetworkConnectionRequest
from tools.network.connection_backend import FakeNetworkConnectionInspectionBackend
from tools.network.connection_service import NetworkConnectionInspectionService


def test_network_connection_audit_metadata_only_no_raw_connection_leak() -> None:
    mem_sink = MemoryAuditSink()
    service = NetworkConnectionInspectionService(backend=FakeNetworkConnectionInspectionBackend())
    service.audit_logger.add_sink(mem_sink)

    req = NetworkConnectionRequest(protocol="TCP")
    result = service.get_active_connections(req, request_id="req-conn-priv-1")

    assert result.success is True

    events = mem_sink.get_events(tool_name="windows.desktop") + mem_sink.get_events(tool_name="windows.network")
    assert len(events) >= 1

    audit_event = events[0]
    assert audit_event.event_type == AuditEventType.NETWORK_CONNECTIONS_SUCCEEDED

    # INVARIANTE DE PRIVACIDAD: CERO DIRECCIONES IP, PUERTOS O CONEXIONES CRUDAS EN LA AUDITORÍA DE AUDITLOGGER
    metadata_str = str(audit_event.metadata)
    assert "192.168.1.100" not in metadata_str
    assert "54321" not in metadata_str
    assert "chrome.exe" not in metadata_str
    assert audit_event.metadata["total_found"] >= 1
    assert "returned_count" in audit_event.metadata
