"""Pruebas unitarias completas del Capability Manager."""

from __future__ import annotations

from core.capability import CapabilityManager, ToolCapabilitySpec
from core.types import JSONDict
from tools.base_tool import BaseMCPTool
from tools.registry import ToolRegistry


class CopyFileTool(BaseMCPTool):
    def __init__(self) -> None:
        super().__init__(
            name="copy_file_tool",
            description="Copia un archivo de un origen a un destino",
            capability="Filesystem",
            action="copy",
            aliases=["copiar_archivo", "duplicar_archivo", "cp"],
        )

    def _get_input_schema(self) -> JSONDict:
        return {"type": "object", "properties": {}}

    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        return {"status": "copied"}


class NetworkPingTool(BaseMCPTool):
    def __init__(self) -> None:
        super().__init__(
            name="network_ping_tool",
            description="Envia un ping a un host remoto",
            capability="Network",
            action="ping",
            aliases=["probar_conexion", "ping_host"],
        )

    def _get_input_schema(self) -> JSONDict:
        return {"type": "object", "properties": {}}

    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        return {"status": "pong"}


def test_capability_resolution() -> None:
    cap_mgr = CapabilityManager()
    copy_tool = CopyFileTool()
    ping_tool = NetworkPingTool()

    spec1 = ToolCapabilitySpec(
        capability=copy_tool.capability,
        action=copy_tool.action,
        aliases=copy_tool.aliases,
    )
    spec2 = ToolCapabilitySpec(
        capability=ping_tool.capability,
        action=ping_tool.action,
        aliases=ping_tool.aliases,
    )

    cap_mgr.register_tool_capability(copy_tool, spec1)
    cap_mgr.register_tool_capability(ping_tool, spec2)

    # Resolución por Capacidad y Acción
    resolved_copy = cap_mgr.resolve("Filesystem", "copy")
    assert resolved_copy is copy_tool

    resolved_ping = cap_mgr.resolve("Network", "ping")
    assert resolved_ping is ping_tool

    # Resolución por Alias
    resolved_alias = cap_mgr.resolve_by_alias("copiar_archivo")
    assert resolved_alias is copy_tool

    resolved_alias_2 = cap_mgr.resolve_by_alias("probar_conexion")
    assert resolved_alias_2 is ping_tool


def test_discover_capabilities_from_registry() -> None:
    registry = ToolRegistry()
    copy_tool = CopyFileTool()
    ping_tool = NetworkPingTool()
    registry.register(copy_tool)
    registry.register(ping_tool)

    cap_mgr = CapabilityManager()
    count = cap_mgr.discover_capabilities(registry)
    assert count == 2

    caps = cap_mgr.get_available_capabilities()
    assert "Filesystem" in caps
    assert "copy" in caps["Filesystem"]
    assert "Network" in caps
    assert "ping" in caps["Network"]


def test_search_tools() -> None:
    cap_mgr = CapabilityManager()
    copy_tool = CopyFileTool()
    spec = ToolCapabilitySpec(
        capability=copy_tool.capability,
        action=copy_tool.action,
        aliases=copy_tool.aliases,
    )
    cap_mgr.register_tool_capability(copy_tool, spec)

    results = cap_mgr.search_tools("copiar")
    assert len(results) == 1
    assert results[0] is copy_tool
