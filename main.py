"""main.py
Punto de entrada principal de JESSYCA 3.0 (DEMO & Local Assistant).

Permite ejecutar:
  1. Modo DEMO completo (predeterminado: python main.py)
     - Servidor FastMCP en segundo plano (streamable-http en 127.0.0.1:8000)
     - Security Architecture activa (RiskEngine, PermissionManager, SecurityPolicy)
     - Skills y Registries cargados
     - Local Agent activo
     - Voz interactiva con auto-detección de micrófono (G435 / C270)
     - Síntesis de voz Camila Neural (es-PE-CamilaNeural)
     - Sesión conversacional continua
  2. Modo MCP explícito (python main.py --mcp)
     - Inicia exclusivamente el servidor MCP (STDIO / configurado)
  3. Modo Voz explícito (python main.py --voice)
     - Inicia exclusivamente la interfaz de voz interactiva
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from config.manager import get_settings
from core.local_agent.local_agent import JessycaLocalAgent
from core.logger import get_logger
from interfaces.modo_voz import iniciar_modo_voz
from server import JessycaMCPServer, create_mcp_server
from server.runtime import MCPDemoRuntime

logger = get_logger("jessyca.main")

BANNER_DEMO = r"""
╔══════════════════════════════════════════════════════╗
║                  J E S S Y C A  3.0                 ║
║              ASISTENTE LOCAL WINDOWS                ║
╠══════════════════════════════════════════════════════╣
║ ✓ Security                                           ║
║ ✓ Skills                                             ║
║ ✓ Local Agent                                        ║
║ ✓ MCP Server                                         ║
║ ✓ Voice                                              ║
║ ✓ STT / VAD                                          ║
║ ✓ CamilaNeural                                       ║
╚══════════════════════════════════════════════════════╝
"""


def run_demo_mode() -> int:
    """Ejecuta la experiencia completa DEMO de JESSYCA 3.0."""
    logger.info("[DEMO] JESSYCA 3.0 iniciando...")

    settings = get_settings()
    mcp_runtime: MCPDemoRuntime | None = None

    try:
        # 1. Logging y Security
        logger.info("[DEMO] Security inicializada")

        # 2. Inicialización del Agente Local y Skills
        JessycaLocalAgent.get_instance()
        logger.info("[DEMO] Skills cargadas")
        logger.info("[DEMO] Local Agent inicializado")

        # 3. Inicialización del Servidor MCP en segundo plano
        mcp_host = getattr(settings, "MCP_SERVER_HOST", "127.0.0.1")
        mcp_port = getattr(settings, "MCP_SERVER_PORT", 8000)
        mcp_transport = getattr(settings, "MCP_DEMO_TRANSPORT", "streamable-http")

        mcp_runtime = MCPDemoRuntime(
            host=mcp_host,
            port=mcp_port,
            transport=mcp_transport,
        )
        mcp_runtime.start()
        logger.info(f"[DEMO] MCP iniciado en {mcp_host}:{mcp_port}")

        # 4. Inicio de la sesión conversacional de voz continua
        mcp_info_str = f"{mcp_host}:{mcp_port} ({mcp_transport})"
        iniciar_modo_voz(
            show_header=False,
            custom_banner=BANNER_DEMO,
            mcp_info=mcp_info_str,
        )
        return 0

    except KeyboardInterrupt:
        logger.info("[DEMO] Sesión detenida por el usuario.")
        return 0
    except Exception as e:
        logger.critical(f"[DEMO FATAL] Error en ejecución de JESSYCA DEMO: {e}", exc_info=True)
        return 1
    finally:
        if mcp_runtime is not None:
            try:
                mcp_runtime.stop()
            except Exception as e:
                logger.warning(f"[DEMO] Error al detener runtime MCP: {e}")
        logger.info("[DEMO] JESSYCA 3.0 finalizada.")


def run_mcp_mode(transport: str | None = None) -> int:
    """Ejecuta exclusivamente el servidor FastMCP standalone."""
    server: JessycaMCPServer | None = None
    settings = get_settings()
    eff_transport = transport or getattr(settings, "MCP_EXTERNAL_TRANSPORT", "stdio")

    try:
        logger.info(f"[MCP STANDALONE] Iniciando servidor MCP standalone (transporte: {eff_transport})...")
        server = create_mcp_server()
        server.run(transport=eff_transport)
        return 0
    except KeyboardInterrupt:
        logger.info("[MCP STANDALONE] Servidor detenido por el usuario.")
        if server is not None:
            server.shutdown()
        return 0
    except Exception as e:
        logger.critical(f"[MCP STANDALONE FATAL] Error en servidor MCP: {e}", exc_info=True)
        if server is not None:
            server.shutdown()
        return 1


def run_voice_mode() -> int:
    """Ejecuta exclusivamente la interfaz interactiva de voz."""
    try:
        logger.info("[VOICE STANDALONE] Iniciando interfaz interactiva de voz...")
        iniciar_modo_voz(show_header=True)
        return 0
    except KeyboardInterrupt:
        logger.info("[VOICE STANDALONE] Modo voz detenido por el usuario.")
        return 0
    except Exception as e:
        logger.critical(f"[VOICE STANDALONE FATAL] Error en modo voz: {e}", exc_info=True)
        return 1


def run_mobile_mode(host: str | None = None, port: int | None = None) -> int:
    """Ejecuta exclusivamente el servidor Mobile API Bridge standalone."""
    try:
        from interfaces.mobile_api.server import run_mobile_server

        logger.info("[MOBILE STANDALONE] Iniciando servidor Mobile API Bridge...")
        return run_mobile_server(host=host, port=port)
    except KeyboardInterrupt:
        logger.info("[MOBILE STANDALONE] Servidor Mobile API detenido por el usuario.")
        return 0
    except Exception as e:
        logger.critical(f"[MOBILE STANDALONE FATAL] Error en servidor Mobile API: {e}", exc_info=True)
        return 1


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parsea los argumentos de línea de comandos para seleccionar el modo de ejecución."""
    parser = argparse.ArgumentParser(
        prog="jessyca",
        description="JESSYCA 3.0 — Asistente Local Windows Inteligente",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--demo",
        action="store_true",
        help="Inicia el asistente completo en modo DEMO interactivo con MCP y Voz (predeterminado)",
    )
    group.add_argument(
        "--mcp",
        action="store_true",
        help="Inicia exclusivamente el servidor MCP standalone",
    )
    group.add_argument(
        "--voice",
        action="store_true",
        help="Inicia exclusivamente la interfaz interactiva de voz",
    )
    group.add_argument(
        "--mobile",
        action="store_true",
        help="Inicia exclusivamente el servidor Mobile API Bridge",
    )
    parser.add_argument(
        "--transport",
        type=str,
        default=None,
        help="Transporte para el servidor MCP (ej. stdio, sse, streamable-http)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host de escucha personalizado para servidores de red",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Puerto TCP de escucha personalizado para servidores de red",
    )
    return parser.parse_args(args=argv if argv is not None else [])


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada principal del script."""
    args = parse_arguments(argv)

    if args.mcp:
        return run_mcp_mode(transport=args.transport)
    if args.voice:
        return run_voice_mode()
    if args.mobile:
        return run_mobile_mode(host=args.host, port=args.port)

    # Modo DEMO predeterminado
    return run_demo_mode()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
