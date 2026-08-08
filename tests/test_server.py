"""Pruebas unitarias completas de la creación y configuración del servidor MCP."""

from __future__ import annotations

from server import JessycaMCPServer, ServerLifecycleState, create_mcp_server, get_mcp_server


def test_server_creation_and_defaults() -> None:
    server = JessycaMCPServer()
    assert server.state == ServerLifecycleState.STARTING
    assert server.uptime_seconds >= 0.0
    assert server.settings.MCP_SERVER_NAME == "jessyca-windows-mcp"


def test_create_mcp_server_factory() -> None:
    server = create_mcp_server(server_name="test-server-instance")
    assert server.state == ServerLifecycleState.READY
    assert server.settings.MCP_SERVER_NAME == "test-server-instance"


def test_get_mcp_server_singleton() -> None:
    s1 = get_mcp_server()
    s2 = get_mcp_server()
    assert s1 is s2
