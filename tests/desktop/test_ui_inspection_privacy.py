"""Prueba de privacidad e integridad de auditoría sin filtración de datos o secretos UI (Subetapa 08.3)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.ui_inspection_models import (
    UIControlType,
    UIElementBounds,
    UIElementInfo,
    UIElementRequest,
    UIElementTree,
)
from tools.desktop.ui_backend import FakeUIInspectionBackend
from tools.desktop.ui_inspection_service import UIInspectionService


def test_ui_inspection_audit_metadata_only_no_secret_leak() -> None:
    mem_sink = MemoryAuditSink()
    secret_elem = UIElementInfo(
        automation_id="SecretField",
        name="User Password (password=SuperSecretToken999;)",
        control_type=UIControlType.EDIT,
        class_name="Edit",
        bounds=UIElementBounds(x=10, y=10, width=100, height=30),
        is_enabled=True,
        is_offscreen=False,
        has_keyboard_focus=False,
        process_id=500,
        framework_id="Win32",
    )
    root = UIElementInfo(
        automation_id="WinRoot",
        name="Main Window",
        control_type=UIControlType.WINDOW,
        class_name="Window",
        bounds=UIElementBounds(x=0, y=0, width=500, height=400),
        is_enabled=True,
        is_offscreen=False,
        has_keyboard_focus=False,
        process_id=500,
        framework_id="Win32",
        children=(secret_elem,),
    )

    backend = FakeUIInspectionBackend(mock_tree=UIElementTree(root=root))
    service = UIInspectionService(backend=backend)
    service.audit_logger.add_sink(mem_sink)

    req = UIElementRequest()
    result = service.inspect_ui_elements(req, request_id="req-ui-privacy-1")

    # 1. Verificar que en el resultado de inspección el secreto esté redactado
    for elem in result.elements_flat:
        assert "SuperSecretToken999" not in elem.name

    events = mem_sink.get_events(tool_name="windows.desktop")
    assert len(events) >= 1

    audit_event = events[0]
    assert audit_event.event_type == AuditEventType.UI_INSPECTION_SUCCEEDED

    # INVARIANTE DE PRIVACIDAD: CERO ARBOL CRUDO / CERO SECRETOS EN AUDITORÍA
    metadata_str = str(audit_event.metadata)
    assert "SuperSecretToken999" not in metadata_str
    assert "SecretField" not in metadata_str  # Los IDs/nombres completos de nodos no deben incluirse en auditoría
    assert audit_event.metadata["element_count"] == 2
    assert audit_event.metadata["max_depth_reached"] >= 1
