"""Pruebas del ServiceNameSecurityManager (Subetapa 06.5)."""

from __future__ import annotations

import pytest

from tools.services.errors import ServiceNameError
from tools.services.name_security import ServiceNameSecurityManager


def test_valid_service_name_accepted() -> None:
    sec = ServiceNameSecurityManager()

    assert sec.validate_and_sanitize_name("wuauserv") == "wuauserv"
    assert sec.validate_and_sanitize_name("  Spooler  ") == "Spooler"
    assert sec.validate_and_sanitize_name("Jessyca_Service-01") == "Jessyca_Service-01"


def test_invalid_service_names_rejected() -> None:
    sec = ServiceNameSecurityManager()

    # Vacío o no string
    with pytest.raises(ServiceNameError):
        sec.validate_and_sanitize_name("")

    with pytest.raises(ServiceNameError):
        sec.validate_and_sanitize_name(None)

    # Caracteres nulos
    with pytest.raises(ServiceNameError):
        sec.validate_and_sanitize_name("service\x00_name")


def test_command_injection_patterns_rejected() -> None:
    sec = ServiceNameSecurityManager()

    malicious_payloads = [
        "wuauserv & calc.exe",
        "Spooler | dir",
        "service; rm -rf /",
        "service' OR 1=1",
        'service" && whoami',
        "$(whoami)",
        "`sc.exe stop wuauserv`",
        "sc.exe start malicious",
        "powershell -command dir",
    ]

    for payload in malicious_payloads:
        with pytest.raises(ServiceNameError):
            sec.validate_and_sanitize_name(payload)
