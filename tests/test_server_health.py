"""Pruebas unitarias de la herramienta e informe de Health Check del servidor MCP."""

from __future__ import annotations

from server import JessycaMCPServer, ServerLifecycleState
from server.health import HealthStatus


def test_server_health_status_report() -> None:
    server = JessycaMCPServer()
    server.initialize()

    health = server.check_health()

    # Verificar que es un HealthCheckResult con los campos esperados
    assert health.server_name == server.server_name
    assert health.version == server.version
    assert health.uptime_seconds >= 0.0
    assert health.registered_tools_count >= 0
    assert health.lifecycle_state == ServerLifecycleState.STOPPED
    # Antes de start(), el estado es DEGRADED (no RUNNING)
    assert health.status == HealthStatus.DEGRADED

    # Arrancar el servidor y verificar que el health es HEALTHY
    server.start()
    health_running = server.check_health()
    assert health_running.status == HealthStatus.HEALTHY
    assert health_running.lifecycle_state == ServerLifecycleState.RUNNING

    server.shutdown()
