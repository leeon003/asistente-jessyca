"""Pruebas de normalización de codificación UTF-8 y caracteres de control (Subetapa 07.5)."""

from __future__ import annotations

from core.command_output import CommandOutputSanitizer


def test_output_sanitizer_utf8_bytes_and_invalid_encoding() -> None:
    sanitizer = CommandOutputSanitizer()

    # Stream de bytes con caracteres UTF-8 válidos y bytes corruptos (0xff)
    raw_bytes = b"Hello \xf0\x9f\x9a\x80 \xff world"

    normalized = sanitizer.normalize_utf8(raw_bytes)
    assert "Hello" in normalized
    assert "world" in normalized
    assert isinstance(normalized, str)
