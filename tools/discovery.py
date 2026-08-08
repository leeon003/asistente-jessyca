"""Motor de autodescubrimiento e integración de herramientas MCP para Jessyca Windows MCP.

Proporciona capacidad de escaneo independiente de la carpeta tools/ y sus subcarpetas temáticas,
validando metadatos, detectando clases derivantes de BaseMCPTool y registrándolas en ToolRegistry
y CapabilityManager de forma desacoplada de FastMCP.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.capability import CapabilityManager
from core.contracts import ITool
from core.logger import get_logger
from tools.registry import ToolRegistry

logger = get_logger("jessyca.tools.discovery")

# Registro para funciones anotadas con @mcp_tool
_DECORATED_MCP_TOOLS: list[dict[str, Any]] = []


def mcp_tool(
    func: Callable[..., Any] | None = None,
    *,
    capability: str = "general",
    action: str = "execute",
    aliases: list[str] | None = None,
) -> Any:
    """Decorador para registrar automáticamente una función como herramienta MCP.

    Soporta uso directo `@mcp_tool` o parametrizado `@mcp_tool(capability='filesystem', action='copy', aliases=['copiar'])`.
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        tool_entry = {
            "func": fn,
            "name": getattr(fn, "__name__", str(fn)),
            "capability": capability,
            "action": action,
            "aliases": aliases or [],
        }
        # Evitar duplicados por función
        if not any(item["func"] is fn for item in _DECORATED_MCP_TOOLS):
            _DECORATED_MCP_TOOLS.append(tool_entry)
        return fn

    if func is not None:
        return decorator(func)
    return decorator


class ToolDiscoveryEngine:
    """Motor de exploración e integración desacoplado de herramientas MCP."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        capability_manager: CapabilityManager | None = None,
        tools_base_dir: Path | str | None = None,
    ) -> None:
        self.registry = registry or ToolRegistry()
        self.capability_manager = capability_manager or CapabilityManager()

        if tools_base_dir is None:
            self.tools_dir = Path(__file__).resolve().parent
        else:
            self.tools_dir = Path(tools_base_dir)

    def discover_tools(self) -> list[ITool]:
        """Escanea recursivamente el directorio de herramientas y subdirectorios temáticos.

        Descubre clases que implementan BaseMCPTool o ITool, las valida, previene duplicados
        y las registra en el ToolRegistry y CapabilityManager de forma totalmente independiente a FastMCP.

        Returns:
            list[ITool]: Lista de herramientas descubiertas y registradas con éxito.
        """
        logger.info(f"Iniciando autodescubrimiento independiente en: {self.tools_dir}")
        if not self.tools_dir.exists():
            logger.warning(f"Directorio de herramientas no encontrado: {self.tools_dir}")
            return []

        # 1. Escaneo vía ToolRegistry (File-based Fault-Tolerant Dynamic Import)
        self.registry.discover(tools_dir=self.tools_dir)

        # 2. Indexar en CapabilityManager
        self.capability_manager.discover_capabilities(self.registry)

        discovered = self.registry.list_tools()
        logger.info(f"Autodescubrimiento independiente finalizado. Total herramientas activas: {len(discovered)}")
        return discovered

    def discover_and_register(self, mcp_server: Any) -> int:
        """Escanea el directorio, registra en ToolRegistry/CapabilityManager y vincula las herramientas en FastMCP.

        Args:
            mcp_server: Instancia de FastMCP u objeto servidor equivalente.

        Returns:
            int: Cantidad total de herramientas registradas en el servidor MCP.
        """
        tools = self.discover_tools()
        registered_names: set[str] = set()

        # Registrar herramientas registradas en FastMCP
        for tool in tools:
            if tool.name not in registered_names:
                try:
                    self._bind_tool_to_mcp(mcp_server, tool)
                    registered_names.add(tool.name)
                except Exception as e:
                    logger.error(f"Error al vincular herramienta '{tool.name}' al servidor MCP: {e}")

        # Registrar funciones decoradas con @mcp_tool
        for entry in _DECORATED_MCP_TOOLS:
            decorated_func = entry["func"]
            func_name = entry["name"]
            if func_name not in registered_names:
                try:
                    if hasattr(mcp_server, "add_tool"):
                        mcp_server.add_tool(decorated_func)
                    registered_names.add(func_name)
                    logger.info(f"Herramienta decorada vinculada a servidor MCP: '{func_name}'")
                except Exception as e:
                    logger.error(f"Error al vincular función decorada '{func_name}': {e}")

        return len(registered_names)

    def _bind_tool_to_mcp(self, mcp_server: Any, tool: ITool) -> None:
        """Vincula una herramienta ITool al servidor MCP."""
        if not hasattr(mcp_server, "add_tool"):
            return

        async def _wrapper(arguments: dict[str, Any] | None = None) -> Any:
            args = arguments or {}
            result = await self.registry.execute_tool(tool.name, args)
            if result.is_success:
                return result.value
            raise RuntimeError(f"Error ejecutando {tool.name}: {result.error}")

        _wrapper.__name__ = tool.name
        _wrapper.__doc__ = tool.description

        mcp_server.add_tool(_wrapper)
