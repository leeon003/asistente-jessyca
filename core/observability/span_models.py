"""Modelos de datos para el canal TRACE (Etapa 17.0).

Define Span, SpanEvent y SpanStatus — unidades atómicas del árbol de ejecución.

Naming convention de spans: <component>.<operation>
  mcp.request
  executor.execute_step
  security.evaluate_policy
  boundary.registry.write
  plugin.sandbox.execute
  audit.emit
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class SpanStatus(StrEnum):
    """Estado de terminación de un span."""

    OK = "OK"           # Completado sin errores
    ERROR = "ERROR"     # Terminó con un error
    CANCELLED = "CANCELLED"  # Cancelado (Emergency Stop u otro motivo)


@dataclass
class SpanEvent:
    """Evento puntual ocurrido durante la vida de un span.

    Representa momentos significativos que no merecen un span propio
    (ej: 'confirmation.requested', 'emergency_stop.triggered').

    PRIVACIDAD: los atributos NO deben contener secrets, passwords, tokens
    ni contenido sensible. Solo metadata de control y estado.
    """

    name: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    attributes: dict[str, str | int | float | bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "timestamp": self.timestamp.isoformat(),
            "attributes": dict(self.attributes),
        }


@dataclass
class Span:
    """Unidad atómica de un trace — representa una operación con inicio, fin y status.

    Un Span pertenece a exactamente un Trace (identificado por trace_id = correlation_id).
    Los spans se organizan en árbol mediante parent_span_id.

    PRIVACIDAD: Los atributos del span NO deben contener:
    - Passwords, tokens, secrets, API keys
    - Contenido de portapapeles, screenshots, audio
    - Parámetros sin sanitizar de herramientas
    Solo se permiten: nombres de operaciones, risk levels, decisiones de policy,
    IDs de correlación y flags booleanos.
    """

    name: str                           # "component.operation"
    component: str                      # "executor", "boundary.registry", etc.
    trace_id: str                       # = correlation_id del ObservabilityContext
    session_id: str
    span_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_span_id: str | None = None   # None para root span
    task_id: str | None = None
    action_id: str | None = None
    plugin_id: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    duration_ms: float | None = None
    status: SpanStatus = SpanStatus.OK
    attributes: dict[str, str | int | float | bool] = field(default_factory=dict)
    events: list[SpanEvent] = field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None    # sanitizado, sin datos sensibles

    def end(
        self,
        status: SpanStatus = SpanStatus.OK,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Finaliza el span registrando tiempo de fin y duración."""
        self.ended_at = datetime.now(UTC)
        self.duration_ms = (self.ended_at - self.started_at).total_seconds() * 1000
        self.status = status
        if error_type:
            self.error_type = error_type
        if error_message:
            self.error_message = error_message

    def add_event(self, name: str, attributes: dict[str, str | int | float | bool] | None = None) -> None:
        """Agrega un SpanEvent al span actual."""
        self.events.append(SpanEvent(name=name, attributes=attributes or {}))

    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        """Establece un atributo en el span."""
        self.attributes[key] = value

    @property
    def is_finished(self) -> bool:
        return self.ended_at is not None

    def to_dict(self) -> dict[str, Any]:
        """Serialización completa del span para JSONL export."""
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "component": self.component,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "action_id": self.action_id,
            "plugin_id": self.plugin_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_ms": round(self.duration_ms, 3) if self.duration_ms is not None else None,
            "status": str(self.status),
            "attributes": dict(self.attributes),
            "events": [e.to_dict() for e in self.events],
            "error_type": self.error_type,
            "error_message": self.error_message,
        }
