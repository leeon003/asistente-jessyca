"""Punto de entrada principal del servidor Jessyca Windows MCP.

Inicializa la configuración, activa el sistema de logging, valida la compatibilidad
con Windows 10/11 y ejecuta el servidor FastMCP a través del canal de comunicación (STDIO / SSE).
"""

from __future__ import annotations

import sys

from core.logger import get_logger
from server import create_mcp_server

logger = get_logger("jessyca.main")


def main() -> None:
    """Función de entrada principal."""
    try:
        mcp_server = create_mcp_server()

        # Ejecución del servidor FastMCP (por defecto utiliza STDIO para integración con clientes MCP)
        logger.info("Iniciando transporte de servidor FastMCP...")
        mcp_server.run()
    except KeyboardInterrupt:
        logger.info("Servidor detenido por solicitud del usuario.")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Error fatal al iniciar el servidor Jessyca Windows MCP: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
