"""Módulo de comprobación de salud (Health Check) para el servidor MCP (Subetapa 05.1).

Proporciona diagnósticos estructurados y tipados sobre el estado operativo del servidor,
su versión, tiempo de actividad y componentes sin ejecutar herramientas ni comandos del sistema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from server.lifecycle import LifecycleState, ServerLifecycleManager
from tools.tool_registry import ToolRegistry, get_tool_registry


class HealthStatus(StrEnum):
    """Estados del diagnóstico de salud del servidor MCP."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


@dataclass(frozen=True)
class HealthCheckResult:
    """Resultado estructurado del diagnóstico de salud del servidor MCP."""

    status: HealthStatus
    server_name: str
    version: str
    uptime_seconds: float
    registered_tools_count: int
    lifecycle_state: LifecycleState
    components: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, str | float | int | dict[str, str]]:
        """Convierte el resultado a un diccionario explícito serializable."""
        return {
            "status": self.status.value,
            "server_name": self.server_name,
            "version": self.version,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "registered_tools_count": self.registered_tools_count,
            "lifecycle_state": self.lifecycle_state.value,
            "components": self.components,
            "timestamp": self.timestamp.isoformat(),
        }


class HealthChecker:
    """Realiza la evaluación de salud del servidor MCP."""

    def __init__(
        self,
        server_name: str = "Jessyca Windows MCP",
        version: str = "0.5.1",
        lifecycle_manager: ServerLifecycleManager | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.server_name = server_name
        self.version = version
        self.lifecycle_manager = lifecycle_manager or ServerLifecycleManager()
        self.tool_registry = tool_registry or get_tool_registry()

    def check_health(self) -> HealthCheckResult:
        """Genera un reporte completo de salud sin invocar herramientas."""
        state = self.lifecycle_manager.state
        uptime = self.lifecycle_manager.uptime_seconds
        tools_count = len(self.tool_registry)

        if state == LifecycleState.RUNNING:
            status = HealthStatus.HEALTHY
        elif state in (LifecycleState.INITIALIZING, LifecycleState.STOPPING, LifecycleState.STOPPED):
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.UNHEALTHY

        components = {
            "lifecycle": state.value,
            "tool_registry": "READY",
            "security_pipeline": "CONFIGURED",
        }

        return HealthCheckResult(
            status=status,
            server_name=self.server_name,
            version=self.version,
            uptime_seconds=uptime,
            registered_tools_count=tools_count,
            lifecycle_state=state,
            components=components,
            timestamp=datetime.now(UTC),
        )
