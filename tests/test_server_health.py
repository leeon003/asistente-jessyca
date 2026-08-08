"""Pruebas unitarias de la herramienta e informe de Health Check del servidor MCP."""

from __future__ import annotations

from server import JessycaMCPServer, ServerLifecycleState


def test_server_health_status_report() -> None:
    server = JessycaMCPServer()
    server.initialize()

    health = server.get_health_status()

    assert isinstance(health, dict)
    assert health["server_status"] == ServerLifecycleState.READY.value
    assert health["server_name"] == server.settings.MCP_SERVER_NAME
    assert "version" in health
    assert "environment" in health
    assert "uptime_seconds" in health
    assert "registered_tools_count" in health
    assert "windows_info" in health
    assert health["windows_info"]["is_windows"] in (True, False)
