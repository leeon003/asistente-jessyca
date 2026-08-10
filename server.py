"""Servidor principal FastMCP para Jessyca Windows MCP (Subetapa 05.1).

Proporciona integración y retrocompatibilidad con el paquete server/ y la suite previa.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from config.settings import AppSettings
from core.event_bus import EventBus, get_event_bus
from core.logger import get_logger
from server.app import JessycaMCPServer as CoreMCPServer
from server.boundary import ExecutionResult, IExecutionBoundary
from server.context import RequestContext
from server.health import HealthCheckResult, HealthStatus
from server.lifecycle import LifecycleState, ServerLifecycleManager
from tools.registry import ToolRegistry, get_tool_registry
from utils.platform import check_windows_compatibility, is_admin

logger = get_logger("jessyca.server")


class ServerLifecycleState(StrEnum):
    """Estados del ciclo de vida del servidor MCP (compatibilidad)."""

    STARTING = "STARTING"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    RUNNING = "RUNNING"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    STOPPED = "STOPPED"


class JessycaMCPServer(CoreMCPServer):
    """Servidor MCP principal con soporte de compatibilidad legacy y FastMCP."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        tool_registry: ToolRegistry | None = None,
        lifecycle_manager: ServerLifecycleManager | None = None,
        execution_boundary: IExecutionBoundary | None = None,
        registry: ToolRegistry | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        tr = tool_registry or registry or get_tool_registry()
        super().__init__(
            settings=settings,
            tool_registry=tr,
            lifecycle_manager=lifecycle_manager,
            execution_boundary=execution_boundary,
        )
        self._legacy_state = ServerLifecycleState.STARTING
        self.registry = self.tool_registry
        self.event_bus = event_bus or get_event_bus()

    @property
    def state(self) -> Any:  # type: ignore[override]
        """Obtiene el estado actual del ciclo de vida del servidor."""
        return self._legacy_state

    def initialize(self) -> bool:  # type: ignore[override]
        """Inicializa el servidor y cambia el estado a READY."""
        self._legacy_state = ServerLifecycleState.INITIALIZING
        super().initialize()
        self._legacy_state = ServerLifecycleState.READY
        return True

    def start(self) -> None:
        """Inicia el servidor y cambia el estado a RUNNING."""
        super().start()
        self._legacy_state = ServerLifecycleState.RUNNING

    def shutdown(self) -> None:
        """Detiene el servidor y cambia el estado a STOPPED."""
        self._legacy_state = ServerLifecycleState.SHUTTING_DOWN
        super().shutdown()
        self._legacy_state = ServerLifecycleState.STOPPED

    def get_health_status(self) -> dict[str, Any]:
        """Obtiene un diccionario con métricas diagnósticas puras (retrocompatibilidad)."""
        res = self.check_health()
        compat = check_windows_compatibility()
        data = res.to_dict()
        data["server_status"] = self._legacy_state.value
        data["environment"] = self.settings.ENVIRONMENT.value
        data["windows_info"] = {
            "is_windows": compat.is_windows,
            "version": compat.version.value,
            "build_number": compat.build_number,
            "is_compatible": compat.is_compatible,
            "is_admin": is_admin(),
        }
        return data

    def run(self) -> None:
        """Ejecuta activamente el servidor MCP."""
        self.start()


def create_mcp_server(
    server_name: str | None = None,
    tools_dir: str | None = None,
) -> JessycaMCPServer:
    """Factory function que crea e inicializa un JessycaMCPServer."""
    settings = AppSettings()
    if server_name:
        settings.MCP_SERVER_NAME = server_name

    server = JessycaMCPServer(settings=settings)
    server.initialize()
    return server


_global_server_instance: JessycaMCPServer | None = None


def get_mcp_server() -> JessycaMCPServer:
    """Obtiene o crea la instancia global del JessycaMCPServer."""
    global _global_server_instance
    if _global_server_instance is None:
        _global_server_instance = create_mcp_server()
    return _global_server_instance
