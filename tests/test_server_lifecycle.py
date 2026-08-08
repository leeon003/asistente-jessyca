"""Pruebas unitarias del ciclo de vida del servidor MCP (ServerLifecycleState)."""

from __future__ import annotations

from server import JessycaMCPServer, ServerLifecycleState


def test_server_lifecycle_transitions() -> None:
    server = JessycaMCPServer()

    # Estado inicial: STARTING
    assert server.state == ServerLifecycleState.STARTING

    # Inicializar -> Transiciona a READY
    initialized = server.initialize()
    assert initialized is True
    assert server.state == ServerLifecycleState.READY

    # Apagado -> Transiciona a STOPPED
    server.shutdown()
    assert server.state == ServerLifecycleState.STOPPED
