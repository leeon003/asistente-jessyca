"""Servidor Uvicorn para JESSYCA Web Bridge (OpenAI-Compatible).

Maneja el ciclo de vida y la escucha en red para el puente con Open WebUI.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from core.logger import get_logger
from interfaces.webui_bridge.app import create_webui_bridge_app

logger = get_logger("jessyca.webui_bridge.server")

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8088


def _verify_health(url: str, timeout_seconds: float = 1.0) -> bool:
    """Comprueba el endpoint /health usando la biblioteca estándar."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            if response.status == 200:
                payload = json.loads(response.read().decode("utf-8"))
                return payload.get("status") == "ok"
    except Exception:
        return False
    return False


def run_webui_server(
    host: str | None = None,
    port: int | None = None,
    auth_token: str | None = None,
    timeout_seconds: float | None = None,
    perform_health_check: bool = True,
) -> int:
    """Inicia el servidor Uvicorn para JESSYCA Web Bridge de manera controlada.

    Args:
        host: Host o interfaz de escucha (por defecto 0.0.0.0).
        port: Puerto TCP de escucha (por defecto 8088).
        auth_token: Token de autenticación Bearer opcional.
        timeout_seconds: Timeout de procesamiento en segundos.
        perform_health_check: Si debe comprobar el endpoint /health antes de confirmar inicio.

    Returns:
        0 si finalizó normalmente, 1 ante error crítico.
    """
    eff_host = host or os.getenv("WEBUI_BRIDGE_HOST", DEFAULT_HOST)
    raw_port = port if port is not None else os.getenv("WEBUI_BRIDGE_PORT", str(DEFAULT_PORT))
    try:
        eff_port = int(raw_port)
    except (ValueError, TypeError):
        eff_port = DEFAULT_PORT

    logger.info(f"[WebUI Bridge Server] Configurando servidor en http://{eff_host}:{eff_port}...")

    try:
        app = create_webui_bridge_app(
            auth_token=auth_token,
            timeout_seconds=timeout_seconds,
        )
    except ValueError as val_err:
        logger.critical(f"[WebUI Bridge Server] Error de configuración: {val_err}")
        print(f"[ERROR] {val_err}", file=sys.stderr)
        return 1

    config = uvicorn.Config(
        app=app,
        host=eff_host,
        port=eff_port,
        log_level="info",
        access_log=True,
    )

    server = uvicorn.Server(config)

    if not perform_health_check:
        try:
            logger.info(f"[WebUI Bridge Server] Iniciando escucha en http://{eff_host}:{eff_port}")
            server.run()
            return 0
        except KeyboardInterrupt:
            logger.info("[WebUI Bridge Server] Servidor detenido por el usuario.")
            return 0
        except Exception as exc:
            logger.critical(f"[WebUI Bridge Server] Error fatal en servidor: {exc}", exc_info=True)
            return 1

    # Arranque con Health Check real
    server_thread = threading.Thread(
        target=server.run,
        name="Jessyca-WebUIBridge-Worker",
        daemon=True,
    )
    server_thread.start()

    # Comprobación de salud sobre 127.0.0.1
    health_url = f"http://127.0.0.1:{eff_port}/health"
    start_time = time.time()
    is_healthy = False

    while time.time() - start_time < 5.0:
        if _verify_health(health_url):
            is_healthy = True
            break
        time.sleep(0.1)

    if not is_healthy:
        logger.critical(f"[WebUI Bridge Server] Fallo en la verificación de salud inicial en {health_url}")
        print(f"[ERROR] El servidor Web Bridge no respondió en {health_url}", file=sys.stderr)
        server.should_exit = True
        server_thread.join(timeout=2.0)
        return 1

    # Mensajes formales requeridos de inicio
    print("[JESSYCA] Web Bridge iniciado")
    print(f"[JESSYCA] Web Bridge: http://localhost:{eff_port}")
    print(f"[JESSYCA] OpenAI API: http://localhost:{eff_port}/v1")
    print("[JESSYCA] Modelo disponible: jessyca")

    logger.info(f"[JESSYCA] Web Bridge iniciado exitosamente en http://{eff_host}:{eff_port}")

    try:
        while server_thread.is_alive():
            server_thread.join(timeout=0.5)
        return 0
    except KeyboardInterrupt:
        logger.info("[WebUI Bridge Server] Interrupción por teclado recibida; deteniendo servidor...")
        server.should_exit = True
        server_thread.join(timeout=2.0)
        logger.info("[WebUI Bridge Server] Servidor Uvicorn finalizado limpiamente.")
        return 0
    except Exception as exc:
        logger.critical(f"[WebUI Bridge Server] Error fatal en ejecución: {exc}", exc_info=True)
        server.should_exit = True
        return 1


if __name__ == "__main__":
    sys.exit(run_webui_server())
