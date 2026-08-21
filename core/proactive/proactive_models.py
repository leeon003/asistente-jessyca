"""Modelos de datos inmutables para el Asistente Proactivo Seguro (proactive_models.py - Fase 27).

Define los tipos de eventos proactivos, decisiones de política, acciones y resultados de ejecución.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. PROACTIVE != UNRESTRICTED_ACTION (JESSYCA jamás ejecuta acciones peligrosas sin confirmación).
2. EVENT OUTPUT = UNTRUSTED DATA (Todo evento es evaluado a través de RiskEngine y PermissionManager).
3. Prevalencia de Parada de Emergencia (EmergencyStopManager detiene inmediatamente cualquier acción proactiva).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.security_architecture import SecurityLevel


class ProactiveEventType(StrEnum):
    """Tipos de eventos observados o generados en el sistema."""

    SCHEDULED_TASK = "scheduled_task"        # Disparo de tarea programada
    TASK_COMPLETED = "task_completed"        # Finalización exitosa de tarea/plan
    TASK_FAILED = "task_failed"              # Fallo o aborto de tarea/plan
    SYSTEM_ERROR = "system_error"            # Error crítico del sistema o excepción
    HEALTH_ALERT = "health_alert"            # Alerta de degradación de hardware/software
    SYSTEM_EVENT = "system_event"            # Evento detectado en Windows (disco, red, app)
    NOTIFICATION = "notification"            # Notificación informativa general


class ProactiveActionType(StrEnum):
    """Acciones resultantes de la evaluación de política proactiva."""

    NOTIFY_USER = "NOTIFY_USER"                      # Enviar notificación directa al usuario (informativa/segura)
    REQUEST_CONFIRMATION = "REQUEST_CONFIRMATION"    # Suspender y solicitar confirmación interactiva explícita
    SAFE_EXECUTE = "SAFE_EXECUTE"                    # Ejecutar acción de nivel SAFE con permisos desatendidos
    SUPPRESS = "SUPPRESS"                            # Descartar o registrar exclusivamente en auditoría


@dataclass(frozen=True)
class ProactiveEvent:
    """Evento proactivo inmutable recibido por el asistente."""

    event_id: str = field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:8]}")
    event_type: ProactiveEventType = ProactiveEventType.NOTIFICATION
    source: str = "system"
    payload: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    proposed_tool: str | None = None
    tool_parameters: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": str(self.event_type),
            "source": self.source,
            "summary": self.summary,
            "proposed_tool": self.proposed_tool,
            "tool_parameters": dict(self.tool_parameters),
            "timestamp": self.timestamp.isoformat(),
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class ProactivePolicyDecision:
    """Decisión inmutable emitida por el motor de políticas proactivas."""

    event_id: str
    action_type: ProactiveActionType
    risk_level: SecurityLevel
    allowed: bool
    reason: str
    user_message: str
    confirmation_required: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "action_type": str(self.action_type),
            "risk_level": str(self.risk_level),
            "allowed": self.allowed,
            "reason": self.reason,
            "user_message": self.user_message,
            "confirmation_required": self.confirmation_required,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class ProactiveExecutionResult:
    """Resultado final inmutable del procesamiento de un evento proactivo."""

    event_id: str
    success: bool
    action_taken: ProactiveActionType
    user_message: str
    execution_data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "success": self.success,
            "action_taken": str(self.action_taken),
            "user_message": self.user_message,
            "execution_data": dict(self.execution_data),
            "timestamp": self.timestamp.isoformat(),
        }
