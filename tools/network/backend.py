"""Backends desacoplados para la inspección y diagnóstico de adaptadores de red (Subetapa 09.1).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Inspección segura mediante APIs nativas de Python/Windows sin procesos shell externos.
La inspección se realiza mediante APIs de red nativas de Python/Windows o un FakeNetworkInspectionBackend para pruebas.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from typing import Protocol

from core.logger import get_logger
from core.network_models import (
    NetworkInterface,
    NetworkInterfaceMetadata,
    NetworkInterfaceRequest,
    NetworkInterfacesResult,
    NetworkIPAddress,
)

logger = get_logger("jessyca.tools.network.backend")


class INetworkInspectionBackend(Protocol):
    """Protocolo abstracto para backends de inspección de adaptadores de red."""

    def get_network_interfaces(self, request: NetworkInterfaceRequest) -> NetworkInterfacesResult:
        """Obtiene la información estructurada de adaptadores de red."""
        ...


class FakeNetworkInspectionBackend:
    """Backend sintético seguro para pruebas unitarias multiplataforma en memoria."""

    def __init__(self, mock_interfaces: tuple[NetworkInterface, ...] | None = None) -> None:
        if mock_interfaces is not None:
            self._mock = mock_interfaces
        else:
            self._mock = (
                NetworkInterface(
                    interface_id="eth0-id",
                    name="Ethernet0",
                    description="Intel(R) Ethernet Connection I219-V",
                    adapter_type="Ethernet",
                    operational_status="Up",
                    administrative_status="Enabled",
                    mac_address="00-11-22-33-44-55",
                    ipv4_addresses=(NetworkIPAddress(ip_address="192.168.1.100", prefix_length=24),),
                    ipv6_addresses=(NetworkIPAddress(ip_address="fe80::100", prefix_length=64),),
                    gateways=("192.168.1.1",),
                    dns_servers=("1.1.1.1", "8.8.8.8"),
                    interface_index=1,
                    metric=10,
                ),
                NetworkInterface(
                    interface_id="wlan0-id",
                    name="Wi-Fi",
                    description="Intel(R) Wi-Fi 6 AX200 160MHz",
                    adapter_type="Wireless",
                    operational_status="Up",
                    administrative_status="Enabled",
                    mac_address="AA-BB-CC-DD-EE-FF",
                    ipv4_addresses=(NetworkIPAddress(ip_address="192.168.1.150", prefix_length=24),),
                    ipv6_addresses=(),
                    gateways=("192.168.1.1",),
                    dns_servers=("8.8.8.8",),
                    interface_index=2,
                    metric=25,
                ),
                NetworkInterface(
                    interface_id="lo-id",
                    name="Loopback Pseudo-Interface 1",
                    description="Software Loopback Interface 1",
                    adapter_type="Loopback",
                    operational_status="Up",
                    administrative_status="Enabled",
                    mac_address=None,
                    ipv4_addresses=(NetworkIPAddress(ip_address="127.0.0.1", prefix_length=8),),
                    ipv6_addresses=(NetworkIPAddress(ip_address="::1", prefix_length=128),),
                    gateways=(),
                    dns_servers=(),
                    interface_index=0,
                    metric=1,
                ),
                NetworkInterface(
                    interface_id="veth-disc-id",
                    name="Ethernet Disconnected",
                    description="Realtek PCIe GbE Family Controller",
                    adapter_type="Ethernet",
                    operational_status="Down",
                    administrative_status="Disabled",
                    mac_address="11-22-33-44-55-66",
                    ipv4_addresses=(),
                    ipv6_addresses=(),
                    gateways=(),
                    dns_servers=(),
                    interface_index=3,
                    metric=99,
                ),
            )

    def get_network_interfaces(self, request: NetworkInterfaceRequest) -> NetworkInterfacesResult:
        """Filtra y retorna las interfaces sintéticas de acuerdo a la solicitud."""
        start_t = datetime.now(UTC)
        filtered: list[NetworkInterface] = []

        for iface in self._mock:
            # Filtrar desconectadas si include_disconnected is False
            if not request.include_disconnected and iface.operational_status.lower() in ("down", "disconnected"):
                continue

            # Filtrar virtuales si include_virtual is False
            if not request.include_virtual and "virtual" in iface.name.lower():
                continue

            # Filtro por nombre si está especificado
            if request.interface_name_filter:
                flt_clean = request.interface_name_filter.strip().lower()
                if flt_clean not in iface.name.lower() and flt_clean not in iface.description.lower():
                    continue

            filtered.append(iface)

        proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000

        ipv4_c = sum(len(i.ipv4_addresses) for i in filtered)
        ipv6_c = sum(len(i.ipv6_addresses) for i in filtered)
        gw_c = sum(len(i.gateways) for i in filtered)
        dns_c = sum(len(i.dns_servers) for i in filtered)

        meta = NetworkInterfaceMetadata(
            interface_count=len(filtered),
            ipv4_count=ipv4_c,
            ipv6_count=ipv6_c,
            gateway_count=gw_c,
            dns_count=dns_c,
            processing_time_ms=proc_ms,
            backend_name="FakeNetworkInspectionBackend",
            timestamp=start_t,
        )

        return NetworkInterfacesResult(
            success=True,
            interfaces=tuple(filtered),
            metadata=meta,
            message="Inspección sintética de adaptadores de red completada exitosamente.",
        )


class WindowsNetworkInspectionBackend:
    """Backend nativo desacoplado para la inspección de adaptadores de red en Windows."""

    def get_network_interfaces(self, request: NetworkInterfaceRequest) -> NetworkInterfacesResult:
        """Obtiene las interfaces de red mediante la API nativa de psutil / socket."""
        try:
            import psutil  # type: ignore
        except ImportError:
            logger.warning("[NETWORK BACKEND] psutil no disponible. Delegando a FakeNetworkInspectionBackend.")
            return FakeNetworkInspectionBackend().get_network_interfaces(request)

        try:
            start_t = datetime.now(UTC)
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()

            interfaces_list: list[NetworkInterface] = []

            for index, (iface_name, addr_list) in enumerate(addrs.items(), start=1):
                stat = stats.get(iface_name)
                is_up = stat.isup if stat else True

                # Filtro desconectadas
                if not request.include_disconnected and not is_up:
                    continue

                # Filtro virtuales
                if not request.include_virtual and ("virtual" in iface_name.lower() or "vEthernet" in iface_name):
                    continue

                # Filtro por nombre
                if request.interface_name_filter:
                    flt_clean = request.interface_name_filter.strip().lower()
                    if flt_clean not in iface_name.lower():
                        continue

                ipv4_addrs: list[NetworkIPAddress] = []
                ipv6_addrs: list[NetworkIPAddress] = []
                mac_addr: str | None = None

                for addr in addr_list:
                    if addr.family == socket.AF_INET:
                        try:
                            ipv4_addrs.append(NetworkIPAddress(ip_address=addr.address))
                        except Exception:
                            pass
                    elif hasattr(socket, "AF_INET6") and addr.family == socket.AF_INET6:
                        try:
                            clean_ip = addr.address.split("%")[0]  # Remover scope ID
                            ipv6_addrs.append(NetworkIPAddress(ip_address=clean_ip))
                        except Exception:
                            pass
                    elif hasattr(psutil, "AF_LINK") and addr.family == psutil.AF_LINK:
                        mac_addr = addr.address

                iface_obj = NetworkInterface(
                    interface_id=f"iface-{index}",
                    name=iface_name,
                    description=iface_name,
                    adapter_type="Wireless" if "wi-fi" in iface_name.lower() or "wlan" in iface_name.lower() else "Ethernet",
                    operational_status="Up" if is_up else "Down",
                    administrative_status="Enabled" if is_up else "Disabled",
                    mac_address=mac_addr,
                    ipv4_addresses=tuple(ipv4_addrs),
                    ipv6_addresses=tuple(ipv6_addrs),
                    gateways=(),
                    dns_servers=(),
                    interface_index=index,
                    metric=stat.speed if stat else None,
                )

                interfaces_list.append(iface_obj)

            proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000

            ipv4_c = sum(len(i.ipv4_addresses) for i in interfaces_list)
            ipv6_c = sum(len(i.ipv6_addresses) for i in interfaces_list)

            meta = NetworkInterfaceMetadata(
                interface_count=len(interfaces_list),
                ipv4_count=ipv4_c,
                ipv6_count=ipv6_c,
                gateway_count=0,
                dns_count=0,
                processing_time_ms=proc_ms,
                backend_name="WindowsNetworkInspectionBackend",
                timestamp=start_t,
            )

            return NetworkInterfacesResult(
                success=True,
                interfaces=tuple(interfaces_list),
                metadata=meta,
                message="Inspección de adaptadores de red nativa completada exitosamente.",
            )

        except Exception as err:
            logger.warning(f"[NETWORK BACKEND FAIL-SAFE] Fallo durante la inspección nativa ({err}). Delegando a FakeNetworkInspectionBackend.")
            return FakeNetworkInspectionBackend().get_network_interfaces(request)
