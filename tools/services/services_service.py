"""Servicio seguro de lectura e inspección de Servicios de Windows (Subetapa 06.5 - READ ONLY).

GARANTÍA DE CERO ESCRITURA Y CERO SHELL EXECUTION:
Únicamente expone operaciones de consulta e inspección (`list_services`, `get_service`, `get_service_status`, `get_service_configuration`).
Integra la validación previa de seguridad de nombres de servicios (`ServiceNameSecurityManager`) y la abstracción de backend (`IWindowsServicesBackend`).
"""

from __future__ import annotations

from config.settings import AppSettings
from core.logger import get_logger
from tools.services.backend import IWindowsServicesBackend, get_default_services_backend
from tools.services.errors import ServiceLimitError
from tools.services.models import (
    WindowsServiceInfo,
    WindowsServiceQueryResult,
    WindowsServiceStatus,
)
from tools.services.name_security import ServiceNameSecurityManager

logger = get_logger("jessyca.tools.services.service")


class ServicesService:
    """Servicio de lectura e inspección segura de Servicios de Windows."""

    def __init__(

        self,
        name_security_manager: ServiceNameSecurityManager | None = None,
        backend: IWindowsServicesBackend | None = None,
    ) -> None:
        self.name_security = name_security_manager or ServiceNameSecurityManager()
        self.backend = backend or get_default_services_backend()

        settings = AppSettings()
        self.max_list_entries: int = settings.SERVICES_MAX_LIST_ENTRIES
        self.query_timeout: float = settings.SERVICES_QUERY_TIMEOUT

    def list_services(self, limit: int | None = None) -> WindowsServiceQueryResult:
        """Lista los servicios activos del sistema con límite acotado."""
        max_entries = limit if (limit and limit > 0) else self.max_list_entries
        services_tuple = self.backend.enumerate_services(max_services=max_entries)

        if len(services_tuple) > self.max_list_entries:
            raise ServiceLimitError(len(services_tuple), self.max_list_entries)

        return WindowsServiceQueryResult(
            count=len(services_tuple),
            truncated=len(services_tuple) >= max_entries,
            services=services_tuple,
        )

    def get_service(self, service_name: str) -> WindowsServiceInfo:
        """Obtiene la información y metadatos de un servicio de Windows validado."""
        clean_name = self.name_security.validate_and_sanitize_name(service_name)
        return self.backend.get_service(clean_name)

    def get_service_status(self, service_name: str) -> WindowsServiceStatus:
        """Obtiene el estado de ejecución y PID (si está activo) de un servicio validado."""
        clean_name = self.name_security.validate_and_sanitize_name(service_name)
        return self.backend.get_service_status(clean_name)

    def get_service_configuration(self, service_name: str) -> dict[str, object]:
        """Obtiene la configuración de inicio e información técnica de un servicio validado."""
        clean_name = self.name_security.validate_and_sanitize_name(service_name)
        return self.backend.get_service_configuration(clean_name)
