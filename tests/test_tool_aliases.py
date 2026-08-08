"""Pruebas unitarias de resolución de herramientas por alias alternativos."""

from __future__ import annotations

from core.capability import CapabilityManager
from core.types import JSONDict
from tools.base_tool import BaseMCPTool


class AliasTestTool(BaseMCPTool):
    def __init__(self) -> None:
        super().__init__(
            name="process_list",
            description="Lista procesos activos",
            category="processes",
            capability="processes",
            action="list",
            aliases=["listar_procesos", "ver_procesos", "ps"],
        )

    def _get_input_schema(self) -> JSONDict:
        return {"type": "object", "properties": {}}

    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        return {"processes": []}


def test_tool_alias_resolution() -> None:
    cap_mgr = CapabilityManager()
    tool = AliasTestTool()
    cap_mgr.register_capability(tool)

    # Resoluciones por alias
    for alias in ["listar_procesos", "ver_procesos", "ps", "process_list"]:
        resolved = cap_mgr.find_tools_by_alias(alias)
        assert resolved is not None
        assert resolved.name == "process_list"

    # Alias inexistente
    assert cap_mgr.find_tools_by_alias("alias_inexistente") is None
