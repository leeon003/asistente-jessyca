"""Prueba de prevención de filtración de secretos en salida (Subetapa 07.6)."""

from __future__ import annotations

from core.audit_logger import MemoryAuditSink
from core.command_output import CommandOutputSanitizer


def test_e2e_output_sanitizer_prevents_raw_secret_leak() -> None:
    mem_sink = MemoryAuditSink()
    sanitizer = CommandOutputSanitizer()
    sanitizer.audit_logger.add_sink(mem_sink)

    sensitive_stdout = "user_auth password=MyUltraSecretPass123! token=bearer_xyz_999"
    out = sanitizer.sanitize(sensitive_stdout, "", "req-leak-test")

    # Output sanitizado
    assert "MyUltraSecretPass123!" not in out.stdout
    assert "bearer_xyz_999" not in out.stdout

    # Verificación en sumidero de auditoría
    events = mem_sink.get_events(tool_name="windows.shell")
    assert len(events) >= 1
    assert "MyUltraSecretPass123!" not in str(events[0].metadata)
    assert "bearer_xyz_999" not in str(events[0].metadata)
