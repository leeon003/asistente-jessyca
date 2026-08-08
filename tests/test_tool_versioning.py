"""Pruebas unitarias de declaración de versión y metadatos de autoría en herramientas MCP."""

from __future__ import annotations

from core.types import JSONDict
from tools.base_tool import BaseMCPTool


class VersionedTool(BaseMCPTool):
    def __init__(self, version: str = "1.0.0") -> None:
        super().__init__(
            name="versioned_tool",
            description="Herramienta versionada",
            version=version,
            author="Community Contributor",
        )

    def _get_input_schema(self) -> JSONDict:
        return {"type": "object", "properties": {}}

    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        return {"v": self.version}


def test_tool_versioning_and_author() -> None:
    t1 = VersionedTool(version="1.2.0")
    t2 = VersionedTool(version="2.0.0-beta")

    assert t1.version == "1.2.0"
    assert t1.author == "Community Contributor"
    assert t2.version == "2.0.0-beta"

    meta = t1.get_metadata()
    assert meta.version == "1.2.0"
    assert meta.author == "Community Contributor"
