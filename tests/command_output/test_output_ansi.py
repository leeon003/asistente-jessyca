"""Pruebas de eliminación de secuencias de escape ANSI (Subetapa 07.5)."""

from __future__ import annotations

from core.command_output import CommandOutputSanitizer


def test_command_output_sanitizer_strip_ansi() -> None:
    sanitizer = CommandOutputSanitizer()

    ansi_text = "\x1b[31mERROR:\x1b[0m Failed to execute \x1b[1mcommand\x1b[0m"
    clean_text = sanitizer.strip_ansi(ansi_text)

    assert "\x1b[" not in clean_text
    assert clean_text == "ERROR: Failed to execute command"
