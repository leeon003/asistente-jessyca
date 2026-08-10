"""Herramientas MCP de valores del Registro de Windows (Subetapa 06.4).

Implementa WindowsListRegistryValuesTool y WindowsGetRegistryValueTool integradas con BaseMCPTool y ToolRegistry.
"""

from __future__ import annotations

from typing import Any

from core.security_architecture import SecurityLevel
from tools.base import BaseMCPTool, ToolMetadata
from tools.registry.registry_service import RegistryService


class WindowsListRegistryValuesTool(BaseMCPTool):
    """Herramienta MCP para listar los valores contenidos en una clave del Registro autorizada."""

    def __init__(self, service: RegistryService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.registry",
                description="Lista los valores contenidos en una clave del Registro de Windows.",
                category="registry",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.service = service or RegistryService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        hive = str(parameters.get("hive") or "HKEY_CURRENT_USER")
        key_path = str(parameters.get("key_path") or parameters.get("path") or "")
        limit_val = parameters.get("limit")
        limit_int = int(limit_val) if limit_val else None

        values = self.service.list_values(hive, key_path, limit=limit_int)
        return {"values": [v.to_dict() for v in values]}


class WindowsGetRegistryValueTool(BaseMCPTool):
    """Herramienta MCP para consultar el detalle de un valor específico del Registro."""

    def __init__(self, service: RegistryService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.registry",
                description="Consulta el contenido y tipo de un valor específico del Registro de Windows.",
                category="registry",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.service = service or RegistryService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        hive = str(parameters.get("hive") or "HKEY_CURRENT_USER")
        key_path = str(parameters.get("key_path") or parameters.get("path") or "")
        value_name = str(parameters.get("value_name") or parameters.get("name") or "")

        return self.service.get_value(hive, key_path, value_name).to_dict()
