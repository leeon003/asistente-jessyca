"""Pruebas de los modelos inmutables de inspección de red (Subetapa 09.1)."""

from __future__ import annotations

import pytest

from core.network_models import (
    NetworkIPAddress,
    NetworkInterface,
    NetworkInterfaceRequest,
)


def test_network_ip_address_validation_ipv4_and_ipv6() -> None:
    ip4 = NetworkIPAddress(ip_address="192.168.1.1", prefix_length=24)
    assert ip4.family == "IPv4"
    assert ip4.ip_address == "192.168.1.1"

    ip6 = NetworkIPAddress(ip_address="fe80::1", prefix_length=64)
    assert ip6.family == "IPv6"

    with pytest.raises(ValueError):
        NetworkIPAddress(ip_address="invalid.ip.address.999")


def test_network_interface_immutability() -> None:
    iface = NetworkInterface(
        interface_id="id1",
        name="Eth0",
        description="Intel Ethernet",
        adapter_type="Ethernet",
        operational_status="Up",
        administrative_status="Enabled",
        mac_address="00-11-22-33-44-55",
        ipv4_addresses=(NetworkIPAddress(ip_address="10.0.0.1"),),
        ipv6_addresses=(),
        gateways=("10.0.0.254",),
        dns_servers=("8.8.8.8",),
    )

    assert iface.name == "Eth0"

    with pytest.raises(AttributeError):
        iface.name = "Eth1"  # type: ignore


def test_network_interface_request_to_dict() -> None:
    req = NetworkInterfaceRequest(include_disconnected=True, interface_name_filter="Wi-Fi")
    d = req.to_dict()
    assert d["include_disconnected"] is True
    assert d["interface_name_filter"] == "Wi-Fi"
