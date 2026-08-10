"""Prueba del ciclo completo de auditoría para la operación inspect_ui_element (Subetapa 08.3)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.ui_inspection_models import UIElementRequest
from tools.desktop.ui_backend import FakeUIInspectionBackend
from tools.desktop.ui_inspection_service import UIInspectionService


def test_ui_inspection_full_audit_sequence() -> None:
    sink = MemoryAuditSink()
    service = UIInspectionService(backend=FakeUIInspectionBackend())
    service.audit_logger.add_sink(sink)

    req = UIElementRequest(window_title="Test Audit Window", max_depth=5)
    res = service.inspect_ui_elements(req, request_id="ui-audit-seq-1")

    assert res.metadata.element_count >= 1

    events = sink.get_events(tool_name="windows.desktop")
    event_types = [e.event_type for e in events]

    assert AuditEventType.UI_INSPECTION_SUCCEEDED in event_types
