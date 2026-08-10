"""Pruebas del diagnóstico de salud HealthChecker (Subetapa 05.1)."""

from __future__ import annotations

from server.health import HealthChecker, HealthStatus
from server.lifecycle import ServerLifecycleManager
from tools.registry import ToolRegistry


def test_health_checker_when_stopped() -> None:
    lifecycle = ServerLifecycleManager()
    registry = ToolRegistry()
    checker = HealthChecker(lifecycle_manager=lifecycle, tool_registry=registry)

    result = checker.check_health()
    assert result.status == HealthStatus.DEGRADED
    assert result.lifecycle_state.value == "STOPPED"
    assert result.registered_tools_count == 0
    assert result.uptime_seconds == 0.0


def test_health_checker_when_running() -> None:
    lifecycle = ServerLifecycleManager()
    registry = ToolRegistry()
    checker = HealthChecker(lifecycle_manager=lifecycle, tool_registry=registry)

    lifecycle.start()
    result = checker.check_health()

    assert result.status == HealthStatus.HEALTHY
    assert result.lifecycle_state.value == "RUNNING"
    assert result.uptime_seconds >= 0.0

    dict_res = result.to_dict()
    assert dict_res["status"] == "HEALTHY"
    assert "timestamp" in dict_res
