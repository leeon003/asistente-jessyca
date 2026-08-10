"""Pruebas de fuzzing controlado para parámetros de procesos (Subetapa 06.3)."""

from __future__ import annotations

import pytest

from tools.process.errors import InvalidPIDError, ProcessError
from tools.process.process_service import ProcessService


def test_controlled_pid_fuzzing() -> None:
    service = ProcessService()

    invalid_pids = [
        None,
        "",
        " ",
        "abc",
        -1,
        -999,
        999999999999999999999999999999,
        [],
        {},
        "\x00",
        "file_\U0001f600.txt",
    ]

    for bad_pid in invalid_pids:
        with pytest.raises((InvalidPIDError, ProcessError, ValueError)):
            service.get_process(bad_pid)
