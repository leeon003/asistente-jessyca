"""Modelos inmutables para la inspección y diagnóstico de la tabla de ruteo y caché DNS (Subetapa 09.3).

GARANTÍA ABSOLUTA DE SEGURIDAD Y PRIVACIDAD:
Modelos inmutables (`@dataclass(frozen=True)`). Representan únicamente rutas IP y entradas de caché DNS
en modo solo lectura (READ-ONLY). CERO mutación de rutas o caché.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class NetworkRoute:
    """Representación inmutable de una ruta IP de red."""

    destination: str
    prefix_length: int
    gateway: str | None
    interface: str
    metric: int | None
    protocol: str | None
    address_family: str
    route_type: str | None

    def to_dict(self) -> dict[str, Any]:
        """Convierte la ruta IP a diccionario estructurado."""
        return {
            "destination": self.destination,
            "prefix_length": self.prefix_length,
            "gateway": self.gateway,
            "interface": self.interface,
            "metric": self.metric,
            "protocol": self.protocol,
            "address_family": self.address_family,
            "route_type": self.route_type,
        }


@dataclass(frozen=True)
class RoutingTableRequest:
    """Solicitud inmutable para la inspección de la tabla de ruteo IP."""

    address_family: str | None = None
    destination: str | None = None
    gateway: str | None = None
    interface: str | None = None
    metric: int | None = None
    protocol: str | None = None
    max_results: int = 2048

    def to_dict(self) -> dict[str, Any]:
        """Convierte la solicitud a diccionario estructurado."""
        return {
            "address_family": self.address_family,
            "destination": self.destination,
            "gateway": self.gateway,
            "interface": self.interface,
            "metric": self.metric,
            "protocol": self.protocol,
            "max_results": self.max_results,
        }


@dataclass(frozen=True)
class RoutingTableMetadata:
    """Metadatos inmutables de la inspección de la tabla de ruteo IP."""

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
class RoutingTableResult:
    """Resultado inmutable de la inspección de diagnóstico de la tabla de ruteo IP."""

    success: bool
    routes: tuple[NetworkRoute, ...]
    metadata: RoutingTableMetadata
    message: str

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado a diccionario estructurado."""
        return {
            "success": self.success,
            "routes": [r.to_dict() for r in self.routes],
            "metadata": self.metadata.to_dict(),
            "message": self.message,
        }


@dataclass(frozen=True)
class DNSCacheEntry:
    """Representación inmutable de una entrada en la caché DNS local del sistema."""

    hostname: str
    record_type: str
    value: str
    ttl: int | None
    address_family: str | None
    status: str | None

    def to_dict(self) -> dict[str, Any]:
        """Convierte la entrada de caché DNS a diccionario estructurado."""
        return {
            "hostname": self.hostname,
            "record_type": self.record_type,
            "value": self.value,
            "ttl": self.ttl,
            "address_family": self.address_family,
            "status": self.status,
        }


@dataclass(frozen=True)
class DNSCacheRequest:
    """Solicitud inmutable para la inspección de la caché DNS local."""

    hostname: str | None = None
    record_type: str | None = None
    address_family: str | None = None
    value: str | None = None
    max_results: int = 4096

    def to_dict(self) -> dict[str, Any]:
        """Convierte la solicitud a diccionario estructurado."""
        return {
            "hostname": self.hostname,
            "record_type": self.record_type,
            "address_family": self.address_family,
            "value": self.value,
            "max_results": self.max_results,
        }


@dataclass(frozen=True)
class DNSCacheMetadata:
    """Metadatos inmutables de la inspección de la caché DNS."""

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
class DNSCacheResult:
    """Resultado inmutable de la inspección de diagnóstico de la caché DNS."""

    success: bool
    entries: tuple[DNSCacheEntry, ...]
    metadata: DNSCacheMetadata
    message: str

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado a diccionario estructurado."""
        return {
            "success": self.success,
            "entries": [e.to_dict() for e in self.entries],
            "metadata": self.metadata.to_dict(),
            "message": self.message,
        }
