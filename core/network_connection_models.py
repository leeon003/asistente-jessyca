"""Modelos inmutables para la inspección y diagnóstico de conexiones de red y puertos (Subetapa 09.2).

GARANTÍA ABSOLUTA DE SEGURIDAD Y PRIVACIDAD:
Modelos inmutables (`@dataclass(frozen=True)`). Representan únicamente conexiones activas y puertos
en escucha en modo solo lectura (READ-ONLY). CERO mutación de sockets o puertos.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class NetworkEndpoint:
    """Representación inmutable de un extremo de red (dirección IP y puerto)."""

    address: str
    port: int
    family: str = "IPv4"

    def __post_init__(self) -> None:
        # Validar dirección IP usando ipaddress de la librería estándar
        try:
            parsed = ipaddress.ip_address(self.address)
            object.__setattr__(self, "address", str(parsed))
            object.__setattr__(self, "family", "IPv6" if parsed.version == 6 else "IPv4")
        except ValueError as err:
            raise ValueError(f"Dirección IP del endpoint inválida: '{self.address}' ({err})") from err

        # Validar rango de puerto
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not (0 <= self.port <= 65535):
            raise ValueError(f"Puerto fuera de rango válido [0-65535]: {self.port}")

    def to_dict(self) -> dict[str, Any]:
        """Convierte el endpoint a diccionario estructurado."""
        return {
            "address": self.address,
            "port": self.port,
            "family": self.family,
        }


@dataclass(frozen=True)
class ActiveNetworkConnection:
    """Representación inmutable de una conexión de red activa (TCP o UDP)."""

    protocol: str
    local_endpoint: NetworkEndpoint
    remote_endpoint: NetworkEndpoint | None
    status: str
    process_id: int | None
    process_name: str | None
    family: str

    def to_dict(self) -> dict[str, Any]:
        """Convierte la conexión activa a diccionario estructurado."""
        return {
            "protocol": self.protocol,
            "local_endpoint": self.local_endpoint.to_dict(),
            "remote_endpoint": self.remote_endpoint.to_dict() if self.remote_endpoint else None,
            "status": self.status,
            "process_id": self.process_id,
            "process_name": self.process_name,
            "family": self.family,
        }


@dataclass(frozen=True)
class ListeningPort:
    """Representación inmutable de un puerto en escucha o socket bindado."""

    protocol: str
    local_endpoint: NetworkEndpoint
    state: str
    process_id: int | None
    process_name: str | None
    family: str

    def to_dict(self) -> dict[str, Any]:
        """Convierte el puerto en escucha a diccionario estructurado."""
        return {
            "protocol": self.protocol,
            "local_endpoint": self.local_endpoint.to_dict(),
            "state": self.state,
            "process_id": self.process_id,
            "process_name": self.process_name,
            "family": self.family,
        }


@dataclass(frozen=True)
class NetworkConnectionRequest:
    """Solicitud inmutable para la inspección de conexiones activas o puertos en escucha."""

    protocol: str | None = None
    state: str | None = None
    local_address: str | None = None
    local_port: int | None = None
    remote_address: str | None = None
    remote_port: int | None = None
    process_id: int | None = None
    include_process_info: bool = True
    max_results: int = 1000

    def to_dict(self) -> dict[str, Any]:
        """Convierte la solicitud a diccionario estructurado."""
        return {
            "protocol": self.protocol,
            "state": self.state,
            "local_address": self.local_address,
            "local_port": self.local_port,
            "remote_address": self.remote_address,
            "remote_port": self.remote_port,
            "process_id": self.process_id,
            "include_process_info": self.include_process_info,
            "max_results": self.max_results,
        }


@dataclass(frozen=True)
class NetworkConnectionMetadata:
    """Metadatos inmutables de la inspección de conexiones de red."""

    total_found: int
    returned_count: int
    truncated: bool
    processing_time_ms: float
    backend_name: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convierte los metadatos a diccionario seguro para auditoría."""
        return {
            "total_found": self.total_found,
            "returned_count": self.returned_count,
            "truncated": self.truncated,
            "processing_time_ms": round(self.processing_time_ms, 2),
            "backend_name": self.backend_name,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class NetworkConnectionsResult:
    """Resultado inmutable de la inspección de diagnóstico de conexiones de red."""

    success: bool
    connections: tuple[ActiveNetworkConnection, ...]
    listening_ports: tuple[ListeningPort, ...]
    metadata: NetworkConnectionMetadata
    message: str

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado a diccionario estructurado."""
        return {
            "success": self.success,
            "connections": [c.to_dict() for c in self.connections],
            "listening_ports": [p.to_dict() for p in self.listening_ports],
            "metadata": self.metadata.to_dict(),
            "message": self.message,
        }
