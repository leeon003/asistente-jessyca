"""Pruebas de integración del ToolRegistry con JessycaMCPServer (Subetapa 05.1)."""

from __future__ import annotations

import pytest

from server.app import JessycaMCPServer
from server.errors import MCPToolNotFoundError
from tools.base import BaseTool, ToolMetadata
from tools.registry import ToolRegistry


class DummyMockTool(BaseTool):
    """Herramienta de prueba sin ejecución real."""

    def __init__(self, name: str = "mock_tool") -> None:
        metadata = ToolMetadata(
            name=name,
            description="Herramienta de pruebas para integración MCP",
            category="testing",
        )
        super().__init__(metadata=metadata)

    def execute(self, **kwargs: object) -> object:
        return "mock_result"


def test_tool_registry_empty_server_query() -> None:
    registry = ToolRegistry()
    server = JessycaMCPServer(tool_registry=registry)

    assert len(server.list_tools()) == 0


def test_tool_registry_server_tool_discovery() -> None:
    registry = ToolRegistry()
    tool = DummyMockTool("test_mock")
    registry.register(tool)

    server = JessycaMCPServer(tool_registry=registry)
    tools = server.list_tools()

    assert len(tools) == 1
    assert tools[0]["name"] == "test_mock"

    info = server.get_tool_info("test_mock")
    assert info["name"] == "test_mock"
    assert info["category"] == "testing"


def test_tool_registry_unknown_tool_query() -> None:
    registry = ToolRegistry()
    server = JessycaMCPServer(tool_registry=registry)

    with pytest.raises(MCPToolNotFoundError):
        server.get_tool_info("non_existent_tool")
