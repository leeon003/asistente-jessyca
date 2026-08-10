"""Pruebas del CommandArgumentValidator (Subetapa 07.2)."""

from __future__ import annotations

import pytest

from core.command_parser import ArgumentValidationError, CommandArgumentValidator


def test_command_argument_validator_limits() -> None:
    val = CommandArgumentValidator()
    val.max_arguments = 3
    val.max_argument_length = 10
    val.max_total_length = 50

    # Válido
    val.validate("echo a b c", "echo", ("a", "b", "c"))

    # Excedido total de argumentos
    with pytest.raises(ArgumentValidationError):
        val.validate("echo a b c d", "echo", ("a", "b", "c", "d"))

    # Excedida longitud de argumento individual
    with pytest.raises(ArgumentValidationError):
        val.validate("echo toolongargumentname", "echo", ("toolongargumentname",))
