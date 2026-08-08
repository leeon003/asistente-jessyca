"""Pruebas unitarias de la integración entre ToolRegistry y el servidor FastMCP."""

from __future__ import annotations

import asyncio

from core.types import JSONDict
from server import JessycaMCPServer
from tools.base_tool import BaseMCPTool
from tools.registry import ToolRegistry


class CustomMockTool(BaseMCPTool):
    def __init__(self) -> None:
        super().__init__(
            name="mock_test_tool",
            description="Herramienta de prueba mock",
            capability="TestDomain",
            action="test_action",
        )

    def _get_input_schema(self) -> JSONDict:
        return {"type": "object", "properties": {}}

    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        return {"result": "success_from_mock"}


def test_registry_integration_with_fastmcp() -> None:
    registry = ToolRegistry()
    mock_tool = CustomMockTool()
    registry.register(mock_tool)

    server = JessycaMCPServer(registry=registry)
    server.initialize()

    # Verificar que la herramienta esté en el catálogo de ToolRegistry
    tool = server.registry.get_tool("mock_test_tool")
    assert tool is not None
    assert tool.name == "mock_test_tool"

    # Verificar que la herramienta ejecute correctamente a través de la integración
    exec_res = asyncio.run(server.registry.execute_tool("mock_test_tool", {}))
    assert exec_res.is_success is True
    assert exec_res.value == {"result": "success_from_mock"}
