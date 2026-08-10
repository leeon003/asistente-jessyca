"""Herramientas MCP de Servicios de Windows (Subetapa 06.5).

Implementa WindowsListServicesTool, WindowsGetServiceTool, WindowsGetServiceStatusTool
y WindowsGetServiceConfigurationTool integradas con BaseMCPTool y ToolRegistry.
"""

from __future__ import annotations

from typing import Any

from core.security_architecture import SecurityLevel
from tools.base import BaseMCPTool, ToolMetadata
from tools.services.services_service import ServicesService


class WindowsListServicesTool(BaseMCPTool):
    """Herramienta MCP para listar los Servicios de Windows activos en el sistema."""

    def __init__(self, service: ServicesService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.services",
                description="Lista los Servicios de Windows activos en el sistema.",
                category="services",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.service = service or ServicesService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        limit_val = parameters.get("limit")
        limit_int = int(limit_val) if limit_val else None
        return self.service.list_services(limit=limit_int).to_dict()


class WindowsGetServiceTool(BaseMCPTool):
    """Herramienta MCP para obtener la información y metadatos de un Servicio de Windows."""

    def __init__(self, service: ServicesService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.services",
                description="Obtiene metadatos informativos de un Servicio de Windows por nombre.",
                category="services",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.service = service or ServicesService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        service_name = str(parameters.get("service_name") or parameters.get("name") or "")
        return self.service.get_service(service_name).to_dict()


class WindowsGetServiceStatusTool(BaseMCPTool):
    """Herramienta MCP para consultar el estado de ejecución actual de un Servicio de Windows."""

    def __init__(self, service: ServicesService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.services",
                description="Consulta el estado de ejecución y PID actual de un Servicio de Windows.",
                category="services",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.service = service or ServicesService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        service_name = str(parameters.get("service_name") or parameters.get("name") or "")
        return self.service.get_service_status(service_name).to_dict()


class WindowsGetServiceConfigurationTool(BaseMCPTool):
    """Herramienta MCP para consultar la configuración de inicio de un Servicio de Windows."""

    def __init__(self, service: ServicesService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.services",
                description="Consulta el tipo de inicio y ruta ejecutable de un Servicio de Windows.",
                category="services",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.service = service or ServicesService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        service_name = str(parameters.get("service_name") or parameters.get("name") or "")
        return self.service.get_service_configuration(service_name)
