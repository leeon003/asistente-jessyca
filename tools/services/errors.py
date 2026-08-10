"""Excepciones estructuradas para herramientas de inspección de Servicios de Windows (Subetapa 06.5)."""

from __future__ import annotations

from core.exceptions import MCPError


class ServicesError(MCPError):
    """Error base para operaciones sobre Servicios de Windows."""

    def __init__(self, message: str = "Error en la consulta de Servicios de Windows.") -> None:
        super().__init__(message)


class ServiceNameError(ServicesError):
    """Error de validación o seguridad en el nombre del Servicio de Windows."""

    def __init__(self, message: str = "Nombre de servicio inválido o con caracteres no autorizados.") -> None:
        super().__init__(message)


class ServiceNotFoundError(ServicesError):
    """El Servicio de Windows especificado no existe o no fue encontrado."""

    def __init__(self, service_name: str) -> None:
        super().__init__(f"Servicio de Windows no encontrado: '{service_name}'.")
        self.service_name = service_name


class ServiceAccessDeniedError(ServicesError):
    """El sistema operativo denegó el acceso de lectura al Servicio de Windows."""

    def __init__(self, service_name: str) -> None:
        super().__init__(f"Acceso Denegado por el sistema operativo al consultar el servicio: '{service_name}'.")
        self.service_name = service_name


class ServiceLimitError(ServicesError):
    """La consulta excede el límite máximo configurado de servicios o dependencias."""

    def __init__(self, current_count: int, max_limit: int) -> None:
        super().__init__(f"Límite de consulta de servicios excedido ({current_count}). Máximo permitido: {max_limit}.")
        self.current_count = current_count
        self.max_limit = max_limit
