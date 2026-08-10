"""Herramientas MCP de directorios (Subetapa 06.2).

Implementa WindowsListDirectoryTool y WindowsCreateDirectoryTool integradas con BaseMCPTool y ToolRegistry.
"""

from __future__ import annotations

from typing import Any

from core.security_architecture import SecurityLevel
from tools.base import BaseMCPTool, ToolMetadata
from tools.filesystem.filesystem_service import FilesystemService


class WindowsListDirectoryTool(BaseMCPTool):
    """Herramienta MCP para listar entradas de un directorio dentro del sandbox."""

    def __init__(self, service: FilesystemService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.files",
                description="Lista los archivos y subdirectorios contenidos dentro de una ruta del sandbox.",
                category="filesystem",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.service = service or FilesystemService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        path = str(parameters.get("path") or ".").strip()
        return self.service.list_directory(path).to_dict()


class WindowsCreateDirectoryTool(BaseMCPTool):
    """Herramienta MCP para crear directorios dentro del sandbox."""

    def __init__(self, service: FilesystemService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.files",
                description="Crea un nuevo directorio (y padres necesarios) dentro del sandbox.",
                category="filesystem",
                risk_level=SecurityLevel.WARNING,
            )
        )
        self.service = service or FilesystemService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        path = str(parameters.get("path") or "").strip()
        created = self.service.create_directory(path)
        return {"created_directory": created}
