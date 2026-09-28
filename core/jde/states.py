"""Estados canónicos del JESSYCA Decision Engine (JDE).

Define los estados deterministas e inmutables del ciclo de vida de una decisión.
Regla fundamental: "tool execution succeeded" != "real-world action succeeded".
"""

from __future__ import annotations

from enum import StrEnum


class DecisionState(StrEnum):
    """Estados canónicos y formales del JESSYCA Decision Engine (JDE)."""

    RECEIVED = "RECEIVED"
    ANALYZING = "ANALYZING"
    PLANNED = "PLANNED"
    AUTHORIZED = "AUTHORIZED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    NOT_EXECUTED = "NOT_EXECUTED"
    BLOCKED = "BLOCKED"
    RETRY = "RETRY"
    FALLBACK = "FALLBACK"
    # Estados de error y gobernanza formal (Fase 8)
    NO_DECISION = "NO_DECISION"
    CONFLICT = "CONFLICT"
    DENIED = "DENIED"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    PARTIAL = "PARTIAL"
    ESCALATED = "ESCALATED"

    @property
    def is_terminal(self) -> bool:
        """Indica si el estado representa un punto final del ciclo de decisión."""
        return self in (
            DecisionState.SUCCESS,
            DecisionState.FAILED,
            DecisionState.UNKNOWN,
            DecisionState.NOT_EXECUTED,
            DecisionState.BLOCKED,
            DecisionState.NO_DECISION,
            DecisionState.CONFLICT,
            DecisionState.DENIED,
            DecisionState.REQUIRES_CONFIRMATION,
            DecisionState.EXECUTION_FAILED,
            DecisionState.VERIFICATION_FAILED,
            DecisionState.PARTIAL,
            DecisionState.ESCALATED,
        )

    @property
    def is_action_completed(self) -> bool:
        """Indica si el estado final garantiza verificación positiva real en el sistema operativo."""
        return self == DecisionState.SUCCESS


class ExecutionStatusType(StrEnum):
    """Estado de la fase física de ejecución del Executor (independiente del Verifier)."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    OK = "OK"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    SKIPPED = "SKIPPED"


class VerificationStatusType(StrEnum):
    """Estado de la comprobación observable del Verifier."""

    NOT_RUN = "NOT_RUN"
    VERIFIED_TRUE = "VERIFIED_TRUE"
    VERIFIED_FALSE = "VERIFIED_FALSE"
    UNVERIFIABLE = "UNVERIFIABLE"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"
    TIMEOUT = "TIMEOUT"
