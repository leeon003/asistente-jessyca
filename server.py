"""Servidor principal FastMCP para Jessyca Windows MCP.

Inicializa el servidor FastMCP, aplica configuraciones globales, ejecuta el motor de
autodescubrimiento dinámico de herramientas y administra la salud del servicio.
"""

from __future__ import annotations

from fastmcp import FastMCP

from config.manager import get_settings
from core.constants import APP_VERSION
from core.error_handler import setup_global_exception_hook
from core.logger import get_logger, setup_logger
from tools.discovery import ToolDiscoveryEngine
from utils.platform import check_windows_compatibility

logger = get_logger("jessyca.server")


def create_mcp_server(
    server_name: str | None = None,
    tools_dir: str | None = None,
) -> FastMCP:
    """Crea y configura una nueva instancia del servidor FastMCP con autodescubrimiento.

    Args:
        server_name: Nombre identificador del servidor. Si es None, utiliza la configuración.
        tools_dir: Directorio opcional para el descubrimiento de herramientas.

    Returns:
        Instancia de FastMCP configurada y lista para ejecutar.
    """
    settings = get_settings()

    # 1. Configurar logging centralizado
    setup_logger(
        log_level=settings.LOG_LEVEL.value,
        log_file=settings.LOG_FILE_PATH,
    )

    # 2. Configurar hook de captura global de excepciones
    setup_global_exception_hook()

    # 3. Diagnóstico de plataforma Windows
    compat = check_windows_compatibility()
    logger.info(f"Diagnóstico SO Windows: {compat.details}")

    effective_name = server_name or settings.MCP_SERVER_NAME
    logger.info(f"Inicializando servidor FastMCP '{effective_name}' v{APP_VERSION}...")

    # 4. Instanciar FastMCP
    mcp_server = FastMCP(
        name=effective_name,
    )

    # 5. Ejecutar autodescubrimiento dinámico de herramientas
    discovery_engine = ToolDiscoveryEngine(tools_base_dir=tools_dir)
    registered_count = discovery_engine.discover_and_register(mcp_server)

    logger.info(
        f"Servidor FastMCP '{effective_name}' inicializado con éxito con {registered_count} herramientas."
    )
    return mcp_server
