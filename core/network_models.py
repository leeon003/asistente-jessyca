"""Modelos inmutables para la inspección y diagnóstico de interfaces de red (`windows.network` - Subetapa 09.1).

GARANTÍA ABSOLUTA DE SEGURIDAD Y PRIVACIDAD:
Modelos inmutables (`@dataclass(frozen=True)`). Únicamente representan datos estructurados
de diagnóstico en modo solo lectura (READ-ONLY). CERO mutación de red.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class NetworkIPAddress:
    """Representación inmutable de una dirección IP (IPv4 o IPv6) con máscara/prefijo opcional."""

    ip_address: str
    prefix_length: int | None = None
    family: str = "IPv4"

    def __post_init__(self) -> None:
        # Validar dirección IP usando la librería estándar ipaddress
        try:
            parsed = ipaddress.ip_address(self.ip_address)
            object.__setattr__(self, "ip_address", str(parsed))
            object.__setattr__(self, "family", "IPv6" if parsed.version == 6 else "IPv4")
        except ValueError as err:
            raise ValueError(f"Dirección IP inválida: '{self.ip_address}' ({err})") from err

    def to_dict(self) -> dict[str, Any]:
        """Convierte la dirección IP a diccionario estructurado."""
        return {
            "ip_address": self.ip_address,
            "prefix_length": self.prefix_length,
            "family": self.family,
        }


@dataclass(frozen=True)
class NetworkRouteInfo:
    """Información inmutable de una ruta de red de diagnóstico."""

    destination: str
    gateway: str | None = None
    metric: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convierte la información de ruta a diccionario estructurado."""
        return {
            "destination": self.destination,
            "gateway": self.gateway,
            "metric": self.metric,
        }


@dataclass(frozen=True)
class NetworkDNSInfo:
    """Información inmutable de servidores DNS configurados."""

    dns_servers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Convierte los servidores DNS a diccionario estructurado."""
        return {
            "dns_servers": list(self.dns_servers),
        }


@dataclass(frozen=True)
class NetworkInterface:
    """Representación estructurada inmutable de un adaptador o interfaz de red de Windows."""

    interface_id: str
    name: str
    description: str
    adapter_type: str
    operational_status: str
    administrative_status: str
    mac_address: str | None
    ipv4_addresses: tuple[NetworkIPAddress, ...]
    ipv6_addresses: tuple[NetworkIPAddress, ...]
    gateways: tuple[str, ...]
    dns_servers: tuple[str, ...]
    interface_index: int | None = None
    metric: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convierte la interfaz a diccionario estructurado."""
        return {
            "interface_id": self.interface_id,
            "name": self.name,
            "description": self.description,
            "adapter_type": self.adapter_type,
            "operational_status": self.operational_status,
            "administrative_status": self.administrative_status,
            "mac_address": self.mac_address,
            "ipv4_addresses": [ip.to_dict() for ip in self.ipv4_addresses],
            "ipv6_addresses": [ip.to_dict() for ip in self.ipv6_addresses],
            "gateways": list(self.gateways),
            "dns_servers": list(self.dns_servers),
            "interface_index": self.interface_index,
            "metric": self.metric,
        }


@dataclass(frozen=True)
class NetworkInterfaceRequest:
    """Solicitud inmutable para la inspección de adaptadores de red."""

    include_disconnected: bool = False
    include_virtual: bool = False
    interface_name_filter: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convierte la solicitud a diccionario estructurado."""
        return {
            "include_disconnected": self.include_disconnected,
            "include_virtual": self.include_virtual,
            "interface_name_filter": self.interface_name_filter,
        }


@dataclass(frozen=True)
class NetworkInterfaceMetadata:
    """Metadatos inmutables de la inspección de adaptadores de red."""

    interface_count: int
    ipv4_count: int
    ipv6_count: int
    gateway_count: int
    dns_count: int
    processing_time_ms: float
    backend_name: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convierte los metadatos a diccionario seguro para auditoría."""
        return {
            "interface_count": self.interface_count,
            "ipv4_count": self.ipv4_count,
            "ipv6_count": self.ipv6_count,
            "gateway_count": self.gateway_count,
            "dns_count": self.dns_count,
            "processing_time_ms": round(self.processing_time_ms, 2),
            "backend_name": self.backend_name,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class NetworkInterfacesResult:
    """Resultado inmutable de la inspección de diagnóstico de adaptadores de red."""

    success: bool
    interfaces: tuple[NetworkInterface, ...]
    metadata: NetworkInterfaceMetadata
    message: str

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado a diccionario estructurado."""
        return {
            "success": self.success,
            "interfaces": [iface.to_dict() for iface in self.interfaces],
            "metadata": self.metadata.to_dict(),
            "message": self.message,
        }
