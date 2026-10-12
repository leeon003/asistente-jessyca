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
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.main")


def iniciar_modo_voz(*args: Any, **kwargs: Any) -> Any:
    """Wrapper diferido para iniciar_modo_voz que permite carga bajo demanda y compatibilidad de testing."""
    from interfaces.modo_voz import iniciar_modo_voz as _real_iniciar

    return _real_iniciar(*args, **kwargs)


def create_mcp_server(*args: Any, **kwargs: Any) -> Any:
    """Wrapper diferido para create_mcp_server que permite carga bajo demanda y compatibilidad de testing."""
    from server import create_mcp_server as _real_create

    return _real_create(*args, **kwargs)



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

    from config.manager import get_settings
    from core.local_agent.local_agent import JessycaLocalAgent
    from server.runtime import MCPDemoRuntime

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
    from config.manager import get_settings
    from server import JessycaMCPServer

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


def run_voice_mode(ptt: bool = False) -> int:
    """Ejecuta la interfaz interactiva de voz (continua o Pulsar para Hablar / PTT)."""
    try:
        logger.info(f"[VOICE STANDALONE] Iniciando interfaz de voz (modo PTT: {ptt})...")
        iniciar_modo_voz(show_header=True, ptt_mode=ptt)
        return 0
    except KeyboardInterrupt:
        logger.info("[VOICE STANDALONE] Modo voz detenido por el usuario.")
        return 0
    except Exception as e:
        logger.critical(f"[VOICE STANDALONE FATAL] Error en modo voz: {e}", exc_info=True)
        return 1


def run_text_mode() -> int:
    """Ejecuta exclusivamente la interfaz interactiva de texto (CLI)."""
    try:
        from interfaces.modo_texto import iniciar_modo_texto

        iniciar_modo_texto()
        return 0
    except KeyboardInterrupt:
        logger.info("[TEXT CLI] Modo texto detenido por el usuario.")
        return 0
    except Exception as e:
        logger.critical(f"[TEXT CLI FATAL] Error en modo texto: {e}", exc_info=True)
        return 1



def run_mobile_mode(host: str | None = None, port: int | None = None, force: bool = False) -> int:
    """Ejecuta exclusivamente el servidor Mobile API Bridge standalone."""
    try:
        from interfaces.mobile_api.server import run_mobile_server

        logger.info("[MOBILE STANDALONE] Iniciando servidor Mobile API Bridge...")
        if force:
            return run_mobile_server(host=host, port=port, force=True)
        return run_mobile_server(host=host, port=port)
    except KeyboardInterrupt:
        logger.info("[MOBILE STANDALONE] Servidor Mobile API detenido por el usuario.")
        return 0
    except Exception as e:
        logger.critical(f"[MOBILE STANDALONE FATAL] Error en servidor Mobile API: {e}", exc_info=True)
        return 1


def run_webui_mode(host: str | None = None, port: int | None = None, force: bool = False) -> int:
    """Ejecuta exclusivamente el servidor Web Bridge OpenAI-Compatible standalone."""
    try:
        from interfaces.webui_bridge.server import run_webui_server

        logger.info("[WEBUI STANDALONE] Iniciando servidor Web Bridge OpenAI-Compatible...")
        if force:
            return run_webui_server(host=host, port=port, force=True)
        return run_webui_server(host=host, port=port)
    except KeyboardInterrupt:
        logger.info("[WEBUI STANDALONE] Servidor Web Bridge detenido por el usuario.")
        return 0
    except Exception as e:
        logger.critical(f"[WEBUI STANDALONE FATAL] Error en servidor Web Bridge: {e}", exc_info=True)
        return 1


def run_doctor_command(args: argparse.Namespace) -> int:
    """Ejecuta diagnóstico del sistema, entorno y rutas segregadas."""
    from core.distribution.environment_diagnostics import EnvironmentDiagnosticsEngine
    from core.distribution.paths import ensure_directories, get_paths

    paths = ensure_directories(get_paths())
    report = EnvironmentDiagnosticsEngine.run_diagnostics()

    if getattr(args, "json", False):
        print(EnvironmentDiagnosticsEngine.export_report_json(report))
        return 0

    print("=" * 60)
    print("         JESSYCA 3.0 — DIAGNÓSTICO DEL ENTORNO (DOCTOR)")
    print("=" * 60)
    print(f"Sistema Operativo:     {report.windows_version} (Build {report.windows_build})")
    print(f"Runtime Python:        {report.python_version}")
    print(f"Acelerador / GPU:      {report.gpu_name}")
    if report.vram_total_mb > 0:
        print(f"VRAM GPU:              {report.vram_available_mb:.1f} MB / {report.vram_total_mb:.1f} MB")

    ollama_tag = "[OK]" if report.ollama_running else "[INFO - No activo]"
    models_str = ", ".join(report.ollama_models) if report.ollama_models else "Ninguno detectado"
    print(f"Proveedor Local LLM:   {ollama_tag} Ollama en 127.0.0.1:11434 (Modelos: {models_str})")
    print(f"Dispositivos Audio:    Micrófono={'[OK]' if report.microphone_available else '[NO]'} | Salida={'[OK]' if report.speakers_available else '[NO]'}")

    print("\n--- Rutas Segregadas del Sistema ---")
    print(f"Código Instalado:      {paths.code_dir} (Solo Lectura)")
    print(f"Configuración Usuario: {paths.config_dir}")
    print(f"Datos y Memoria:       {paths.data_dir}")
    print(f"Logs y Auditoría:      {paths.logs_dir}")
    print(f"Cachés Efímeras:       {paths.cache_dir}")
    print(f"Modelos Locales:       {paths.models_dir}")

    # Verificar permisos de escritura en carpetas de usuario
    try:
        test_file = paths.data_dir / ".doctor_write_check"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
    except Exception as e:
        print(f"[ERROR] Sin permisos de escritura en data_dir: {e}")
        return 1

    if report.missing_dependencies:
        print(f"\n[ALERTA] Dependencias faltantes: {', '.join(report.missing_dependencies)}")
        return 1

    print("\n[OK] Diagnóstico completado sin fallos críticos.")
    print("=" * 60)
    return 0


def run_status_command(args: argparse.Namespace) -> int:
    """Muestra el estado de instalación, rutas segregadas y servicio Core."""
    from core.distribution.paths import get_paths
    from core.distribution.service_client import DEFAULT_CORE_HOST, DEFAULT_CORE_PORT, CoreClient

    paths = get_paths()
    host = getattr(args, "host", None) or DEFAULT_CORE_HOST
    port = getattr(args, "port", None) or DEFAULT_CORE_PORT

    client = CoreClient(host=host, port=port)
    svc_status = client.check_service_status()

    print("=" * 60)
    print("              JESSYCA 3.0 — ESTADO DEL SISTEMA")
    print("=" * 60)
    print("Versión:               3.0.0 (Distribution Ready)")
    if svc_status.is_running:
        print(f"Servicio Core:         [EN EJECUCIÓN] en {svc_status.endpoint_url}")
    else:
        print("Servicio Core:         [DETENIDO] (Disponible en modo embebido / bajo demanda)")

    print("\nRutas Segregadas:")
    print(f" - Código:             {paths.code_dir}")
    print(f" - Configuración:      {paths.config_dir}")
    print(f" - Datos/Memoria:      {paths.data_dir}")
    print(f" - Logs:               {paths.logs_dir}")
    print(f" - Cachés:             {paths.cache_dir}")
    print(f" - Modelos:            {paths.models_dir}")
    print("=" * 60)
    return 0


def run_config_command(args: argparse.Namespace) -> int:
    """Inspecciona rutas de configuración y valores activos de forma sanitizada."""
    from core.distribution.environment_diagnostics import EnvironmentDiagnosticsEngine
    from core.distribution.paths import get_paths

    paths = get_paths()
    action = getattr(args, "action", "show") or "show"

    if action == "path":
        print(f"Directorio de configuración: {paths.config_dir}")
        print(f"Archivo de configuración:    {paths.config_dir / 'settings.json'}")
        return 0

    from config.manager import get_settings

    settings = get_settings()
    print("=" * 60)

    print("         JESSYCA 3.0 — CONFIGURACIÓN EFECTIVA")
    print("=" * 60)
    if hasattr(settings, "model_dump"):
        cfg_dict = settings.model_dump()
    elif hasattr(settings, "dict"):
        cfg_dict = settings.dict()
    else:
        cfg_dict = {k: getattr(settings, k) for k in dir(settings) if not k.startswith("_")}

    for key, val in sorted(cfg_dict.items()):
        val_str = str(val)
        sanitized_line = EnvironmentDiagnosticsEngine.sanitize_text(f"{key}={val_str}")
        print(f"{key}: {sanitized_line.split('=', 1)[1]}")

    print("=" * 60)
    return 0


def run_serve_command(args: argparse.Namespace) -> int:
    """Inicia el servicio Core compartido (OpenAI-Compatible Bridge)."""
    host = getattr(args, "host", None)
    port = getattr(args, "port", None)
    logger.info("[SERVE] Iniciando servicio Core compartido...")
    return run_webui_mode(host=host, port=port, force=True)


def run_agent_command(args: argparse.Namespace) -> int:
    """Ejecuta una interacción mediante el cliente Core (servicio o embebido con lock)."""
    from core.distribution.service_client import DEFAULT_CORE_HOST, DEFAULT_CORE_PORT, CoreClient

    raw_message = getattr(args, "message", [])
    prompt = " ".join(raw_message) if isinstance(raw_message, list) else str(raw_message)
    host = getattr(args, "host", None) or DEFAULT_CORE_HOST
    port = getattr(args, "port", None) or DEFAULT_CORE_PORT
    session_id = getattr(args, "session_id", "cli-session")

    client = CoreClient(host=host, port=port)
    try:
        response_text = client.execute(prompt=prompt, session_id=session_id)
        print(response_text)
        return 0
    except Exception as e:
        logger.error(f"[CLI ERROR] Falló la interacción con el Core: {e}")
        print(f"Error: {e}", file=sys.stderr)
        return 1


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parsea los argumentos de línea de comandos para seleccionar el modo de ejecución o subcomando."""
    parser = argparse.ArgumentParser(
        prog="jessyca",
        description="JESSYCA 3.0 — Asistente Local Windows Inteligente",
    )

    # Subcomandos para gestión, diagnóstico y cliente Core
    subparsers = parser.add_subparsers(dest="subcommand", help="Comandos de gestión y diagnóstico")

    # doctor / diag
    doc_parser = subparsers.add_parser("doctor", aliases=["diag"], help="Diagnóstico del entorno y dependencias")
    doc_parser.add_argument("--json", action="store_true", help="Exporta el reporte en JSON sanitizado")

    # status
    stat_parser = subparsers.add_parser("status", help="Muestra el estado de la instalación y del servicio Core")
    stat_parser.add_argument("--host", type=str, default=None, help="Host del servicio Core")
    stat_parser.add_argument("--port", type=int, default=None, help="Puerto del servicio Core")

    # config
    cfg_parser = subparsers.add_parser("config", help="Inspecciona la configuración activa")
    cfg_parser.add_argument("action", nargs="?", default="show", choices=["show", "path"], help="Acción a realizar")

    # serve
    srv_parser = subparsers.add_parser("serve", help="Inicia el servicio Core compartido en segundo plano")
    srv_parser.add_argument("--host", type=str, default=None, help="Host de escucha")
    srv_parser.add_argument("--port", type=int, default=None, help="Puerto de escucha")

    # run / chat
    run_parser = subparsers.add_parser("run", aliases=["chat"], help="Ejecuta una consulta a través del Core")
    run_parser.add_argument("message", nargs="+", help="Mensaje o instrucción para el asistente")
    run_parser.add_argument("--session-id", type=str, default="cli-session", help="ID de sesión conversacional")
    run_parser.add_argument("--host", type=str, default=None, help="Host del servicio Core")
    run_parser.add_argument("--port", type=int, default=None, help="Puerto del servicio Core")

    # Flags globales / modos de ejecución directos
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
        "--text", "-t",
        action="store_true",
        help="Inicia exclusivamente la interfaz interactiva de texto (CLI)",
    )
    group.add_argument(
        "--mobile",
        action="store_true",
        help="Inicia exclusivamente el servidor Mobile API Bridge",
    )
    group.add_argument(
        "--webui",
        action="store_true",
        help="Inicia exclusivamente el servidor Web Bridge OpenAI-Compatible",
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Fuerza el arranque del servicio ignorando flags de deshabilitación en la configuración (ej. MOBILE_API_ENABLED=False)",
    )
    parser.add_argument(
        "--ptt",
        action="store_true",
        help="Activa el modo Pulsar para Hablar (Push-To-Talk) explícito bajo demanda",
    )
    return parser.parse_args(args=argv if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada principal del script."""
    args = parse_arguments(argv)

    # 1. Subcomandos explícitos
    if args.subcommand in ("doctor", "diag"):
        return run_doctor_command(args)
    if args.subcommand == "status":
        return run_status_command(args)
    if args.subcommand == "config":
        return run_config_command(args)
    if args.subcommand == "serve":
        return run_serve_command(args)
    if args.subcommand in ("run", "chat"):
        return run_agent_command(args)

    # 2. Modos de servicio tradicionales por flags
    if getattr(args, "mcp", False):
        return run_mcp_mode(transport=args.transport)
    if getattr(args, "voice", False) or getattr(args, "ptt", False):
        return run_voice_mode(ptt=getattr(args, "ptt", False))
    if getattr(args, "text", False):
        return run_text_mode()
    if getattr(args, "mobile", False):
        if getattr(args, "force", False):
            return run_mobile_mode(host=args.host, port=args.port, force=True)
        return run_mobile_mode(host=args.host, port=args.port)
    if getattr(args, "webui", False):
        if getattr(args, "force", False):
            return run_webui_mode(host=args.host, port=args.port, force=True)
        return run_webui_mode(host=args.host, port=args.port)

    # 3. Modo DEMO predeterminado
    return run_demo_mode()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

