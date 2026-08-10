"""Pruebas de fuzzing controlado para CommandOutputSanitizer (Subetapa 07.5)."""

from __future__ import annotations

from core.command_output import CommandOutputSanitizer


def test_controlled_command_output_fuzzing() -> None:
    sanitizer = CommandOutputSanitizer()

    fuzz_payloads = [
        (None, None),
        ("", ""),
        ("   ", "   "),
        ("password=123" * 500, "token=456" * 500),
        ('{"password": "secret", "nested": {"api_key": "sk_test_123"}}', ""),
        ("mongodb://admin:secretPass123@localhost:27017/db", ""),
        (b"invalid \xff bytes \x00\x01\x02", b"error \xfe"),
    ]

    for stdout, stderr in fuzz_payloads:
        output = sanitizer.sanitize(stdout, stderr)
        assert output.is_sanitized is True
        assert "secretPass123" not in output.stdout
        assert "sk_test_123" not in output.stdout
