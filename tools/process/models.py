"""Modelos de datos fuertemente tipados e inmutables para la gestión de procesos (Subetapa 06.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProcessInfo:
    """Información estructurada inmutable de un proceso de Windows."""

    pid: int
    parent_pid: int | None
    name: str
    executable_path: str
    status: str
    username: str
    creation_time: float
    memory_usage: int
    cpu_percent: float

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado de la información del proceso."""
        return {
            "pid": self.pid,
            "parent_pid": self.parent_pid,
            "name": self.name,
            "executable_path": self.executable_path,
            "status": self.status,
            "username": self.username,
            "creation_time": self.creation_time,
            "memory_usage": self.memory_usage,
            "cpu_percent": self.cpu_percent,
        }


@dataclass(frozen=True)
class ProcessListResult:
    """Resultado inmutable del listado de procesos del sistema."""

    count: int
    truncated: bool
    processes: tuple[ProcessInfo, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado del listado."""
        return {
            "count": self.count,
            "truncated": self.truncated,
            "processes": [p.to_dict() for p in self.processes],
        }


@dataclass(frozen=True)
class ProcessTerminationResult:
    """Resultado inmutable del intento de terminación de un proceso."""

    pid: int
    process_name: str
    success: bool
    status: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado del resultado."""
        return {
            "pid": self.pid,
            "process_name": self.process_name,
            "success": self.success,
            "status": self.status,
            "reason": self.reason,
        }
