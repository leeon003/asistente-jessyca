"""Pruebas de integración de auditoría y EventBus para fronteras de shell (Subetapa 07.3)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.cmd_boundary import CMDExecutionBoundary
from core.powershell_boundary import PowerShellExecutionBoundary


def test_powershell_and_cmd_audit_and_eventbus_integration() -> None:
    mem_sink = MemoryAuditSink()

    ps_boundary = PowerShellExecutionBoundary()
    ps_boundary.audit_logger.add_sink(mem_sink)

    cmd_boundary = CMDExecutionBoundary()
    cmd_boundary.audit_logger.add_sink(mem_sink)

    # Invocación válida de PowerShell
    inv_ps = ps_boundary.validate_and_build("powershell.exe", ["Get-Process"], "req-501")
    assert inv_ps.is_valid is True

    # Invocación rechazada de CMD
    inv_cmd = cmd_boundary.validate_and_build("cmd.exe", ["/c", "whoami"], "req-502")
    assert inv_cmd.is_valid is False

    events = mem_sink.get_events(tool_name="windows.shell")
    event_types = [e.event_type for e in events]

    assert AuditEventType.POWERSHELL_BOUNDARY_ALLOWED in event_types
    assert AuditEventType.CMD_BOUNDARY_REJECTED in event_types
