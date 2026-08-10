"""Pruebas de fuzzing controlado para nombres de Servicios de Windows (Subetapa 06.5)."""

from __future__ import annotations

import pytest

from tools.services.errors import ServiceNameError, ServicesError
from tools.services.name_security import ServiceNameSecurityManager


def test_controlled_service_name_fuzzing() -> None:
    sec = ServiceNameSecurityManager()

    fuzz_payloads = [
        "",
        " ",
        "\t\n",
        "wuauserv\x00",
        "wuauserv & net stop wuauserv",
        "Spooler | dir",
        "service; rm -rf /",
        "$(whoami)",
        "`sc.exe stop wuauserv`",
        "powershell -command dir",
        "a" * 300,  # Length violation
        None,
    ]

    for payload in fuzz_payloads:
        with pytest.raises((ServiceNameError, ServicesError, ValueError)):
            sec.validate_and_sanitize_name(payload)
