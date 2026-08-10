"""Herramientas MCP de claves del Registro de Windows (Subetapa 06.4).

Implementa WindowsListRegistrySubkeysTool y WindowsGetRegistryKeyTool integradas con BaseMCPTool y ToolRegistry.
"""

from __future__ import annotations

from typing import Any

from core.security_architecture import SecurityLevel
from tools.base import BaseMCPTool, ToolMetadata
from tools.registry.registry_service import RegistryService


class WindowsListRegistrySubkeysTool(BaseMCPTool):
    """Herramienta MCP para listar las subclaves de una clave del Registro autorizada."""

    def __init__(self, service: RegistryService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.registry",
                description="Lista las subclaves de una clave específica del Registro de Windows.",
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

        subkeys = self.service.list_subkeys(hive, key_path, limit=limit_int)
        return {"subkeys": [s.to_dict() for s in subkeys]}


class WindowsGetRegistryKeyTool(BaseMCPTool):
    """Herramienta MCP para obtener metadatos e información de una clave del Registro."""

    def __init__(self, service: RegistryService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.registry",
                description="Obtiene información y metadatos de una clave del Registro de Windows.",
                category="registry",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.service = service or RegistryService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        hive = str(parameters.get("hive") or "HKEY_CURRENT_USER")
        key_path = str(parameters.get("key_path") or parameters.get("path") or "")
        return self.service.get_key_info(hive, key_path).to_dict()
