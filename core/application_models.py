"""Modelos e interfaces inmutables para el control de aplicaciones de escritorio (`windows.application` - Subetapa 11.1).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Modelos inmutables congelados (`@dataclass(frozen=True)`).
Estructura desacoplada de `windows.desktop` para control del ciclo de vida de aplicaciones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from core.exceptions import MCPError


class ApplicationState(StrEnum):
    """Estados explícitos del ciclo de vida de una aplicación de escritorio."""

    UNKNOWN = "UNKNOWN"
    NOT_RUNNING = "NOT_RUNNING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    FOCUSED = "FOCUSED"
    MINIMIZED = "MINIMIZED"
    TERMINATING = "TERMINATING"
    CLOSED = "CLOSED"
    FAULTED = "FAULTED"


class ApplicationControlError(MCPError):
    """Error base de la frontera de control de aplicaciones."""

    pass


class ApplicationNotFoundError(ApplicationControlError):
    """Error emitido cuando no se encuentra una aplicación o ejecutable registrado."""

    pass


class DuplicateApplicationInstanceError(ApplicationControlError):
    """Error emitido cuando se intenta abrir una instancia duplicada en modo estricto single-instance."""

    pass


class ApplicationLaunchError(ApplicationControlError):
    """Error emitido cuando falla el inicio o invocación de una aplicación de escritorio."""

    pass


class ApplicationCloseDeniedError(ApplicationControlError):
    """Error emitido cuando la terminación de una aplicación es denegada por seguridad o proceso protegido."""

    pass


@dataclass(frozen=True)
class ApplicationDescriptor:
    """Descriptor inmutable de una aplicación ejecutable registrada en el sistema."""

    app_id: str
    name: str
    executable: str
    aliases: tuple[str, ...] = ()
    supports_single_instance: bool = True
    default_args: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Convierte el descriptor a diccionario estructurado."""
        return {
            "app_id": self.app_id,
            "name": self.name,
            "executable": self.executable,
            "aliases": list(self.aliases),
            "supports_single_instance": self.supports_single_instance,
            "default_args": list(self.default_args),
        }


@dataclass(frozen=True)
class ApplicationSession:
    """Sesión inmutable activa o previa de una aplicación controlada."""

    session_id: str
    app_id: str
    pid: int | None
    hwnd: int | None
    state: ApplicationState
    is_single_instance: bool
    start_time: datetime
    last_active_time: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convierte la sesión de aplicación a diccionario seguro para auditoría."""
        return {
            "session_id": self.session_id,
            "app_id": self.app_id,
            "pid": self.pid,
            "hwnd": self.hwnd,
            "state": str(self.state),
            "is_single_instance": self.is_single_instance,
            "start_time": self.start_time.isoformat(),
            "last_active_time": self.last_active_time.isoformat(),
        }


class IApplicationAdapter(Protocol):
    """Protocolo abstracto para adaptadores del ciclo de vida de aplicaciones de escritorio."""

    def identify(self, app_alias: str) -> ApplicationDescriptor | None:
        """Identifica y resuelve el descriptor de una aplicación a partir de un nombre o alias."""
        ...

    def find_existing_session(self, app_id: str) -> ApplicationSession | None:
        """Busca una sesión o proceso activo existente para la aplicación indicada."""
        ...

    def launch(self, descriptor: ApplicationDescriptor, args: tuple[str, ...] = ()) -> ApplicationSession:
        """Inicia una nueva instancia de la aplicación o reanuda la existente."""
        ...

    def focus(self, session: ApplicationSession) -> bool:
        """Asigna el foco a la ventana principal de la sesión de aplicación."""
        ...

    def query_state(self, session: ApplicationSession) -> ApplicationState:
        """Consulta el estado actual de ejecución de la sesión de aplicación."""
        ...

    def close(self, session: ApplicationSession) -> bool:
        """Cierra la sesión de la aplicación de forma controlada."""
        ...
