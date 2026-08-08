"""Servidor principal FastMCP para Jessyca Windows MCP.

Inicializa el servidor FastMCP, administra el ciclo de vida del servicio (STARTING -> INITIALIZING -> READY -> RUNNING -> SHUTTING_DOWN -> STOPPED),
integra el ToolRegistry desacoplado, ejecuta el registro dinámico de herramientas y administra la salud del servicio.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fastmcp import FastMCP

from config.manager import get_settings
from config.settings import AppSettings
from core.capability import CapabilityManager
from core.constants import APP_NAME, APP_VERSION
from core.contracts import ITool
from core.error_handler import setup_global_exception_hook
from core.event_bus import EventBus, get_event_bus
from core.logger import get_logger, setup_logger
from core.security import SecurityManager
from tools.registry import ToolRegistry
from utils.platform import check_windows_compatibility, is_admin

logger = get_logger("jessyca.server")


class ServerLifecycleState(StrEnum):
    """Estados del ciclo de vida del servidor MCP."""

    STARTING = "STARTING"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    RUNNING = "RUNNING"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    STOPPED = "STOPPED"


class JessycaMCPServer:
    """Gestor del servidor MCP con control formal de ciclo de vida y autodescubrimiento."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        registry: ToolRegistry | None = None,
        security_manager: SecurityManager | None = None,
        capability_manager: CapabilityManager | None = None,
        event_bus: EventBus | None = None,
        fastmcp_instance: FastMCP | None = None,
    ) -> None:
        self._state = ServerLifecycleState.STARTING
        self._start_time = time.perf_counter()
        self._created_at = datetime.now(UTC)

        self.settings = settings or get_settings()
        self.registry = registry or ToolRegistry()
        self.security_manager = security_manager or SecurityManager()
        self.capability_manager = capability_manager or CapabilityManager()
        self.event_bus = event_bus or get_event_bus()

        # Configurar FastMCP
        self.fastmcp = fastmcp_instance or FastMCP(name=self.settings.MCP_SERVER_NAME)

    @property
    def state(self) -> ServerLifecycleState:
        """Obtiene el estado actual del ciclo de vida del servidor."""
        return self._state

    @property
    def uptime_seconds(self) -> float:
        """Calcula el tiempo transcurrido de ejecución del servidor en segundos."""
        return round(time.perf_counter() - self._start_time, 2)

    def initialize(self, tools_dir: str | None = None) -> bool:
        """Inicializa el servidor, el logging, descubre e indexa herramientas en FastMCP.

        Returns:
            bool: True si la inicialización fue exitosa.
        """
        self._state = ServerLifecycleState.INITIALIZING
        logger.info(f"Inicializando {APP_NAME} v{APP_VERSION} [Servidor: '{self.settings.MCP_SERVER_NAME}']...")

        # 1. Configurar logging centralizado
        setup_logger(
            log_level=self.settings.LOG_LEVEL.value,
            log_file=self.settings.LOG_FILE_PATH,
        )

        # 2. Configurar captura global de excepciones
        setup_global_exception_hook()

        # 3. Descubrir e indexar herramientas mediante el ToolRegistry
        discovered_count = self.registry.discover(tools_dir=tools_dir)
        logger.info(f"ToolRegistry descubrió {discovered_count} herramientas en el sistema de archivos.")

        # 4. Indexar capacidades en el CapabilityManager
        self.capability_manager.discover_capabilities(self.registry)

        # 5. Puente dinámico: Registrar herramientas descubiertas en el servidor FastMCP
        self._register_tools_to_fastmcp()

        # 6. Registrar handler diagnóstico de Health Check
        self._register_health_check_tool()

        self._state = ServerLifecycleState.READY
        self.event_bus.publish("server:ready", {"server_name": self.settings.MCP_SERVER_NAME})
        logger.info(f"Servidor '{self.settings.MCP_SERVER_NAME}' inicializado exitosamente (Estado: READY).")
        return True

    def _register_tools_to_fastmcp(self) -> int:
        """Registra dinámicamente cada herramienta del ToolRegistry en FastMCP sin código manual."""
        registered_tools = self.registry.list_tools()
        count = 0

        for tool in registered_tools:
            try:
                # Inyección dinámica de la función ejecutable en FastMCP
                self._bind_tool_to_fastmcp(tool)
                count += 1
            except Exception as e:
                logger.error(f"Error al vincular la herramienta '{tool.name}' en FastMCP: {e}")

        logger.info(f"Vinculadas dinámicamente {count} herramientas en el servidor FastMCP.")
        return count

    def _bind_tool_to_fastmcp(self, tool: ITool) -> None:
        """Crea una función wrapper con tipado explícito para la herramienta y la registra en FastMCP."""
        tool_name = tool.name
        tool_desc = tool.description

        # Crear wrapper dinámico aceptando argumentos genéricos
        async def tool_wrapper(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
            args = arguments or {}
            res = await tool.execute(args)
            if res.is_success:
                return res.value
            raise RuntimeError(str(res.error))

        tool_wrapper.__name__ = tool_name
        tool_wrapper.__doc__ = tool_desc

        # Registrar en FastMCP
        self.fastmcp.add_tool(tool_wrapper)

    def _register_health_check_tool(self) -> None:
        """Registra la herramienta inofensiva de diagnóstico Health Check en FastMCP."""
        server_instance = self

        async def server_health_check() -> dict[str, Any]:
            """Devuelve el estado de salud del servidor MCP, ciclo de vida y plataforma Windows."""
            return server_instance.get_health_status()

        server_health_check.__name__ = "server_health"
        server_health_check.__doc__ = "Obtiene el diagnóstico completo de salud y ciclo de vida del servidor MCP."

        try:
            self.fastmcp.add_tool(server_health_check)
        except Exception as e:
            logger.debug(f"Health check ya registrado o nota de vinculación: {e}")

    def get_health_status(self) -> dict[str, Any]:
        """Obtiene un diccionario con las métricas diagnósticas puras del servidor (sin modificar el SO)."""
        compat = check_windows_compatibility()
        return {
            "server_status": self._state.value,
            "server_name": self.settings.MCP_SERVER_NAME,
            "version": APP_VERSION,
            "environment": self.settings.ENVIRONMENT.value,
            "uptime_seconds": self.uptime_seconds,
            "registered_tools_count": len(self.registry.list_tools()),
            "created_at": self._created_at.isoformat(),
            "windows_info": {
                "is_windows": compat.is_windows,
                "version": compat.version.value,
                "build_number": compat.build_number,
                "is_compatible": compat.is_compatible,
                "is_admin": is_admin(),
            },
        }

    def run(self) -> None:
        """Inicia la ejecución activa del servidor MCP."""
        if self._state != ServerLifecycleState.READY:
            self.initialize()

        self._state = ServerLifecycleState.RUNNING
        self.event_bus.publish("server:running", {"server_name": self.settings.MCP_SERVER_NAME})
        logger.info(f"Servidor '{self.settings.MCP_SERVER_NAME}' ejecuntándose activamente (Estado: RUNNING)...")
        try:
            self.fastmcp.run()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Ejecuta el apagado controlado del servidor y libera recursos."""
        if self._state in (ServerLifecycleState.SHUTTING_DOWN, ServerLifecycleState.STOPPED):
            return

        self._state = ServerLifecycleState.SHUTTING_DOWN
        logger.info(f"Iniciando apagado controlado del servidor '{self.settings.MCP_SERVER_NAME}'...")
        self.event_bus.publish("server:shutdown", {"server_name": self.settings.MCP_SERVER_NAME})

        self._state = ServerLifecycleState.STOPPED
        logger.info(f"Servidor '{self.settings.MCP_SERVER_NAME}' detenido (Estado: STOPPED).")


# Instancia Singleton Global
_global_server_instance: JessycaMCPServer | None = None


def create_mcp_server(
    server_name: str | None = None,
    tools_dir: str | None = None,
) -> JessycaMCPServer:
    """Factory function que crea e inicializa un nuevo JessycaMCPServer."""
    global _global_server_instance
    settings = get_settings()
    if server_name:
        settings.MCP_SERVER_NAME = server_name

    server = JessycaMCPServer(settings=settings)
    server.initialize(tools_dir=tools_dir)
    _global_server_instance = server
    return server


def get_mcp_server() -> JessycaMCPServer:
    """Obtiene o crea la instancia global del JessycaMCPServer."""
    global _global_server_instance
    if _global_server_instance is None:
        _global_server_instance = create_mcp_server()
    return _global_server_instance
