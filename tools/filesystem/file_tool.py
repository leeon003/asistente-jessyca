"""Herramientas MCP de archivos (Subetapa 06.2).

Implementa WindowsReadFileTool, WindowsWriteFileTool y WindowsDeleteFileTool integradas con BaseMCPTool y ToolRegistry.
"""

from __future__ import annotations

from typing import Any

from core.security_architecture import SecurityLevel
from tools.base import BaseMCPTool, ToolMetadata
from tools.filesystem.filesystem_service import FilesystemService


class WindowsReadFileTool(BaseMCPTool):
    """Herramienta MCP para lectura de archivos dentro del sandbox."""

    def __init__(self, service: FilesystemService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.files",
                description="Lee el contenido de un archivo regular dentro del sandbox.",
                category="filesystem",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.service = service or FilesystemService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        path = str(parameters.get("path") or "").strip()
        enc = str(parameters.get("encoding") or "utf-8").strip()
        return self.service.read_file(path, encoding=enc).to_dict()


class WindowsWriteFileTool(BaseMCPTool):
    """Herramienta MCP para escritura atómica de archivos dentro del sandbox."""

    def __init__(self, service: FilesystemService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.files",
                description="Escribe contenido de forma atómica en un archivo dentro del sandbox.",
                category="filesystem",
                risk_level=SecurityLevel.WARNING,
                requires_confirmation=True,
            )
        )
        self.service = service or FilesystemService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        path = str(parameters.get("path") or "").strip()
        content = str(parameters.get("content") or "")
        enc = str(parameters.get("encoding") or "utf-8").strip()
        return self.service.write_file(path, content, encoding=enc).to_dict()


class WindowsDeleteFileTool(BaseMCPTool):
    """Herramienta MCP para eliminación segura de archivos dentro del sandbox."""

    def __init__(self, service: FilesystemService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.files",
                description="Elimina un archivo regular existente dentro del sandbox.",
                category="filesystem",
                risk_level=SecurityLevel.DANGEROUS,
                requires_confirmation=True,
            )
        )
        self.service = service or FilesystemService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        path = str(parameters.get("path") or "").strip()
        return self.service.delete_file(path).to_dict()
