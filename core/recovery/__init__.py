"""Subsistema de Recuperación Controlada ante Fallos (Etapa 17.3).

Proporciona:
  - FailureClassification: TRANSIENT, RECOVERABLE, PERMANENT, UNKNOWN.
  - CircuitState: CLOSED, OPEN, HALF_OPEN.
  - CircuitBreaker & CircuitBreakerOpenError.
  - FailureClassifier: Detección determinista de la naturaleza del fallo.
  - RetryPolicy: Políticas de reintentos acotados con backoff exponencial.
  - ControlledFailureRecovery & get_recovery_coordinator: Orquestador central.
  - EscalationPayload & RecoveryResult: Modelos estructurados de respuesta.
"""

from core.recovery.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from core.recovery.classifier import FailureClassifier
from core.recovery.models import (
    CircuitState,
    EscalationPayload,
    FailureClassification,
    RecoveryResult,
    RetryPolicy,
)
from core.recovery.recovery_coordinator import (
    ControlledFailureRecovery,
    get_recovery_coordinator,
)

__all__ = [
    "FailureClassification",
    "CircuitState",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "FailureClassifier",
    "RetryPolicy",
    "EscalationPayload",
    "RecoveryResult",
    "ControlledFailureRecovery",
    "get_recovery_coordinator",
]
