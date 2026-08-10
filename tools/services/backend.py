"""Abstracción backend de interacción con Servicios de Windows (Subetapa 06.5 - READ ONLY).

GARANTÍA DE CERO SHELL EXECUTION:
NO utiliza subprocess, os.system, cmd.exe, powershell, sc.exe ni comandos externos.
Implementa `WindowsServicesBackend` utilizando psutil.win_service_iter() en Windows,
y `FakeServicesBackend` como mock en memoria para pruebas y entornos fuera de Windows.
"""

from __future__ import annotations

import sys
from typing import Any, Protocol

import psutil

from core.logger import get_logger
from tools.services.errors import ServiceAccessDeniedError, ServiceNotFoundError, ServicesError
from tools.services.models import WindowsServiceInfo, WindowsServiceStatus

logger = get_logger("jessyca.tools.services.backend")


class IWindowsServicesBackend(Protocol):
    """Protocolo de interfaz para la lectura de Servicios de Windows."""

    def enumerate_services(self, max_services: int) -> tuple[WindowsServiceInfo, ...]:
        ...

    def get_service(self, service_name: str) -> WindowsServiceInfo:
        ...

    def get_service_status(self, service_name: str) -> WindowsServiceStatus:
        ...

    def get_service_configuration(self, service_name: str) -> dict[str, Any]:
        ...


class FakeServicesBackend:
    """Backend Mock en memoria para pruebas y plataformas sin Servicios de Windows."""

    def __init__(self) -> None:
        self._services: dict[str, WindowsServiceInfo] = {}
        self._setup_defaults()

    def _setup_defaults(self) -> None:
        """Inicializa servicios de prueba simulados."""
        self.set_service(
            WindowsServiceInfo(
                service_name="wuauserv",
                display_name="Windows Update",
                status="running",
                start_type="automatic",
                service_type="share_process",
                dependencies=("rpcss",),
                description="Habilita la detección, descarga e instalación de actualizaciones de Windows.",
                binpath="C:\\Windows\\System32\\svchost.exe -k netsvcs -p",
            )
        )
        self.set_service(
            WindowsServiceInfo(
                service_name="Spooler",
                display_name="Print Spooler",
                status="running",
                start_type="automatic",
                service_type="own_process",
                dependencies=("http", "RPCSS"),
                description="Administra todas las colas de impresión locales y de red.",
                binpath="C:\\Windows\\System32\\spoolsv.exe",
            )
        )
        self.set_service(
            WindowsServiceInfo(
                service_name="JessycaHelperService",
                display_name="Jessyca MCP Helper Service",
                status="stopped",
                start_type="manual",
                service_type="own_process",
                dependencies=(),
                description="Servicio auxiliar de prueba para Jessyca Windows MCP.",
                binpath="C:\\Program Files\\Jessyca\\jessyca_service.exe",
            )
        )

    def set_service(self, service_info: WindowsServiceInfo) -> None:
        """Inserta o actualiza un servicio en el catálogo simulado."""
        self._services[service_info.service_name.lower()] = service_info

    def enumerate_services(self, max_services: int) -> tuple[WindowsServiceInfo, ...]:
        result = list(self._services.values())[:max_services]
        return tuple(result)

    def get_service(self, service_name: str) -> WindowsServiceInfo:
        key = service_name.lower()
        if key not in self._services:
            raise ServiceNotFoundError(service_name)
        return self._services[key]

    def get_service_status(self, service_name: str) -> WindowsServiceStatus:
        info = self.get_service(service_name)
        pid = 1234 if info.status == "running" else None
        return WindowsServiceStatus(status_str=info.status, pid=pid)

    def get_service_configuration(self, service_name: str) -> dict[str, Any]:
        info = self.get_service(service_name)
        return {
            "service_name": info.service_name,
            "display_name": info.display_name,
            "start_type": info.start_type,
            "service_type": info.service_type,
            "binpath": info.binpath,
            "dependencies": list(info.dependencies),
        }


class WindowsServicesBackend:
    """Backend real utilizando psutil.win_service_iter() en Windows (READ ONLY)."""

    def enumerate_services(self, max_services: int) -> tuple[WindowsServiceInfo, ...]:
        if not hasattr(psutil, "win_service_iter"):
            raise ServicesError("API de servicios psutil.win_service_iter no disponible en este sistema.")

        result: list[WindowsServiceInfo] = []

        try:
            for s in psutil.win_service_iter():
                if len(result) >= max_services:
                    break
                try:
                    info = s.as_dict()
                    name = info.get("name") or "unknown"
                    display = info.get("display_name") or name
                    status = info.get("status") or "unknown"
                    start_type = info.get("start_type") or "unknown"
                    binpath = info.get("binpath") or ""
                    description = info.get("description") or ""

                    result.append(
                        WindowsServiceInfo(
                            service_name=name,
                            display_name=display,
                            status=status,
                            start_type=start_type,
                            service_type="win32_service",
                            dependencies=(),
                            description=description,
                            binpath=binpath,
                        )
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
                    continue

            return tuple(result)
        except Exception as e:
            raise ServicesError(f"Error al enumerar servicios de Windows: {e}")

    def get_service(self, service_name: str) -> WindowsServiceInfo:
        if not hasattr(psutil, "win_service_get"):
            raise ServicesError("API psutil.win_service_get no disponible en este sistema.")

        try:
            s = psutil.win_service_get(service_name)
            info = s.as_dict()
            return WindowsServiceInfo(
                service_name=info.get("name") or service_name,
                display_name=info.get("display_name") or service_name,
                status=info.get("status") or "unknown",
                start_type=info.get("start_type") or "unknown",
                service_type="win32_service",
                dependencies=(),
                description=info.get("description") or "",
                binpath=info.get("binpath") or "",
            )
        except psutil.NoSuchProcess:
            raise ServiceNotFoundError(service_name)
        except psutil.AccessDenied:
            raise ServiceAccessDeniedError(service_name)
        except Exception as e:
            raise ServicesError(f"Error al obtener el servicio '{service_name}': {e}")

    def get_service_status(self, service_name: str) -> WindowsServiceStatus:
        info = self.get_service(service_name)
        try:
            s = psutil.win_service_get(service_name)
            pid = getattr(s, "pid", None)
            return WindowsServiceStatus(status_str=info.status, pid=pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return WindowsServiceStatus(status_str=info.status, pid=None)

    def get_service_configuration(self, service_name: str) -> dict[str, Any]:
        info = self.get_service(service_name)
        return {
            "service_name": info.service_name,
            "display_name": info.display_name,
            "start_type": info.start_type,
            "service_type": info.service_type,
            "binpath": info.binpath,
            "description": info.description,
        }


def get_default_services_backend() -> IWindowsServicesBackend:
    """Fábrica para obtener el backend de Servicios adecuado según el sistema operativo."""
    if sys.platform == "win32" and hasattr(psutil, "win_service_iter"):
        logger.info("Utilizando backend nativo de Servicios de Windows (WindowsServicesBackend).")
        return WindowsServicesBackend()
    logger.info("Utilizando backend simulado en memoria de Servicios (FakeServicesBackend).")
    return FakeServicesBackend()
