"""Pruebas del servidor principal JessycaMCPServer (Subetapa 05.1)."""

from __future__ import annotations

import pytest

from server.app import JessycaMCPServer, get_mcp_server
from server.errors import MCPServerNotInitializedError, MCPToolNotFoundError, MCPValidationError
from server.lifecycle import LifecycleState


def test_server_metadata() -> None:
    server = JessycaMCPServer()
    assert server.server_name in ("Jessyca Windows MCP", "jessyca-windows-mcp")
    assert server.version == "0.5.1"
    assert server.host == "127.0.0.1"
    assert server.port == 8000
    assert server.transport == "stdio"


def test_server_initialization_and_start() -> None:
    server = JessycaMCPServer()
    assert server.state == LifecycleState.STOPPED

    server.initialize()
    assert server.state == LifecycleState.STOPPED

    server.start()
    assert server.state == LifecycleState.RUNNING
    assert server.is_running is True

    server.shutdown()
    assert server.state == LifecycleState.STOPPED
    assert server.is_running is False


def test_server_request_handling_not_running() -> None:
    server = JessycaMCPServer()
    with pytest.raises(MCPServerNotInitializedError):
        server.handle_request({"tool_name": "filesystem", "operation": "read"})


def test_server_invalid_request_payload() -> None:
    server = JessycaMCPServer()
    server.start()

    with pytest.raises(MCPValidationError):
        server.handle_request("not_a_dict")  # type: ignore[arg-type]

    with pytest.raises(MCPValidationError):
        server.handle_request({"parameters": {}})  # missing tool_name

    server.shutdown()


def test_server_unknown_tool_request() -> None:
    server = JessycaMCPServer()
    server.start()

    with pytest.raises(MCPToolNotFoundError):
        server.handle_request({"tool_name": "non_existent_tool_xyz"})

    server.shutdown()


def test_global_get_mcp_server_singleton() -> None:
    s1 = get_mcp_server()
    s2 = get_mcp_server()
    assert s1 is s2
