"""Modelos de Datos para el Subsistema de Recuperación Controlada ante Fallos (Etapa 17.3).

Define:
  - FailureClassification: Clasificación canónica (TRANSIENT, RECOVERABLE, PERMANENT, UNKNOWN).
  - CircuitState: Estados del Circuit Breaker (CLOSED, OPEN, HALF_OPEN).
  - RetryPolicy: Política acotada de reintentos con backoff exponencial.
  - RecoveryResult: Resultado detallado de la ejecución resiliente y escalada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.autonomy.autonomy_level import TaskActionRisk


class FailureClassification(StrEnum):
    """Clasificación formal de naturaleza del fallo."""

    TRANSIENT = "TRANSIENT"
    """Fallo temporal (latencia de red, bloqueo I/O momentáneo, timeout breve). Elegible para retry acotado."""

    RECOVERABLE = "RECOVERABLE"
    """Fallo recuperable mediante reinicialización de sesión o ruta alterna controlada."""

    PERMANENT = "PERMANENT"
    """Fallo permanente (archivo no encontrado, error de sintaxis, permiso denegado). CERO RETRIES."""

    UNKNOWN = "UNKNOWN"
    """Fallo de causa no catalogada. Tratamiento conservador sin reintentos agresivos."""


class CircuitState(StrEnum):
    """Estados canónicos del Circuit Breaker."""

    CLOSED = "CLOSED"
    """Circuito cerrado: Operación normal. Todas las solicitudes fluyen hacia la herramienta."""

    OPEN = "OPEN"
    """Circuito abierto: Fallos reiterados detectados. Rechazo inmediato de solicitudes para proteger el sistema."""

    HALF_OPEN = "HALF_OPEN"
    """Circuito semiabierto: Periodo de prueba tras cooldown. Permite una solicitud sonda para verificar recuperación."""


@dataclass(frozen=True)
class RetryPolicy:
    """Política determinista y acotada de reintentos para operaciones seguras."""

    max_retries: int = 3
    """Límite superior estricto de reintentos. PROHIBIDO retries ilimitados (max <= 5)."""

    initial_delay_sec: float = 0.1
    """Tiempo base de espera inicial antes del primer reintento."""

    max_delay_sec: float = 2.0
    """Límite superior del retardo de backoff exponencial."""

    backoff_multiplier: float = 2.0
    """Factor multiplicador para el backoff exponencial."""

    timeout_sec: float = 5.0
    """Tiempo máximo de ejecución por intento antes de lanzar TimeoutError."""

    allowed_risks_for_retry: tuple[TaskActionRisk, ...] = (
        TaskActionRisk.READ_ONLY,
        TaskActionRisk.LOW_RISK,
    )
    """Riesgos permitidos para reintento automático. DANGEROUS y CRITICAL están estrictamente excluidos."""

    def __post_init__(self) -> None:
        if self.max_retries > 5:
            raise ValueError(f"max_retries={self.max_retries} excede el límite máximo de seguridad permitido (5).")
        if self.max_retries < 0:
            raise ValueError("max_retries no puede ser negativo.")

    def is_retry_allowed_for_risk(self, risk: TaskActionRisk) -> bool:
        """Verifica si el nivel de riesgo permite reintentos automáticos.

        GARANTÍA DE SEGURIDAD:
        DANGEROUS y CRITICAL NUNCA son reintentados automáticamente.
        """
        if risk in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL):
            return False
        return risk in self.allowed_risks_for_retry


@dataclass(frozen=True)
class EscalationPayload:
    """Información estructurada para escalado al usuario humano ante fallos persistentes."""

    tool_name: str
    operation: str
    failure_reason: str
    classification: FailureClassification
    attempts_made: int
    circuit_state: CircuitState
    suggested_user_action: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "operation": self.operation,
            "failure_reason": self.failure_reason,
            "classification": self.classification.value,
            "attempts_made": self.attempts_made,
            "circuit_state": self.circuit_state.value,
            "suggested_user_action": self.suggested_user_action,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class RecoveryResult:
    """Resultado consolidado del proceso de ejecución resiliente y recuperación controlada."""

    success: bool
    result: Any = None
    attempts: int = 1
    final_error: str | None = None
    classification: FailureClassification = FailureClassification.TRANSIENT
    escalated_to_user: bool = False
    escalation_payload: EscalationPayload | None = None
    circuit_state: CircuitState = CircuitState.CLOSED
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "attempts": self.attempts,
            "final_error": self.final_error,
            "classification": self.classification.value,
            "escalated_to_user": self.escalated_to_user,
            "escalation_payload": self.escalation_payload.to_dict() if self.escalation_payload else None,
            "circuit_state": self.circuit_state.value,
            "duration_ms": round(self.duration_ms, 2),
        }
