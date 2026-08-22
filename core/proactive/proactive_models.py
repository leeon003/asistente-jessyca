"""Modelos de datos inmutables y contratos para el Motor de Inteligencia Proactiva (Fase 44).

Define fuentes de eventos, evaluaciones de relevancia, decisiones anti-spam,
configuraciones de control de usuario, sugerencias y resultados del pipeline proactivo.

PRINCIPIOS E INVARIANTES DE SEGURIDAD:
1. PROACTIVE != UNCONTROLLED AUTONOMY (JESSYCA detecta, analiza, sugiere y pregunta; sólo ejecuta si AutonomyPolicy lo autoriza).
2. EXTERNAL EVENT = UNTRUSTED DATA (Ningún dato de navegador, documento, app o memoria se convierte automáticamente en instrucción).
3. Prevalencia de Parada de Emergencia (EmergencyStopManager detiene inmediatamente cualquier acción proactiva).
4. Control Soberano del Usuario (Habilitar, deshabilitar, silenciar/mutear y configurar).
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.autonomy.autonomy_level import AutonomyLevel
from core.security_architecture import SecurityLevel


class EventSourceType(StrEnum):
    """Fuentes existentes y soportadas de eventos proactivos."""

    SCHEDULER = "scheduler"
    APPLICATION_STATE = "application_state"
    CALENDAR = "calendar"
    FILES = "files"
    BROWSER = "browser"
    SYSTEM_EVENTS = "system_events"
    USER_INTERACTION = "user_interaction"
    UNKNOWN = "unknown"


class ProactiveEventType(StrEnum):
    """Tipos de eventos observados o procesados por el motor proactivo."""

    SCHEDULED_TASK = "scheduled_task"        # Disparo de tarea programada
    TASK_COMPLETED = "task_completed"        # Finalización exitosa de tarea/plan
    TASK_FAILED = "task_failed"              # Fallo o aborto de tarea/plan
    SYSTEM_ERROR = "system_error"            # Error crítico del sistema o excepción
    HEALTH_ALERT = "health_alert"            # Alerta de degradación de hardware/software
    SYSTEM_EVENT = "system_event"            # Evento detectado en Windows (disco, red, app)
    NOTIFICATION = "notification"            # Notificación informativa general
    CALENDAR_UPCOMING = "calendar_upcoming"  # Reunión o evento de calendario próximo
    FILE_MODIFIED = "file_modified"          # Modificación o creación relevante de archivo
    BROWSER_ACTIVITY = "browser_activity"    # Actividad de navegación o contexto web
    USER_CONTEXT_CHANGE = "user_context_change"  # Cambio de foco o estado de interacción


class ProactiveActionType(StrEnum):
    """Acciones resultantes de la evaluación de la política proactiva."""

    NOTIFY_USER = "NOTIFY_USER"                      # Enviar notificación directa al usuario (informativa/segura)
    REQUEST_CONFIRMATION = "REQUEST_CONFIRMATION"    # Solicitar confirmación interactiva humana antes de proceder
    SUGGEST_ACTION = "SUGGEST_ACTION"                # Proponer una sugerencia amigable sin auto-ejecución ("¿Quieres que...?")
    ASK_USER = "ASK_USER"                            # Formular una pregunta de clarificación o decisión al usuario
    SAFE_EXECUTE = "SAFE_EXECUTE"                    # Ejecutar acción de nivel SAFE con permisos desatendidos
    SUPPRESS = "SUPPRESS"                            # Descartar o suprimir por irrelevancia, spam o política


@dataclass(frozen=True)
class ProactiveEvent:
    """Evento proactivo inmutable recibido por el pipeline."""

    event_id: str = field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:8]}")
    event_type: ProactiveEventType = ProactiveEventType.NOTIFICATION
    source: str = "system"
    source_type: EventSourceType = EventSourceType.SYSTEM_EVENTS
    payload: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    proposed_tool: str | None = None
    tool_parameters: dict[str, Any] = field(default_factory=dict)
    is_untrusted_data: bool = True
    context_metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def compute_fingerprint(self) -> str:
        """Calcula un hash determinista para deduplicación y anti-spam."""
        raw = f"{self.event_type}:{self.source}:{self.proposed_tool}:{self.summary}:{json.dumps(self.tool_parameters, sort_keys=True)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": str(self.event_type),
            "source": self.source,
            "source_type": str(self.source_type),
            "summary": self.summary,
            "proposed_tool": self.proposed_tool,
            "tool_parameters": dict(self.tool_parameters),
            "is_untrusted_data": self.is_untrusted_data,
            "context_metadata": dict(self.context_metadata),
            "timestamp": self.timestamp.isoformat(),
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class RelevanceAssessment:
    """Evaluación de relevancia, urgencia y confianza de un evento."""

    relevance: float         # 0.0 a 1.0
    urgency: float           # 0.0 a 1.0
    confidence: float        # 0.0 a 1.0
    is_relevant: bool
    reason: str
    context_match: dict[str, Any] = field(default_factory=dict)
    topic_keywords: list[str] = field(default_factory=list)

    def composite_score(self) -> float:
        """Calcula una puntuación ponderada para priorización."""
        return (0.45 * self.relevance) + (0.35 * self.urgency) + (0.20 * self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "relevance": round(self.relevance, 3),
            "urgency": round(self.urgency, 3),
            "confidence": round(self.confidence, 3),
            "composite_score": round(self.composite_score(), 3),
            "is_relevant": self.is_relevant,
            "reason": self.reason,
            "context_match": dict(self.context_match),
            "topic_keywords": list(self.topic_keywords),
        }


@dataclass(frozen=True)
class AntiSpamDecision:
    """Resultado inmutable de la evaluación anti-spam y deduplicación."""

    allowed: bool
    reason: str
    fingerprint: str = ""
    cooldown_remaining_seconds: float = 0.0
    suppressed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "fingerprint": self.fingerprint,
            "cooldown_remaining_seconds": round(self.cooldown_remaining_seconds, 2),
            "suppressed": self.suppressed,
        }


@dataclass
class UserControlSettings:
    """Configuración de control del usuario para la inteligencia proactiva."""

    enabled: bool = True
    muted_until: float | None = None
    min_relevance_threshold: float = 0.5
    min_confidence_threshold: float = 0.4
    cooldown_seconds: float = 30.0
    max_suggestions_per_hour: int = 15
    autonomous_execution_allowed: bool = False  # Si True, permite SAFE_EXECUTE bajo AutonomyPolicy
    allowed_sources: set[EventSourceType] = field(
        default_factory=lambda: {
            EventSourceType.SCHEDULER,
            EventSourceType.APPLICATION_STATE,
            EventSourceType.CALENDAR,
            EventSourceType.FILES,
            EventSourceType.BROWSER,
            EventSourceType.SYSTEM_EVENTS,
            EventSourceType.USER_INTERACTION,
        }
    )
    quiet_hours_start: int | None = None  # Ej: 22 (10 PM)
    quiet_hours_end: int | None = None    # Ej: 7 (7 AM)

    def is_in_quiet_hours(self) -> bool:
        """Comprueba si la hora actual cae en el horario de silencio configurado."""
        if self.quiet_hours_start is None or self.quiet_hours_end is None:
            return False
        current_hour = datetime.now().hour
        if self.quiet_hours_start <= self.quiet_hours_end:
            return self.quiet_hours_start <= current_hour < self.quiet_hours_end
        # Cruza medianoche (ej: 22 a 7)
        return current_hour >= self.quiet_hours_start or current_hour < self.quiet_hours_end

    def is_muted(self) -> bool:
        """Verifica si el asistente proactivo está silenciado actualmente."""
        if self.muted_until is None:
            return False
        return time.time() < self.muted_until

    def is_active(self) -> bool:
        """Verifica si el motor proactivo puede emitir sugerencias al usuario."""
        if not self.enabled:
            return False
        if self.is_muted():
            return False
        if self.is_in_quiet_hours():
            return False
        return True


@dataclass(frozen=True)
class ProactiveSuggestion:
    """Sugerencia o propuesta estructurada generada para el usuario."""

    suggestion_id: str = field(default_factory=lambda: f"sug-{uuid.uuid4().hex[:8]}")
    event_id: str = ""
    title: str = ""
    user_prompt: str = ""
    proposed_tool: str | None = None
    tool_parameters: dict[str, Any] = field(default_factory=dict)
    relevance: float = 1.0
    urgency: float = 0.5
    confidence: float = 1.0
    requires_confirmation: bool = True
    risk_level: SecurityLevel = SecurityLevel.SAFE
    autonomy_level: AutonomyLevel = AutonomyLevel.LEVEL_1_SUGGEST
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id,
            "event_id": self.event_id,
            "title": self.title,
            "user_prompt": self.user_prompt,
            "proposed_tool": self.proposed_tool,
            "tool_parameters": dict(self.tool_parameters),
            "relevance": self.relevance,
            "urgency": self.urgency,
            "confidence": self.confidence,
            "requires_confirmation": self.requires_confirmation,
            "risk_level": str(self.risk_level),
            "autonomy_level": str(self.autonomy_level),
            "timestamp": self.timestamp.isoformat(),
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
