"""Pruebas unitarias completas del motor de autodescubrimiento independiente (ToolDiscoveryEngine)."""

from __future__ import annotations

from core.capability import CapabilityManager
from tools.discovery import ToolDiscoveryEngine
from tools.tool_registry import ToolRegistry


def test_standalone_tool_discovery() -> None:
    registry = ToolRegistry()
    cap_mgr = CapabilityManager()
    engine = ToolDiscoveryEngine(registry=registry, capability_manager=cap_mgr)

    tools = engine.discover_tools()
    assert isinstance(tools, list)
    assert len(tools) >= 1

    # Comprobar que las herramientas estén registradas tanto en Registry como en CapabilityManager
    for tool in tools:
        assert registry.get_tool(tool.name) is not None
        assert cap_mgr.find_tools_by_alias(tool.name) is not None
