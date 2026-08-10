"""Pruebas de seguridad adversariales de parseo de comandos (Subetapa 07.2)."""

from __future__ import annotations

import pytest

from core.command_parser import (
    CommandLexer,
    NewlineInjectionError,
    NullByteRejectedError,
    SecureCommandParser,
    ShellOperatorRejectedError,
)


def test_parser_rejection_shell_operators() -> None:
    malicious_inputs = [
        "git status & whoami",
        "git status && whoami",
        "git status | whoami",
        "git status || whoami",
        "git status; whoami",
        "git status > output.txt",
        "git status < input.txt",
        "git status `whoami`",
        "git status $(whoami)",
    ]

    for raw in malicious_inputs:
        with pytest.raises(ShellOperatorRejectedError):
            CommandLexer.tokenize(raw)


def test_parser_rejection_null_bytes_and_newlines() -> None:
    with pytest.raises(NullByteRejectedError):
        CommandLexer.tokenize("git\x00status")

    with pytest.raises(NewlineInjectionError):
        CommandLexer.tokenize("git status\nwhoami")

    with pytest.raises(NewlineInjectionError):
        CommandLexer.tokenize("git status\r\nwhoami")


def test_parser_preserves_path_information() -> None:
    parser = SecureCommandParser()

    cmd_relative = parser.parse(".\\git.exe status")
    assert cmd_relative.executable == ".\\git.exe"
    assert cmd_relative.normalized_executable == "git.exe"

    cmd_absolute = parser.parse("C:\\Windows\\System32\\git.exe status")
    assert cmd_absolute.executable == "C:\\Windows\\System32\\git.exe"
    assert cmd_absolute.normalized_executable == "git.exe"
