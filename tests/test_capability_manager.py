"""Pruebas unitarias completas del CapabilityManager y consultas avanzadas."""

from __future__ import annotations

from core.capability import CapabilityManager
from core.types import JSONDict
from tools.base_tool import BaseMCPTool


class MockFileSystemTool(BaseMCPTool):
    def __init__(self) -> None:
        super().__init__(
            name="mock_read_file",
            description="Lee un archivo mock",
            category="filesystem",
            capability="filesystem",
            action="read",
            aliases=["leer_archivo", "abrir_fichero"],
        )

    def _get_input_schema(self) -> JSONDict:
        return {"type": "object", "properties": {}}

    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        return {"content": "mock_data"}


def test_capability_manager_crud_and_queries() -> None:
    cap_mgr = CapabilityManager()
    tool = MockFileSystemTool()

    # Register
    assert cap_mgr.register_capability(tool) is True

    # Find by capability and action
    found = cap_mgr.get_capability("filesystem", "read")
    assert found is not None
    assert found.name == "mock_read_file"

    # Find by capability domain
    cap_tools = cap_mgr.find_tools_by_capability("filesystem")
    assert len(cap_tools) == 1
    assert cap_tools[0].name == "mock_read_file"

    # Find by action
    act_tools = cap_mgr.find_tools_by_action("read")
    assert len(act_tools) == 1

    # Find by category
    cat_tools = cap_mgr.find_tools_by_category("filesystem")
    assert len(cat_tools) == 1

    # Find by alias
    alias_tool1 = cap_mgr.find_tools_by_alias("leer_archivo")
    alias_tool2 = cap_mgr.find_tools_by_alias("abrir_fichero")
    assert alias_tool1 is not None
    assert alias_tool2 is not None
    assert alias_tool1.name == "mock_read_file"

    # Unregister capability
    assert cap_mgr.unregister_capability("filesystem", "read") is True
    assert cap_mgr.get_capability("filesystem", "read") is None
