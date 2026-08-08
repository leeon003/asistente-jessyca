"""Pruebas unitarias de los contratos base y registro de herramientas MCP."""

from __future__ import annotations

import asyncio

from core.types import JSONDict
from tools.base_tool import BaseMCPTool
from tools.registry import ToolRegistry


class DummyTool(BaseMCPTool):
    def __init__(self) -> None:
        super().__init__(name="dummy_tool", description="Herramienta ficticia para pruebas unitarias")

    def _get_input_schema(self) -> JSONDict:
        return {
            "type": "object",
            "properties": {"param": {"type": "string", "description": "Parámetro de prueba"}},
            "required": ["param"],
        }

    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        param = arguments.get("param", "")
        return {"output": f"processed_{param}"}


def test_tool_registry_registration_and_execution() -> None:
    async def _run() -> None:
        registry = ToolRegistry()
        tool = DummyTool()

        registry.register(tool)
        assert len(registry.list_tools()) == 1
        assert registry.get_tool("dummy_tool") is tool

        res = await registry.execute_tool("dummy_tool", {"param": "test_value"})
        assert res.is_success
        assert res.value == {"output": "processed_test_value"}

        # Invocación de herramienta inexistente
        fail_res = await registry.execute_tool("non_existent", {})
        assert not fail_res.is_success

    asyncio.run(_run())
