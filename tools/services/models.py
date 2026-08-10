"""Modelos de datos fuertemente tipados e inmutables para herramientas de Servicios de Windows (Subetapa 06.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WindowsServiceStatus:
    """Información inmutable del estado de ejecución de un Servicio de Windows."""

    status_str: str
    pid: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado del estado del servicio."""
        return {
            "status_str": self.status_str,
            "pid": self.pid,
        }


@dataclass(frozen=True)
class WindowsServiceInfo:
    """Información inmutable detallada de metadatos de un Servicio de Windows."""

    service_name: str
    display_name: str
    status: str
    start_type: str
    service_type: str
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    binpath: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado de los metadatos del servicio."""
        return {
            "service_name": self.service_name,
            "display_name": self.display_name,
            "status": self.status,
            "start_type": self.start_type,
            "service_type": self.service_type,
            "dependencies": list(self.dependencies),
            "description": self.description,
            "binpath": self.binpath,
        }


@dataclass(frozen=True)
class WindowsServiceQueryResult:
    """Resultado inmutable de la consulta estructurada del catálogo de Servicios."""

    count: int
    truncated: bool
    services: tuple[WindowsServiceInfo, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado del resultado de la consulta."""
        return {
            "count": self.count,
            "truncated": self.truncated,
            "services": [s.to_dict() for s in self.services],
        }
