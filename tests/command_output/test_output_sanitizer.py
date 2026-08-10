"""Pruebas del CommandOutputSanitizer (Subetapa 07.5)."""

from __future__ import annotations

from core.command_output import CommandOutputSanitizer


def test_command_output_sanitizer_full_pipeline() -> None:
    sanitizer = CommandOutputSanitizer()

    raw_stdout = "Execution completed. password=secretValue123"
    raw_stderr = "Warning: API token api_key=sk_live_999 exposed."

    output = sanitizer.sanitize(raw_stdout, raw_stderr, request_id="req-701")

    assert output.is_sanitized is True
    assert "secretValue123" not in output.stdout
    assert "sk_live_999" not in output.stderr
    assert output.redactions_count >= 2
    assert output.stdout_truncated is False
    assert output.stderr_truncated is False
