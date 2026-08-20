"""Pruebas de integración del ToolRegistry con JessycaMCPServer (Subetapa 05.1)."""

from __future__ import annotations

from typing import Any

import pytest

from server.app import JessycaMCPServer
from server.errors import MCPToolNotFoundError
from tools.base import BaseTool
from tools.tool_registry import ToolRegistry


class DummyMockTool(BaseTool):
    """Herramienta de prueba sin ejecución real."""

    def __init__(self, name: str = "mock_tool") -> None:
        super().__init__(name=name, description="Herramienta de pruebas para integración MCP", category="testing")

    def _get_input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def _execute_internal(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ok", "result": "mock_result"}


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
