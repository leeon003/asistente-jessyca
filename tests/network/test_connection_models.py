"""Pruebas de los modelos inmutables de conexiones de red y puertos (Subetapa 09.2)."""

from __future__ import annotations

import pytest

from core.network_connection_models import (
    ActiveNetworkConnection,
    ListeningPort,
    NetworkConnectionRequest,
    NetworkEndpoint,
)


def test_network_endpoint_validation_and_immutability() -> None:
    ep = NetworkEndpoint(address="192.168.1.1", port=80)
    assert ep.address == "192.168.1.1"
    assert ep.port == 80
    assert ep.family == "IPv4"

    # Puerto fuera de rango
    with pytest.raises(ValueError):
        NetworkEndpoint(address="10.0.0.1", port=70000)

    # IP inválida
    with pytest.raises(ValueError):
        NetworkEndpoint(address="invalid_ip", port=80)

    # Inmutabilidad
    with pytest.raises(AttributeError):
        ep.port = 8080  # type: ignore


def test_active_connection_to_dict() -> None:
    conn = ActiveNetworkConnection(
        protocol="TCP",
        local_endpoint=NetworkEndpoint(address="10.0.0.1", port=5000),
        remote_endpoint=NetworkEndpoint(address="142.250.190.46", port=443),
        status="ESTABLISHED",
        process_id=1234,
        process_name="browser.exe",
        family="IPv4",
    )

    d = conn.to_dict()
    assert d["protocol"] == "TCP"
    assert d["local_endpoint"]["port"] == 5000
    assert d["remote_endpoint"]["address"] == "142.250.190.46"


def test_listening_port_to_dict() -> None:
    port = ListeningPort(
        protocol="TCP",
        local_endpoint=NetworkEndpoint(address="0.0.0.0", port=80),
        state="LISTEN",
        process_id=4,
        process_name="System",
        family="IPv4",
    )

    d = port.to_dict()
    assert d["protocol"] == "TCP"
    assert d["state"] == "LISTEN"
