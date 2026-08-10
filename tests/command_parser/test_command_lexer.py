"""Pruebas unitarias del CommandLexer (Subetapa 07.2)."""

from __future__ import annotations

import pytest

from core.command_parser import CommandLexer, UnterminatedQuoteError


def test_command_lexer_basic_tokenization() -> None:
    exe, args = CommandLexer.tokenize("git status")
    assert exe == "git"
    assert args == ("status",)

    exe2, args2 = CommandLexer.tokenize("   ipconfig   /all   ")
    assert exe2 == "ipconfig"
    assert args2 == ("/all",)


def test_command_lexer_quoting_support() -> None:
    exe, args = CommandLexer.tokenize('echo "hello world"')
    assert exe == "echo"
    assert args == ("hello world",)

    exe2, args2 = CommandLexer.tokenize("git commit -m 'commit message'")
    assert exe2 == "git"
    assert args2 == ("commit", "-m", "commit message")


def test_command_lexer_unclosed_quote_raises_error() -> None:
    with pytest.raises(UnterminatedQuoteError):
        CommandLexer.tokenize('echo "unclosed string')

    with pytest.raises(UnterminatedQuoteError):
        CommandLexer.tokenize("git commit -m 'unclosed string")
