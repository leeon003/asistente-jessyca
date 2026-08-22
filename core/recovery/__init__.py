"""Subsistema de Recuperación Controlada, Resiliencia y Hardening de JESSYCA (core.recovery)."""

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
from core.recovery.system_hardening import (
    IdempotencyManager,
    StateRecoveryManager,
    SystemHardeningEngine,
    TaskCheckpoint,
    TaskExecutionState,
)

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "CircuitState",
    "ControlledFailureRecovery",
    "EscalationPayload",
    "FailureClassification",
    "FailureClassifier",
    "IdempotencyManager",
    "RecoveryResult",
    "RetryPolicy",
    "StateRecoveryManager",
    "SystemHardeningEngine",
    "TaskCheckpoint",
    "TaskExecutionState",
    "get_recovery_coordinator",
]
