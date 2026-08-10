"""Prueba del ciclo completo de auditoría para la operación ocr_screen (Subetapa 08.2)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.desktop_models import OCRRequest
from tools.desktop.ocr_backend import FakeOCRBackend
from tools.desktop.ocr_service import OCRService


def test_ocr_full_audit_sequence() -> None:
    sink = MemoryAuditSink()
    service = OCRService(backend=FakeOCRBackend())
    service.audit_logger.add_sink(sink)

    req = OCRRequest(width=640, height=480, language="eng")
    res = service.process_ocr(req, request_id="ocr-audit-seq-1")

    assert res.metadata.char_count > 0

    events = sink.get_events(tool_name="windows.desktop")
    event_types = [e.event_type for e in events]

    assert AuditEventType.OCR_SUCCEEDED in event_types
