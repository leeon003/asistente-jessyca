"""Prueba de privacidad e integridad de auditoría sin filtración de datos binarios (Subetapa 08.1)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.desktop_models import ScreenshotRequest
from tools.desktop.backend import FakeDesktopCaptureBackend
from tools.desktop.desktop_service import DesktopService


def test_desktop_capture_audit_metadata_only_no_image_leak() -> None:
    mem_sink = MemoryAuditSink()
    service = DesktopService(backend=FakeDesktopCaptureBackend())
    service.audit_logger.add_sink(mem_sink)

    req = ScreenshotRequest(width=100, height=100, format="PNG")
    result = service.take_screenshot(req, request_id="req-audit-privacy-1")

    assert result.image_base64 is not None

    events = mem_sink.get_events(tool_name="windows.desktop")
    assert len(events) >= 1

    audit_event = events[0]
    assert audit_event.event_type == AuditEventType.DESKTOP_CAPTURE_SUCCEEDED

    # INVARIANTE DE PRIVACIDAD: CERO DATOS BINARIOS / CERO BASE64 EN AUDITORÍA
    metadata_str = str(audit_event.metadata)
    assert result.image_base64 not in metadata_str
    assert "fakeb64data" not in metadata_str
    assert audit_event.metadata["width"] == 100
    assert audit_event.metadata["height"] == 100
