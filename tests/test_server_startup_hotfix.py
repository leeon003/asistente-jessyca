"""Suite de pruebas unitarias para certificar el arranque y transporte del servidor MCP (Hotfix FastMCP Runner).

Verifica:
TEST 1: JessycaMCPServer puede instanciarse correctamente con valores por defecto y personalizados.
TEST 2: initialize() funciona y coloca el estado en STOPPED (listo).
TEST 3: el servidor puede iniciar correctamente mediante start() pasando a RUNNING.
TEST 4: run() ejecuta el transporte pasando a RUNNING y transiciona limpiamente a STOPPED al terminar.
TEST 5: un error en el transporte de FastMCP lleva el lifecycle a FAILED y propaga la excepción.
TEST 6: shutdown() devuelve el estado a STOPPED.
TEST 7: main.py puede invocar server.run() sin generar AttributeError.
TEST 8: El transporte configurado (stdio, sse, http) se respeta e invoca con los argumentos adecuados.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from config.settings import AppSettings
from server import (
    JessycaMCPServer,
    LifecycleState,
    ServerLifecycleState,
)


# ── TEST 1: INSTANCIACIÓN ──
def test_01_server_instantiation() -> None:
    """TEST 1: JessycaMCPServer puede instanciarse."""
    server = JessycaMCPServer()
    assert server is not None
    assert server.state == ServerLifecycleState.STOPPED
    assert server.is_running is False
    assert hasattr(server, "run")
    assert callable(server.run)


# ── TEST 2: INITIALIZE ──
def test_02_server_initialize() -> None:
    """TEST 2: initialize() funciona y deja el servidor en STOPPED listo para arrancar."""
    server = JessycaMCPServer()
    server.initialize()
    assert server.state == ServerLifecycleState.STOPPED
    assert server.is_running is False


# ── TEST 3: START ──
def test_03_server_start() -> None:
    """TEST 3: el servidor puede iniciar correctamente pasando a RUNNING."""
    server = JessycaMCPServer()
    server.start()
    assert server.state == ServerLifecycleState.RUNNING
    assert server.is_running is True
    assert server.lifecycle_manager.uptime_seconds >= 0.0
    server.shutdown()
    final_state: LifecycleState = server.state
    assert final_state == ServerLifecycleState.STOPPED


# ── TEST 4: RUN CON ESTADO RUNNING Y CIERRE LIMPIO ──
def test_04_server_run_lifecycle_flow() -> None:
    """TEST 4: run() transiciona a RUNNING y ejecuta el shutdown al finalizar."""
    mock_fastmcp = MagicMock()
    server = JessycaMCPServer()
    server._fastmcp_instance = mock_fastmcp

    states_during_run = []

    def fake_fastmcp_run(*args: object, **kwargs: object) -> None:
        states_during_run.append(server.state)

    mock_fastmcp.run.side_effect = fake_fastmcp_run

    server.run()

    # Durante la ejecución de FastMCP el estado debió ser RUNNING
    assert states_during_run == [ServerLifecycleState.RUNNING]
    # Al terminar la ejecución el estado vuelve a STOPPED
    final_state: LifecycleState = server.state
    assert final_state == ServerLifecycleState.STOPPED
    assert mock_fastmcp.run.called


# ── TEST 5: ERROR DE FASTMCP LLEVA A FAILED ──
def test_05_fastmcp_error_transitions_to_failed() -> None:
    """TEST 5: un error de FastMCP lleva el lifecycle a FAILED y registra el error."""
    mock_fastmcp = MagicMock()
    mock_fastmcp.run.side_effect = RuntimeError("Error simulado de enlace de socket o transporte FastMCP")

    server = JessycaMCPServer()
    server._fastmcp_instance = mock_fastmcp

    with pytest.raises(RuntimeError, match="Error simulado"):
        server.run()

    assert server.state == LifecycleState.FAILED
    assert server.is_running is False


# ── TEST 6: SHUTDOWN DEVUELVE A STOPPED ──
def test_06_shutdown_returns_to_stopped() -> None:
    """TEST 6: shutdown() devuelve correctamente el estado a STOPPED."""
    server = JessycaMCPServer()
    server.start()
    assert server.state == ServerLifecycleState.RUNNING
    server.shutdown()
    final_state: LifecycleState = server.state
    assert final_state == ServerLifecycleState.STOPPED
    assert server.is_running is False


# ── TEST 7: MAIN ENTRY POINT Y NO ATTRIBUTE ERROR ──
def test_07_main_entry_point_executes_run_without_attribute_error() -> None:
    """TEST 7: main.py en modo MCP invoca run() en el servidor MCP sin AttributeError."""
    mock_server = MagicMock(spec=JessycaMCPServer)
    mock_server.run.return_value = None

    with patch("main.create_mcp_server", return_value=mock_server):
        from main import main
        main(["--mcp"])

    assert mock_server.run.called


# ── TEST 8: TRANSPORTE CONFIGURADO SE RESPETA ──
@pytest.mark.parametrize(
    ("config_transport", "expected_call_transport"),
    [
        ("stdio", "stdio"),
        ("sse", "sse"),
        ("http", "http"),
        ("streamable-http", "streamable-http"),
    ],
)
def test_08_configured_transport_respected(config_transport: str, expected_call_transport: str) -> None:
    """TEST 8: El transporte configurado se respeta e invoca con los argumentos adecuados."""
    settings = AppSettings()
    settings.MCP_TRANSPORT = config_transport
    settings.MCP_SERVER_HOST = "127.0.0.1"
    settings.MCP_SERVER_PORT = 9999

    mock_fastmcp = MagicMock()
    server = JessycaMCPServer(settings=settings)
    server._fastmcp_instance = mock_fastmcp

    server.run()

    if config_transport in ("sse", "http", "streamable-http"):
        mock_fastmcp.run.assert_called_once_with(
            transport=expected_call_transport,
            host="127.0.0.1",
            port=9999,
            show_banner=None,
        )
    else:
        mock_fastmcp.run.assert_called_once_with(
            transport="stdio",
            show_banner=None,
        )
