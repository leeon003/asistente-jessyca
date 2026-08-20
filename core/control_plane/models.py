"""Modelos y Presupuestos (Budgets) para el Controlled Agent Loop (Etapa 20.1).

GARANTÍAS DE SEGURIDAD:
1. Bounded Execution: Máximo de iteraciones estricto, nunca bucles infinitos.
2. Multi-Dimensional Budgets: Iteraciones, tiempo (timeout), herramientas y tokens.
3. Risk Ceiling: Techo de riesgo inmutable que ninguna acción del loop puede sobrepasar.
4. Stop Safely: Parada segura e inmediata ante cualquier violación de límite o emergencia.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk


class AgentLoopState(StrEnum):
    """Estados del ciclo de vida del Controlled Agent Loop."""

    IDLE = "IDLE"
    OBSERVING = "OBSERVING"
    INTERPRETING = "INTERPRETING"
    RETRIEVING = "RETRIEVING"
    PLANNING = "PLANNING"
    CHECKING_POLICY = "CHECKING_POLICY"
    ACTING = "ACTING"
    VERIFYING = "VERIFYING"
    UPDATING = "UPDATING"

    # Estados terminales seguros
    COMPLETED = "COMPLETED"
    STOPPED_LIMIT_REACHED = "STOPPED_LIMIT_REACHED"
    STOPPED_TIMEOUT = "STOPPED_TIMEOUT"
    STOPPED_CANCELLED = "STOPPED_CANCELLED"
    STOPPED_EMERGENCY = "STOPPED_EMERGENCY"
    STOPPED_PERMISSION_DENIED = "STOPPED_PERMISSION_DENIED"
    STOPPED_REPEATED_FAILURE = "STOPPED_REPEATED_FAILURE"
    STOPPED_ERROR = "STOPPED_ERROR"


@dataclass(frozen=True)
class AgentBudget:
    """Presupuesto acotado y techo de riesgo para una tarea en el Agent Loop."""

    max_iterations: int = 10
    global_timeout_seconds: float = 60.0
    max_tool_executions: int = 15
    max_tokens: int = 50000
    risk_ceiling: TaskActionRisk = TaskActionRisk.DANGEROUS
    required_autonomy_level: AutonomyLevel = AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED
    max_consecutive_failures: int = 3

    def __post_init__(self) -> None:
        if self.max_iterations <= 0:
            raise ValueError("max_iterations debe ser mayor a 0.")
        if self.global_timeout_seconds <= 0:
            raise ValueError("global_timeout_seconds debe ser mayor a 0.")
        if self.max_tool_executions <= 0:
            raise ValueError("max_tool_executions debe ser mayor a 0.")


@dataclass
class BudgetTracker:
    """Rastreador mutable en tiempo de ejecución del consumo de recursos del loop."""

    iterations_count: int = 0
    tools_executed_count: int = 0
    tokens_consumed_count: int = 0
    consecutive_failures_count: int = 0
    start_monotonic: float = field(default_factory=time.monotonic)
    start_datetime: datetime = field(default_factory=lambda: datetime.now(UTC))

    def elapsed_seconds(self) -> float:
        """Retorna el tiempo transcurrido en segundos desde el inicio."""
        return time.monotonic() - self.start_monotonic

    def check_limits(self, budget: AgentBudget) -> tuple[bool, str | None, AgentLoopState | None]:
        """Comprueba si algún límite del presupuesto ha sido alcanzado.

        Returns:
            tuple[bool, str | None, AgentLoopState | None]: (exceeded, reason, terminal_state)
        """
        # 1. Timeout global
        if self.elapsed_seconds() >= budget.global_timeout_seconds:
            return (
                True,
                f"Timeout global alcanzado ({self.elapsed_seconds():.2f}s >= {budget.global_timeout_seconds:.2f}s).",
                AgentLoopState.STOPPED_TIMEOUT,
            )

        # 2. Máximo de iteraciones
        if self.iterations_count >= budget.max_iterations:
            return (
                True,
                f"Límite de iteraciones alcanzado ({self.iterations_count} >= {budget.max_iterations}).",
                AgentLoopState.STOPPED_LIMIT_REACHED,
            )

        # 3. Límite de herramientas
        if self.tools_executed_count >= budget.max_tool_executions:
            return (
                True,
                f"Límite de herramientas ejecutadas alcanzado ({self.tools_executed_count} >= {budget.max_tool_executions}).",
                AgentLoopState.STOPPED_LIMIT_REACHED,
            )

        # 4. Límite de tokens
        if self.tokens_consumed_count >= budget.max_tokens:
            return (
                True,
                f"Presupuesto de tokens excedido ({self.tokens_consumed_count} >= {budget.max_tokens}).",
                AgentLoopState.STOPPED_LIMIT_REACHED,
            )

        # 5. Fallos repetidos consecutivos
        if self.consecutive_failures_count >= budget.max_consecutive_failures:
            return (
                True,
                f"Límite de fallos consecutivos alcanzado ({self.consecutive_failures_count} >= {budget.max_consecutive_failures}).",
                AgentLoopState.STOPPED_REPEATED_FAILURE,
            )

        return False, None, None


@dataclass(frozen=True)
class AgentLoopResult:
    """Resultado inmutable del ciclo del agente."""

    task_id: str
    intent: str
    final_state: AgentLoopState
    iterations_executed: int
    tools_executed: int
    tokens_consumed: int
    duration_seconds: float
    stop_reason: str
    output_metadata: dict[str, Any] = field(default_factory=dict)
    history_trace: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def is_success(self) -> bool:
        return self.final_state == AgentLoopState.COMPLETED

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "intent": self.intent,
            "final_state": self.final_state.value,
            "iterations_executed": self.iterations_executed,
            "tools_executed": self.tools_executed,
            "tokens_consumed": self.tokens_consumed,
            "duration_seconds": round(self.duration_seconds, 3),
            "stop_reason": self.stop_reason,
            "output_metadata": self.output_metadata,
            "trace_steps_count": len(self.history_trace),
        }
