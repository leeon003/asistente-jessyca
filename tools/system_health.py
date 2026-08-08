"""Herramienta integrada de verificación de salud y diagnóstico del servidor FastMCP."""

from __future__ import annotations

from typing import Any, cast

from core.constants import APP_NAME, APP_VERSION
from core.types import JSONDict
from tools.base_tool import BaseMCPTool
from tools.discovery import mcp_tool
from utils.platform import check_windows_compatibility, get_system_metrics, is_admin


@mcp_tool
async def system_health(include_metrics: bool = True) -> dict[str, Any]:
    """Obtiene el estado de salud del servidor MCP, métricas del SO Windows, CPU, memoria RAM y permisos.

    Args:
        include_metrics: Si es True, incluye métricas detalladas de CPU y memoria RAM.
    """
    compat_info = check_windows_compatibility()

    health_data: dict[str, Any] = {
        "status": "healthy",
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "windows_platform": {
            "is_windows": compat_info.is_windows,
            "version": compat_info.version.value,
            "build_number": compat_info.build_number,
            "is_compatible": compat_info.is_compatible,
            "is_admin": is_admin(),
        },
    }

    if include_metrics:
        health_data["system_metrics"] = get_system_metrics()

    return health_data


class SystemHealthTool(BaseMCPTool):
    """Clase base de diagnóstico del sistema para la jerarquía BaseMCPTool."""

    def __init__(self) -> None:
        super().__init__(
            name="system_health",
            description="Obtiene el estado de salud del servidor MCP a través de la clase BaseMCPTool.",
        )

    def _get_input_schema(self) -> JSONDict:
        return {
            "type": "object",
            "properties": {
                "include_metrics": {
                    "type": "boolean",
                    "description": "Incluir métricas de sistema.",
                    "default": True,
                }
            },
        }

    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        include_metrics = bool(arguments.get("include_metrics", True))
        res = await system_health(include_metrics=include_metrics)
        return cast(JSONDict, res)
