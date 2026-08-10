"""Pruebas del comportamiento de timeout y terminación limpia (Subetapa 07.6)."""

from __future__ import annotations

from core.command_audit import CommandAuditManager
from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel


def test_e2e_command_timeout_audit_handling() -> None:
    audit_mgr = CommandAuditManager()
    req_id = "req-timeout-1"

    event = audit_mgr.log_command_completion(
        request_id=req_id,
        tool_name="windows.shell",
        operation="execute_command",
        shell_type="powershell",
        executable="powershell.exe",
        fingerprint="fp-timeout-123",
        risk_level=SecurityLevel.MEDIUM,
        decision=PermissionDecision.ALLOW,
        duration_ms=30000.0,
        exit_code=None,
        timeout=True,
        output_sizes={"stdout": 120, "stderr": 50},
    )

    assert event.timeout_occurred is True
    assert event.exit_code is None
    assert event.output_sizes["stdout"] == 120
