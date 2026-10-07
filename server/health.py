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


import threading
import time

class HealthChecker:
    """Realiza la evaluación de salud del servidor MCP con soporte de caché TTL."""

    def __init__(
        self,
        server_name: str = "Jessyca Windows MCP",
        version: str = "0.5.1",
        lifecycle_manager: ServerLifecycleManager | None = None,
        tool_registry: ToolRegistry | None = None,
        cache_ttl_seconds: float = 2.0,
    ) -> None:
        self.server_name = server_name
        self.version = version
        self.lifecycle_manager = lifecycle_manager or ServerLifecycleManager()
        self.tool_registry = tool_registry or get_tool_registry()
        self.cache_ttl_seconds = float(cache_ttl_seconds)
        self._cached_result: HealthCheckResult | None = None
        self._cached_monotonic: float = 0.0
        self._cached_state: LifecycleState | None = None
        self._lock = threading.Lock()

    def check_health(self, force: bool = False) -> HealthCheckResult:
        """Genera un reporte completo de salud sin invocar herramientas, con caché TTL."""
        now_monotonic = time.monotonic()
        with self._lock:
            state = self.lifecycle_manager.state
            if not force and self._cached_result is not None and self._cached_state == state:
                if (now_monotonic - self._cached_monotonic) < self.cache_ttl_seconds:
                    return self._cached_result
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

            result = HealthCheckResult(
                status=status,
                server_name=self.server_name,
                version=self.version,
                uptime_seconds=uptime,
                registered_tools_count=tools_count,
                lifecycle_state=state,
                components=components,
                timestamp=datetime.now(UTC),
            )
            self._cached_result = result
            self._cached_monotonic = now_monotonic
            self._cached_state = state
            return result

