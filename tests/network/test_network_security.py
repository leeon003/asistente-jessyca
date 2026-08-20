"""Pruebas de la frontera de seguridad NetworkSecurityManager (Subetapa 09.1)."""

from __future__ import annotations

import pytest

from core.network_models import (
    NetworkInterface,
    NetworkInterfaceRequest,
    NetworkIPAddress,
)
from core.network_security import (
    NetworkLimitExceededError,
    NetworkSecurityError,
    NetworkSecurityManager,
)


def test_network_security_mac_normalization() -> None:
    sec = NetworkSecurityManager()

    assert sec.normalize_mac_address("001122334455") == "00-11-22-33-44-55"
    assert sec.normalize_mac_address("aa:bb:cc:dd:ee:ff") == "AA-BB-CC-DD-EE-FF"
    assert sec.normalize_mac_address(None) is None


def test_network_security_validates_request_filter_length() -> None:
    sec = NetworkSecurityManager()
    sec.max_name_len = 20

    # Válido
    sec.validate_request(NetworkInterfaceRequest(interface_name_filter="Wi-Fi"))

    # Excesivo
    with pytest.raises(NetworkLimitExceededError):
        sec.validate_request(NetworkInterfaceRequest(interface_name_filter="A" * 50))

    # Caracteres no permitidos
    with pytest.raises(NetworkSecurityError):
        sec.validate_request(NetworkInterfaceRequest(interface_name_filter="Wi-Fi; rm -rf /"))


def test_network_security_sanitizes_interface_lists() -> None:
    sec = NetworkSecurityManager()
    sec.max_ips = 2

    ips = tuple(NetworkIPAddress(ip_address=f"10.0.0.{i}") for i in range(10))
    iface = NetworkInterface(
        interface_id="id-1",
        name="Eth0",
        description="Desc",
        adapter_type="Ethernet",
        operational_status="Up",
        administrative_status="Enabled",
        mac_address="001122334455",
        ipv4_addresses=ips,
        ipv6_addresses=(),
        gateways=(),
        dns_servers=(),
    )

    sanitized = sec.sanitize_and_validate_interface(iface)

    assert len(sanitized.ipv4_addresses) == 2
    assert sanitized.mac_address == "00-11-22-33-44-55"
