"""Servidor Uvicorn para JESSYCA Mobile API Bridge.

Maneja el ciclo de vida, arranque asíncrono y graceful shutdown del servidor HTTP.
"""

from __future__ import annotations

import uvicorn

from config.manager import get_settings
from core.logger import get_logger
from interfaces.mobile_api.app import create_mobile_api_app

logger = get_logger("jessyca.mobile_api.server")


def run_mobile_server(host: str | None = None, port: int | None = None) -> int:
    """Ejecuta el servidor Uvicorn para Mobile API Bridge de manera controlada.

    Args:
        host: Dirección IP o host de escucha (por defecto según settings).
        port: Puerto TCP de escucha (por defecto según settings).

    Returns:
        0 si el servidor finalizó normalmente, 1 ante error crítico.
    """
    settings = get_settings()

    if not settings.MOBILE_API_ENABLED:
        logger.warning("[Mobile API Server] MOBILE_API_ENABLED es False en la configuración.")

    eff_host = host or settings.MOBILE_API_HOST
    eff_port = port or settings.MOBILE_API_PORT

    logger.info(f"[Mobile API Server] Configurando servidor en {eff_host}:{eff_port}...")

    app = create_mobile_api_app(settings=settings)

    config = uvicorn.Config(
        app=app,
        host=eff_host,
        port=eff_port,
        log_level="info",
        access_log=True,
    )

    server = uvicorn.Server(config)

    try:
        logger.info(f"[Mobile API Server] Iniciando escucha en http://{eff_host}:{eff_port}")
        server.run()
        logger.info("[Mobile API Server] Servidor Uvicorn finalizado limpiamente.")
        return 0
    except KeyboardInterrupt:
        logger.info("[Mobile API Server] Interrupción por teclado recibida; deteniendo servidor...")
        return 0
    except Exception as exc:
        logger.critical(f"[Mobile API Server] Error fatal en servidor: {exc}", exc_info=True)
        return 1
