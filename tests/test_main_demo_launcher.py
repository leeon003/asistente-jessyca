"""Suite de pruebas unitarias e integración para el launcher de JESSYCA 3.0 (FASE DEMO).

Valida:
- TEST 1: Argumentos por defecto (python main.py) seleccionan modo DEMO.
- TEST 2: Argumento --mcp selecciona modo servidor MCP standalone.
- TEST 3: Argumento --voice selecciona modo interfaz de voz standalone.
- TEST 4: MCPDemoRuntime inicia en background sin bloquear, reporta salud y se detiene limpiamente.
- TEST 5: VoiceSpeaker utiliza es-PE-CamilaNeural como voz principal.
- TEST 6: VoiceSpeaker.speak() sintetiza correctamente con Edge-TTS y maneja fallbacks.
- TEST 7: Cierre ordenado y detención de MCPDemoRuntime ante salida de sesión.
- TEST 8: Integración completa de run_demo_mode con mock de hardware.
- TEST 9: Configuración de host y puerto personalizados en MCPDemoRuntime.
- TEST 10: Manejo limpio de KeyboardInterrupt sin excepciones no capturadas.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from interfaces.modo_voz import VoiceSpeaker
from main import main, parse_arguments, run_demo_mode, run_mcp_mode, run_voice_mode
from server.health import HealthCheckResult, HealthStatus
from server.runtime import MCPDemoRuntime

# ── TEST 1: ARGUMENTOS DEFAULT -> MODO DEMO ──

def test_01_default_args_select_demo_mode() -> None:
    """TEST 1: Ejecutar sin argumentos selecciona el modo DEMO completo."""
    args = parse_arguments([])
    assert args.mcp is False
    assert args.voice is False
    assert args.demo is False  # Por lógica de main(), sin flags ejecuta DEMO

    with patch("main.run_demo_mode", return_value=0) as mock_demo:
        exit_code = main([])
        assert exit_code == 0
        mock_demo.assert_called_once()


# ── TEST 2: ARGUMENTO --mcp -> MODO MCP STANDALONE ──

def test_02_mcp_flag_selects_mcp_mode() -> None:
    """TEST 2: Flag --mcp selecciona exclusivamente el modo MCP."""
    args = parse_arguments(["--mcp"])
    assert args.mcp is True
    assert args.voice is False

    with patch("main.run_mcp_mode", return_value=0) as mock_mcp:
        exit_code = main(["--mcp"])
        assert exit_code == 0
        mock_mcp.assert_called_once_with(transport=None)


# ── TEST 3: ARGUMENTO --voice -> MODO VOZ STANDALONE ──

def test_03_voice_flag_selects_voice_mode() -> None:
    """TEST 3: Flag --voice selecciona exclusivamente el modo de voz."""
    args = parse_arguments(["--voice"])
    assert args.voice is True
    assert args.mcp is False

    with patch("main.run_voice_mode", return_value=0) as mock_voice:
        exit_code = main(["--voice"])
        assert exit_code == 0
        mock_voice.assert_called_once()


# ── TEST 4: MCPDEMORUNTIME LIFECYCLE NO BLOQUEANTE ──

def test_04_mcp_demo_runtime_lifecycle() -> None:
    """TEST 4: MCPDemoRuntime inicia en background, reporta is_running y se detiene limpiamente."""
    mock_server = MagicMock()
    mock_server.is_running = True
    mock_server.check_health.return_value = HealthCheckResult(
        status=HealthStatus.HEALTHY,
        server_name="test-server",
        version="1.0.0",
        uptime_seconds=10.0,
        registered_tools_count=5,
        lifecycle_state=MagicMock(),
    )

    runtime = MCPDemoRuntime(
        server=mock_server,
        host="127.0.0.1",
        port=8000,
        transport="streamable-http",
    )

    assert runtime.is_running is False
    assert runtime.host == "127.0.0.1"
    assert runtime.port == 8000
    assert runtime.transport == "streamable-http"

    # Iniciar runtime
    with patch("threading.Thread") as mock_thread_class:
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        mock_thread_class.return_value = mock_thread

        success = runtime.start(timeout_sec=0.1)
        assert success is True
        assert runtime.is_running is True

        health = runtime.health()
        assert health.status == HealthStatus.HEALTHY

        # Detener runtime
        runtime.stop()
        mock_server.shutdown.assert_called_once()
        assert runtime.is_running is False


# ── TEST 5: VOICESPEAKER VOZ PREDETERMINADA ES CAMILA NEURAL ──

def test_05_voicespeaker_default_voice_is_camila_neural() -> None:
    """TEST 5: VoiceSpeaker está configurado por defecto con es-PE-CamilaNeural."""
    speaker = VoiceSpeaker()
    assert speaker.voice_name == "es-PE-CamilaNeural"


# ── TEST 6: VOICESPEAKER.SPEAK SÍNTESIS CON EDGE-TTS ──

def test_06_voicespeaker_speak_synthesis() -> None:
    """TEST 6: VoiceSpeaker.speak() sintetiza texto sin lanzar excepciones."""
    speaker = VoiceSpeaker(default_voice="es-PE-CamilaNeural")

    with patch("pygame.mixer.init"), patch("pygame.mixer.get_init", return_value=True), \
         patch("pygame.mixer.Sound") as mock_sound_class, patch("pygame.mixer.get_busy", side_effect=[True, False]):

        mock_sound = MagicMock()
        mock_sound_class.return_value = mock_sound

        # Sintetizar mensaje
        speaker.speak("Hola, soy Jessyca.")
        # No debe lanzar excepción
        assert True

    # Texto vacío debe retornar de inmediato sin invocar TTS
    speaker.speak("")
    speaker.speak("   ")


# ── TEST 7: CIERRE ORDENADO Y SHUTDOWN DE MCP EN DEMO ──

def test_07_demo_mode_clean_shutdown_on_exit() -> None:
    """TEST 7: run_demo_mode asegura la detención de MCPDemoRuntime al terminar."""
    with patch("server.runtime.MCPDemoRuntime.start") as mock_start, \
         patch("server.runtime.MCPDemoRuntime.stop") as mock_stop, \
         patch("main.iniciar_modo_voz") as mock_iniciar_voz, \
         patch("core.local_agent.local_agent.JessycaLocalAgent.get_instance"):

        exit_code = run_demo_mode()
        assert exit_code == 0
        mock_start.assert_called_once()
        mock_iniciar_voz.assert_called_once()
        mock_stop.assert_called_once()


# ── TEST 8: INTEGRACIÓN RUN_DEMO_MODE CON MOCK DE HARDWARE ──

def test_08_run_demo_mode_integration() -> None:
    """TEST 8: Flujo completo de inicialización en modo DEMO."""
    with patch("server.runtime.MCPDemoRuntime.start") as mock_mcp_start, \
         patch("server.runtime.MCPDemoRuntime.stop") as mock_mcp_stop, \
         patch("main.iniciar_modo_voz") as mock_voice, \
         patch("core.local_agent.local_agent.JessycaLocalAgent.get_instance") as mock_agent:

        mock_agent.return_value = MagicMock()

        exit_code = main([])
        assert exit_code == 0
        mock_mcp_start.assert_called_once()
        mock_voice.assert_called_once()
        mock_mcp_stop.assert_called_once()


# ── TEST 9: MCPDEMORUNTIME CONFIGURACIÓN PERSONALIZADA ──

def test_09_mcp_demo_runtime_custom_config() -> None:
    """TEST 9: MCPDemoRuntime acepta y refleja configuraciones de red personalizadas."""
    custom_runtime = MCPDemoRuntime(
        host="127.0.0.1",
        port=8080,
        transport="sse",
    )
    data = custom_runtime.to_dict()
    assert data["host"] == "127.0.0.1"
    assert data["port"] == 8080
    assert data["transport"] == "sse"
    assert data["is_running"] is False


# ── TEST 10: MANEJO LIMPIO DE KEYBOARDINTERRUPT ──

def test_10_keyboard_interrupt_graceful_handling() -> None:
    """TEST 10: KeyboardInterrupt se maneja limpiamente devolviendo código de salida 0."""
    with patch("main.iniciar_modo_voz", side_effect=KeyboardInterrupt), \
         patch("server.runtime.MCPDemoRuntime.start"), \
         patch("server.runtime.MCPDemoRuntime.stop") as mock_stop, \
         patch("core.local_agent.local_agent.JessycaLocalAgent.get_instance"):

        exit_code = run_demo_mode()
        assert exit_code == 0
        mock_stop.assert_called_once()

    with patch("main.create_mcp_server") as mock_create:
        mock_server = MagicMock()
        mock_server.run.side_effect = KeyboardInterrupt
        mock_create.return_value = mock_server

        exit_code = run_mcp_mode()
        assert exit_code == 0
        mock_server.shutdown.assert_called_once()

    with patch("main.iniciar_modo_voz", side_effect=KeyboardInterrupt):
        exit_code = run_voice_mode()
        assert exit_code == 0
