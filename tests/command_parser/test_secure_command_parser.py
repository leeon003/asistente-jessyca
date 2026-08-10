"""Pruebas del SecureCommandParser y StructuredCommand (Subetapa 07.2)."""

from __future__ import annotations

import hashlib

import pytest

from core.command_parser import SecureCommandParser


def test_secure_command_parser_structured_output() -> None:
    parser = SecureCommandParser()
    cmd = parser.parse("git status")

    assert cmd.is_valid is True
    assert cmd.executable == "git"
    assert cmd.arguments == ("status",)
    assert cmd.normalized_executable == "git"
    assert cmd.raw_input_hash == hashlib.sha256(b"git status").hexdigest()

    with pytest.raises(AttributeError):
        cmd.is_valid = False  # type: ignore

    d = cmd.to_dict()
    assert d["executable"] == "git"
    assert d["arguments"] == ["status"]


def test_secure_command_parser_invalid_input() -> None:
    parser = SecureCommandParser()
    cmd = parser.parse("echo hello && calc.exe")

    assert cmd.is_valid is False
    assert cmd.rejection_reason is not None
    assert "operadores" in cmd.rejection_reason
