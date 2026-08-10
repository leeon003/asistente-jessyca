"""Pruebas de backends de inspección de adaptadores de red (Subetapa 09.1)."""

from __future__ import annotations

from core.network_models import NetworkInterfaceRequest
from tools.network.backend import (
    FakeNetworkInspectionBackend,
    WindowsNetworkInspectionBackend,
)


def test_fake_network_inspection_backend_filtering() -> None:
    backend = FakeNetworkInspectionBackend()

    # 1. Sin incluir desconectadas (por defecto returna conectadas: Ethernet0, Wi-Fi, Loopback)
    req1 = NetworkInterfaceRequest(include_disconnected=False)
    res1 = backend.get_network_interfaces(req1)
    assert res1.success is True
    assert len(res1.interfaces) == 3

    # 2. Incluir desconectadas (Ethernet Disconnected)
    req2 = NetworkInterfaceRequest(include_disconnected=True)
    res2 = backend.get_network_interfaces(req2)
    assert len(res2.interfaces) == 4

    # 3. Filtro por nombre "Wi-Fi"
    req3 = NetworkInterfaceRequest(interface_name_filter="Wi-Fi")
    res3 = backend.get_network_interfaces(req3)
    assert len(res3.interfaces) == 1
    assert res3.interfaces[0].name == "Wi-Fi"


def test_windows_network_inspection_backend_fallback() -> None:
    backend = WindowsNetworkInspectionBackend()
    req = NetworkInterfaceRequest()
    res = backend.get_network_interfaces(req)

    assert res.success is True
    assert res.metadata.interface_count >= 1
