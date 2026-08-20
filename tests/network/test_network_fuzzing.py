"""Pruebas de fuzzing controlado para la frontera de seguridad de inspección de red (Subetapa 09.1)."""

from __future__ import annotations

import pytest

from core.network_models import NetworkInterfaceRequest, NetworkIPAddress
from core.network_security import (
    NetworkLimitExceededError,
    NetworkSecurityError,
    NetworkSecurityManager,
)


def test_controlled_network_fuzzing() -> None:
    sec = NetworkSecurityManager()

    invalid_filters = [
        "A" * 9999,
        "Wi-Fi; rm -rf /",
        "Ethernet && calc.exe",
        "| powershell.exe",
        "$(whoami)",
    ]

    for flt in invalid_filters:
        with pytest.raises((NetworkSecurityError, NetworkLimitExceededError)):
            sec.validate_request(NetworkInterfaceRequest(interface_name_filter=flt))

    invalid_ips = [
        "256.256.256.256",
        "192.168.1.999",
        "not_an_ip",
        "127.0.0.1; calc",
        "fe80:::1",
    ]

    for ip_str in invalid_ips:
        with pytest.raises(ValueError):
            NetworkIPAddress(ip_address=ip_str)
