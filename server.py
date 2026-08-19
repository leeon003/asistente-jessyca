"""Servidor principal FastMCP para Jessyca Windows MCP (Subetapa 05.1).

Proporciona integración y retrocompatibilidad con el paquete server/ y la suite previa.
"""

from __future__ import annotations

from config.settings import AppSettings
from core.event_bus import EventBus, get_event_bus
from core.logger import get_logger
from server.app import JessycaMCPServer, create_mcp_server, get_mcp_server
from server.boundary import ExecutionResult, IExecutionBoundary
from server.context import RequestContext
from server.health import HealthCheckResult, HealthStatus
from server.lifecycle import LifecycleState as ServerLifecycleState, ServerLifecycleManager
from tools.tool_registry import ToolRegistry, get_tool_registry
from utils.platform import check_windows_compatibility, is_admin

logger = get_logger("jessyca.server")

__all__ = [
    "JessycaMCPServer",
    "ServerLifecycleState",
    "create_mcp_server",
    "get_mcp_server",
]
