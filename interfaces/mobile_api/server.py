from __future__ import annotations

import sys

import uvicorn

from config.manager import get_settings
from config.settings import AppSettings
from core.logger import get_logger
from interfaces.mobile_api.app import create_mobile_api_app

logger = get_logger("jessyca.mobile_api.server")


def run_mobile_server(
    host: str | None = None,
    port: int | None = None,
    settings: AppSettings | None = None,
    force: bool = False,
) -> int:
    """Ejecuta el servidor Uvicorn para Mobile API Bridge de manera controlada.

    Args:
        host: Dirección IP o host de escucha (por defecto 127.0.0.1 en settings).
        port: Puerto TCP de escucha (por defecto 8765 en settings).
        settings: Instancia opcional de AppSettings.
        force: Si es True, anula el flag MOBILE_API_ENABLED=False desde CLI.

    Returns:
        0 si el servidor finalizó normalmente, 1 ante error de configuración o ejecución.
    """
    eff_settings = settings or get_settings()

    # Precedencia explícita: MOBILE_API_ENABLED=False impide levantar el servicio a menos que se fuerce vía CLI
    if not eff_settings.MOBILE_API_ENABLED and not force:
        logger.error(
            "[Mobile API Server] MOBILE_API_ENABLED es False. El servicio Mobile API está deshabilitado y no se iniciará. "
            "Para permitir el arranque, configure MOBILE_API_ENABLED=True o use --force desde la CLI."
        )
        print(
            "[ERROR] Servidor Mobile API deshabilitado por configuración (MOBILE_API_ENABLED=False).",
            file=sys.stderr,
        )
        return 1

    eff_host = host or eff_settings.MOBILE_API_HOST
    eff_port = port or eff_settings.MOBILE_API_PORT

    # Validación estricta de token y configuración antes de inicializar el servidor o escuchar
    try:
        app = create_mobile_api_app(settings=eff_settings)
    except ValueError as exc:
        logger.critical(f"[Mobile API Server] Error de configuración de seguridad: {exc}")
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    # Advertencia de red ante escucha no loopback
    if eff_host not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            f"[Mobile API Server] ADVERTENCIA DE RED: Servidor escuchando en interfaz no-loopback '{eff_host}'. "
            "El servicio será accesible desde la red local (LAN). Asegúrese de mantener un token secreto robusto."
        )

    logger.info(f"[Mobile API Server] Configurando servidor en {eff_host}:{eff_port}...")

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
