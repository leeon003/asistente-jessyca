"""Pruebas de límites de tamaño de salida y truncamiento (Subetapa 07.5)."""

from __future__ import annotations

from core.command_output import CommandOutputSanitizer


def test_output_sanitizer_truncation_limits() -> None:
    sanitizer = CommandOutputSanitizer()
    sanitizer.max_stdout_size = 50
    sanitizer.max_stderr_size = 50

    large_stdout = "a" * 100
    large_stderr = "b" * 100

    output = sanitizer.sanitize(large_stdout, large_stderr)

    assert output.stdout_truncated is True
    assert output.stderr_truncated is True
    assert "[STDOUT_TRUNCATED]" in output.stdout
    assert "[STDERR_TRUNCATED]" in output.stderr
    assert output.stdout_original_size == 100
    assert output.stderr_original_size == 100
