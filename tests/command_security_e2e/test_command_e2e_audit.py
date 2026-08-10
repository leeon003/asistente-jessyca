"""Prueba del ciclo completo de auditoría y captura de eventos (Subetapa 07.6)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.command_audit import CommandAuditManager
from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel


def test_e2e_command_audit_sequence() -> None:
    sink = MemoryAuditSink()
    audit_mgr = CommandAuditManager()
    audit_mgr.audit_logger.add_sink(sink)

    req_id = "req-audit-seq-1"

    audit_mgr.log_command_start(req_id, "windows.shell", "execute_command", "powershell", "git.exe")
    audit_mgr.log_command_completion(
        request_id=req_id,
        tool_name="windows.shell",
        operation="execute_command",
        shell_type="powershell",
        executable="git.exe",
        fingerprint="abc123fp",
        risk_level=SecurityLevel.LOW,
        decision=PermissionDecision.ALLOW,
        duration_ms=10.0,
    )

    events = sink.get_events(tool_name="windows.shell")
    event_types = [e.event_type for e in events]

    assert AuditEventType.COMMAND_AUDIT_STARTED in event_types
    assert AuditEventType.COMMAND_AUDIT_COMPLETED in event_types
