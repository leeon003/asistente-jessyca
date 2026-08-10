"""Pruebas de integración de auditoría y EventBus sin filtración de datos crudos (Subetapa 07.5)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.command_output import CommandOutputSanitizer


def test_command_output_audit_and_eventbus_metadata_only() -> None:
    mem_sink = MemoryAuditSink()
    sanitizer = CommandOutputSanitizer()
    sanitizer.audit_logger.add_sink(mem_sink)

    secret_raw = "password=SuperSecretPassword999"
    sanitizer.sanitize(secret_raw, "", request_id="req-801")

    events = mem_sink.get_events(tool_name="windows.shell")
    event_types = [e.event_type for e in events]

    assert AuditEventType.COMMAND_OUTPUT_SANITIZED in event_types

    # Verificar que el evento de auditoría NUNCA almacena la contraseña cruda en metadatos
    audit_event = events[0]
    assert "SuperSecretPassword999" not in str(audit_event.metadata)
    assert audit_event.metadata["redactions_count"] >= 1
