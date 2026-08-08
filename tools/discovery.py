"""Motor de autodescubrimiento e integración de herramientas MCP para Jessyca Windows MCP.

Conecta el ToolRegistry desacoplado con la instancia de FastMCP, permitiendo
registrar dinámicamente tanto subclases de BaseMCPTool como funciones decoradas con @mcp_tool.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from core.logger import get_logger
from tools.registry import ToolRegistry

logger = get_logger("jessyca.tools.discovery")

# Registro para funciones anotadas con @mcp_tool
_DECORATED_MCP_TOOLS: list[dict[str, Any]] = []


def mcp_tool(
    func: Callable[..., Any] | None = None,
    *,
    capability: str = "General",
    action: str = "execute",
    aliases: list[str] | None = None,
) -> Any:
    """Decorador para registrar automáticamente una función como herramienta MCP.

    Soporta uso directo `@mcp_tool` o parametrizado `@mcp_tool(capability='Filesystem', action='copy', aliases=['copiar'])`.
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        tool_entry = {
            "func": fn,
            "name": getattr(fn, "__name__", str(fn)),
            "capability": capability,
            "action": action,
            "aliases": aliases or [],
        }
        # Evitar duplicados
        if not any(item["func"] is fn for item in _DECORATED_MCP_TOOLS):
            _DECORATED_MCP_TOOLS.append(tool_entry)
        return fn

    if func is not None:
        return decorator(func)
    return decorator


class ToolDiscoveryEngine:
    """Motor de exploración e integración de herramientas MCP en FastMCP."""

    def __init__(self, registry: ToolRegistry | None = None, tools_base_dir: Path | str | None = None) -> None:
        self.registry = registry or ToolRegistry()
        if tools_base_dir is None:
            self.tools_dir = Path(__file__).resolve().parent
        else:
            self.tools_dir = Path(tools_base_dir)

    def discover_and_register(self, mcp_server: FastMCP) -> int:
        """Escanea el directorio tools/, registra en el ToolRegistry y vincula las herramientas en FastMCP.

        Returns:
            int: Cantidad total de herramientas registradas en FastMCP.
        """
        logger.info("Ejecutando autodescubrimiento desacoplado a través de ToolRegistry...")
        # 1. Ejecutar escaneo dinámico y fault-tolerant en ToolRegistry
        self.registry.discover(tools_dir=self.tools_dir)

        registered_names: set[str] = set()

        # 2. Registrar cada herramienta de BaseMCPTool del registro en el servidor FastMCP
        for tool in self.registry.list_tools():
            if tool.name not in registered_names:
                self._bind_tool_to_fastmcp(mcp_server, tool)
                registered_names.add(tool.name)

        # 3. Registrar funciones decoradas con @mcp_tool
        for entry in _DECORATED_MCP_TOOLS:
            decorated_func = entry["func"]
            func_name = entry["name"]
            if func_name not in registered_names:
                try:
                    mcp_server.add_tool(decorated_func)
                    registered_names.add(func_name)
                    logger.info(f"Herramienta decorada vinculada a FastMCP: '{func_name}'")
                except Exception as e:
                    logger.error(f"Error al vincular función decorada '{func_name}': {e}")

        total = len(registered_names)
        logger.info(f"Autodescubrimiento e integración completados. Total herramientas activas: {total}")
        return total

    def _bind_tool_to_fastmcp(self, mcp_server: FastMCP, tool: Any) -> None:
        """Vincula una herramienta del ToolRegistry a la instancia FastMCP."""

        async def _wrapper(arguments: dict[str, Any] | None = None) -> Any:
            args = arguments or {}
            result = await self.registry.execute_tool(tool.name, args)
            if result.is_success:
                return result.value
            raise RuntimeError(f"Error ejecutando {tool.name}: {result.error}")

        _wrapper.__name__ = tool.name
        _wrapper.__doc__ = tool.description

        mcp_server.add_tool(_wrapper)
