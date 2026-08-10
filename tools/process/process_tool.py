"""Herramientas MCP de procesos (Subetapa 06.3).

Implementa WindowsListProcessesTool, WindowsGetProcessTool y WindowsTerminateProcessTool integradas con BaseMCPTool y ToolRegistry.
"""

from __future__ import annotations

from typing import Any

from core.security_architecture import SecurityLevel
from tools.base import BaseMCPTool, ToolMetadata
from tools.process.process_service import ProcessService


class WindowsListProcessesTool(BaseMCPTool):
    """Herramienta MCP para listar los procesos activos del sistema Windows."""

    def __init__(self, service: ProcessService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.process",
                description="Lista los procesos activos ejecutándose en el sistema Windows.",
                category="process",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.service = service or ProcessService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        limit_val = parameters.get("limit")
        limit_int = int(limit_val) if limit_val else None
        return self.service.list_processes(limit=limit_int).to_dict()


class WindowsGetProcessTool(BaseMCPTool):
    """Herramienta MCP para obtener metadatos detallados de un proceso por PID."""

    def __init__(self, service: ProcessService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.process",
                description="Obtiene información detallada de un proceso específico por su PID.",
                category="process",
                risk_level=SecurityLevel.SAFE,
            )
        )
        self.service = service or ProcessService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        pid = parameters.get("pid")
        return self.service.get_process(pid).to_dict()


class WindowsTerminateProcessTool(BaseMCPTool):
    """Herramienta MCP para la terminación controlada de un proceso por PID."""

    def __init__(self, service: ProcessService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.process",
                description="Termina un proceso en ejecución por su PID.",
                category="process",
                risk_level=SecurityLevel.DANGEROUS,
                requires_confirmation=True,
            )
        )
        self.service = service or ProcessService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        pid = parameters.get("pid")
        expected_name = parameters.get("process_name")
        exp_time = parameters.get("creation_time")

        expected_creation_time = float(exp_time) if exp_time is not None else None
        expected_name_str = str(expected_name) if expected_name else None

        return self.service.terminate_process(
            pid=pid,
            expected_name=expected_name_str,
            expected_creation_time=expected_creation_time,
        ).to_dict()
