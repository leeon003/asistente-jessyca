"""Pruebas de fuzzing controlado para SecureCommandParser (Subetapa 07.2)."""

from __future__ import annotations

from core.command_parser import SecureCommandParser


def test_controlled_command_parser_fuzzing() -> None:
    parser = SecureCommandParser()

    fuzz_payloads = [
        "",
        "   ",
        "\t\n",
        'git commit -m "unclosed quote',
        "git\x00status",
        "echo hello && calc.exe",
        "git status; whoami",
        "$(whoami)",
        "`whoami`",
        "a" * 5000,  # Total length violation
    ]

    for payload in fuzz_payloads:
        cmd = parser.parse(payload)
        assert cmd.is_valid is False
        assert cmd.rejection_reason is not None
