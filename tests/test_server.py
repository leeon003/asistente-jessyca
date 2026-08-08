"""Pruebas de integración del servidor FastMCP y del motor de autodescubrimiento."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastmcp import FastMCP

from server import create_mcp_server
from tools.discovery import ToolDiscoveryEngine
from tools.system_health import SystemHealthTool


def test_create_mcp_server_instance() -> None:
    mcp_server = create_mcp_server(server_name="test-jessyca-server")
    assert isinstance(mcp_server, FastMCP)
    assert mcp_server.name == "test-jessyca-server"


def test_auto_discovery_engine_discovers_health_tool(temp_dir: Path) -> None:
    mcp_server = FastMCP("test-discovery")
    engine = ToolDiscoveryEngine()

    count = engine.discover_and_register(mcp_server)
    # Debe descubrir al menos la herramienta nativa system_health
    assert count >= 1


def test_system_health_tool_execution() -> None:
    async def _run() -> None:
        tool = SystemHealthTool()
        assert tool.name == "system_health"

        res = await tool.execute({"include_metrics": True})
        assert res.is_success
        data = res.value
        assert data["status"] == "healthy"
        assert "windows_platform" in data
        assert "system_metrics" in data

    asyncio.run(_run())
