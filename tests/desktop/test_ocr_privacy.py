"""Prueba de privacidad e integridad de auditoría sin filtración de texto OCR ni secretos (Subetapa 08.2)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.desktop_models import OCRRequest
from tools.desktop.ocr_backend import FakeOCRBackend
from tools.desktop.ocr_service import OCRService


def test_ocr_audit_metadata_only_no_secret_text_leak() -> None:
    mem_sink = MemoryAuditSink()
    mock_secret_text = "System Admin Panel\npassword=MySuperSecretPass999;"
    backend = FakeOCRBackend(mock_text=mock_secret_text)

    service = OCRService(backend=backend)
    service.audit_logger.add_sink(mem_sink)

    req = OCRRequest(width=400, height=300)
    result = service.process_ocr(req, request_id="req-ocr-privacy-1")

    assert "MySuperSecretPass999" not in result.recognized_text

    events = mem_sink.get_events(tool_name="windows.desktop")
    assert len(events) >= 1

    audit_event = events[0]
    assert audit_event.event_type == AuditEventType.OCR_SUCCEEDED

    # INVARIANTE DE PRIVACIDAD: CERO RAW TEXT / CERO SECRETOS EN AUDITORÍA
    metadata_str = str(audit_event.metadata)
    assert "MySuperSecretPass999" not in metadata_str
    assert "System Admin Panel" not in metadata_str  # Texto completo no debe registrarse en la auditoría
    assert audit_event.metadata["char_count"] > 0
    assert audit_event.metadata["region_count"] >= 1
