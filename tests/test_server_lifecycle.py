"""Pruebas unitarias del ciclo de vida del servidor MCP (ServerLifecycleState)."""

from __future__ import annotations

from server import JessycaMCPServer, ServerLifecycleState


def test_server_lifecycle_transitions() -> None:
    server = JessycaMCPServer()

    # Estado inicial: STOPPED (antes de initialize/start)
    assert server.state == ServerLifecycleState.STOPPED

    # Inicializar -> queda en STOPPED (listo para iniciar)
    server.initialize()
    assert server.state == ServerLifecycleState.STOPPED

    # Iniciar -> RUNNING
    server.start()
    assert server.state == ServerLifecycleState.RUNNING

    # Apagado -> STOPPED
    server.shutdown()
    assert server.state == ServerLifecycleState.STOPPED
