"""Pruebas adversariales de inyección de comandos en el parser (Subetapa 07.6)."""

from __future__ import annotations

from core.command_parser import SecureCommandParser


def test_e2e_parser_rejects_shell_injections() -> None:
    parser = SecureCommandParser()

    malicious_inputs = [
        "git status & calc.exe",
        "git status && whoami",
        "git status | grep test",
        "git status ; rm -rf /",
        "git status $(whoami)",
        "git status `whoami`",
        "git status > out.txt",
        "git status\r\nwhoami",
        "git status\x00whoami",
    ]

    for raw in malicious_inputs:
        parsed = parser.parse(raw, "e2e-bypass-req")
        assert parsed.is_valid is False
        assert parsed.rejection_reason is not None
