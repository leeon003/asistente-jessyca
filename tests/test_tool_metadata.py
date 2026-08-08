"""Pruebas unitarias de la estructura y declaración formal de metadatos (ToolSchema y BaseMCPTool)."""

from __future__ import annotations

from core.security import RiskLevel
from core.types import JSONDict
from tools.base_tool import BaseMCPTool


class DummyMetadataTool(BaseMCPTool):
    def __init__(self) -> None:
        super().__init__(
            name="dummy_meta",
            description="Herramienta de metadatos",
            version="2.1.0",
            author="Test Suite Author",
            category="network",
            capability="network",
            action="ping",
            aliases=["ping_host"],
            risk_level=RiskLevel.SAFE,
            required_permissions=["network.ping"],
            timeout_seconds=15.0,
            supports_rollback=True,
        )

    def _get_input_schema(self) -> JSONDict:
        return {"type": "object", "properties": {"host": {"type": "string"}}, "required": ["host"]}

    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        return {"ping": "pong"}


def test_tool_metadata_declaration() -> None:
    tool = DummyMetadataTool()
    meta = tool.get_metadata()

    assert meta.name == "dummy_meta"
    assert meta.description == "Herramienta de metadatos"
    assert meta.version == "2.1.0"
    assert meta.author == "Test Suite Author"
    assert meta.category == "network"
    assert meta.capability == "network"
    assert meta.action == "ping"
    assert meta.aliases == ["ping_host"]
    assert meta.risk_level == RiskLevel.SAFE
    assert meta.required_permissions == ["network.ping"]
    assert meta.timeout_seconds == 15.0
    assert meta.supports_rollback is True
    assert meta.input_schema["required"] == ["host"]
