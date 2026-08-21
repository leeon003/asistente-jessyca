"""Modelos inmutables para el Centro de Control y Observabilidad en Tiempo Real (control_center_models.py - Fase 24).

Define los estados formales del sistema, snapshots de telemetría y resultados de comandos de control seguro.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. CONTROL CENTER != TOOL EXECUTOR (La UI de observabilidad no tiene capacidad de ejecutar herramientas directamente).
2. UNTRUSTED DATA: Todo dato visualizado se sanitiza y se procesa como evidencia informativa.
3. Prevalencia de Parada de Emergencia: El estado STOPPED no puede ser ignorado ni sobreescrito arbitrariamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.security_architecture import SecurityLevel


class SystemState(StrEnum):
    """Estados formales del ciclo de vida y operación de JESSYCA 3.0."""

    IDLE = "IDLE"                                # Sistema en espera, listo para recibir solicitudes
    PLANNING = "PLANNING"                        # Sintetizando o validando plan de acción
    RUNNING = "RUNNING"                          # Ejecutando agente, inferencia o herramienta
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"# Bloqueado en espera de confirmación interactiva humana
    PAUSED = "PAUSED"                            # Ejecución pausada controladamente
    STOPPED = "STOPPED"                          # Parada de Emergencia activada
    COMPLETED = "COMPLETED"                      # Tarea o plan completado con éxito
    FAILED = "FAILED"                            # Tarea fallida o abortada por error/seguridad


@dataclass(frozen=True)
class ControlCenterSnapshot:
    """Instantánea inmutable del estado global y telemetría de JESSYCA."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    state: SystemState = SystemState.IDLE
    active_model: str | None = None
    active_agent: str | None = None
    current_task: str | None = None
    current_step: str | None = None
    risk_level: SecurityLevel = SecurityLevel.SAFE
    vram_mb: float = 0.0
    tokens_consumed: int = 0
    latency_ms: float = 0.0
    tools_executed: tuple[str, ...] = field(default_factory=tuple)
    security_events_count: int = 0
    latest_security_event: str | None = None
    emergency_stop_active: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serializa la instantánea a un diccionario seguro para interfaces o APIs."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "state": str(self.state),
            "active_model": self.active_model,
            "active_agent": self.active_agent,
            "current_task": self.current_task,
            "current_step": self.current_step,
            "risk_level": str(self.risk_level),
            "vram_mb": round(self.vram_mb, 2),
            "tokens_consumed": self.tokens_consumed,
            "latency_ms": round(self.latency_ms, 2),
            "tools_executed": list(self.tools_executed),
            "security_events_count": self.security_events_count,
            "latest_security_event": self.latest_security_event,
            "emergency_stop_active": self.emergency_stop_active,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class ControlCommandResult:
    """Resultado inmutable de una acción de control enviada al Centro de Control."""

    command: str
    success: bool
    message: str
    current_state: SystemState
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "success": self.success,
            "message": self.message,
            "current_state": str(self.current_state),
            "data": dict(self.data),
            "timestamp": self.timestamp.isoformat(),
        }
