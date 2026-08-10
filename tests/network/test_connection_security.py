"""Pruebas de la frontera de seguridad NetworkConnectionSecurityManager (Subetapa 09.2)."""

from __future__ import annotations

import pytest

from core.network_connection_models import NetworkConnectionRequest
from core.network_connection_security import (
    NetworkConnectionLimitExceededError,
    NetworkConnectionSecurityError,
    NetworkConnectionSecurityManager,
)


def test_connection_security_manager_validates_correct_request() -> None:
    sec = NetworkConnectionSecurityManager()
    req = NetworkConnectionRequest(protocol="TCP", local_port=80, max_results=100)

    validated = sec.validate_request(req)
    assert validated.protocol == "TCP"
    assert validated.local_port == 80


def test_connection_security_manager_rejects_invalid_ports() -> None:
    sec = NetworkConnectionSecurityManager()

    # Puerto negativo
    with pytest.raises(NetworkConnectionSecurityError):
        sec.validate_request(NetworkConnectionRequest(local_port=-1))

    # Puerto > 65535
    with pytest.raises(NetworkConnectionSecurityError):
        sec.validate_request(NetworkConnectionRequest(local_port=70000))


def test_connection_security_manager_rejects_invalid_protocol() -> None:
    sec = NetworkConnectionSecurityManager()

    with pytest.raises(NetworkConnectionSecurityError):
        sec.validate_request(NetworkConnectionRequest(protocol="INVALID_PROT"))


def test_connection_security_manager_sanitizes_process_name() -> None:
    sec = NetworkConnectionSecurityManager()

    assert sec.sanitize_process_name("chrome.exe --type=renderer") == "chrome.exe"
    assert sec.sanitize_process_name("svchost.exe; rm -rf /") == "svchost.exe"
    assert sec.sanitize_process_name(None) is None
