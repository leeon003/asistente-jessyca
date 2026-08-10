"""Pruebas de integración del pipeline con CommandOutputSanitizer (Subetapa 07.5)."""

from __future__ import annotations

from core.command_output import CommandOutputSanitizer
from server.boundary import ExecutionResult, ExecutionStatus


def test_execution_result_sanitization_integration() -> None:
    sanitizer = CommandOutputSanitizer()

    raw_stdout = "status ok; api_key=sk_live_secretkey123;"
    sanitized = sanitizer.sanitize(raw_stdout, "")

    res = ExecutionResult(
        status=ExecutionStatus.SUCCESS,
        request_id="req-901",
        tool_name="windows.shell",
        operation="execute_command",
        output=sanitized.to_dict(),
        message="Command output processed safely.",
        duration_ms=10.0,
    )

    assert res.status == ExecutionStatus.SUCCESS
    assert "sk_live_secretkey123" not in str(res.output)
    assert res.output["is_sanitized"] is True
