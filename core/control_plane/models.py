"""Modelos y Presupuestos (Budgets) para el Controlled Agent Loop (Etapa 20.1 & Fase 6: Controlled Agent Loop).

GARANTÍAS DE SEGURIDAD:
1. Bounded Execution: Máximo de iteraciones estricto, nunca bucles infinitos.
2. Multi-Dimensional Budgets: Iteraciones/steps, tiempo/timeout, acciones/herramientas, reintentos y tokens.
3. Risk Ceiling: Techo de riesgo inmutable que ninguna acción del loop puede sobrepasar.
4. Stop Safely: Parada segura e inmediata ante cualquier violación de límite, denegación de seguridad o emergencia.
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

    # Aliases de conveniencia (Fase 6)
    @property
    def max_steps(self) -> int:
        return self.max_iterations

    @property
    def max_time(self) -> float:
        return self.global_timeout_seconds

    @property
    def max_actions(self) -> int:
        return self.max_tool_executions

    @property
    def max_risk(self) -> TaskActionRisk:
        return self.risk_ceiling

    @property
    def max_retries(self) -> int:
        return self.max_consecutive_failures

    def __post_init__(self) -> None:
        if self.max_iterations <= 0:
            raise ValueError("max_iterations debe ser mayor a 0.")
        if self.global_timeout_seconds <= 0:
            raise ValueError("global_timeout_seconds debe ser mayor a 0.")
        if self.max_tool_executions <= 0:
            raise ValueError("max_tool_executions debe ser mayor a 0.")
        if self.max_consecutive_failures <= 0:
            raise ValueError("max_consecutive_failures debe ser mayor a 0.")

    @classmethod
    def create(
        cls,
        max_steps: int | None = None,
        max_time: float | None = None,
        max_actions: int | None = None,
        max_risk: TaskActionRisk | str | None = None,
        max_retries: int | None = None,
        max_tokens: int = 50000,
        required_autonomy_level: AutonomyLevel = AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED,
    ) -> AgentBudget:
        """Constructor de conveniencia con nombres de parámetros de Fase 6."""
        risk = TaskActionRisk.DANGEROUS
        if isinstance(max_risk, TaskActionRisk):
            risk = max_risk
        elif isinstance(max_risk, str):
            try:
                risk = TaskActionRisk(max_risk.lower())
            except ValueError:
                risk = TaskActionRisk.DANGEROUS

        return cls(
            max_iterations=max_steps if max_steps is not None else 10,
            global_timeout_seconds=max_time if max_time is not None else 60.0,
            max_tool_executions=max_actions if max_actions is not None else 15,
            max_tokens=max_tokens,
            risk_ceiling=risk,
            required_autonomy_level=required_autonomy_level,
            max_consecutive_failures=max_retries if max_retries is not None else 3,
        )


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

        # 2. Máximo de iteraciones / steps
        if self.iterations_count >= budget.max_iterations:
            return (
                True,
                f"Límite de iteraciones alcanzado ({self.iterations_count} >= {budget.max_iterations}).",
                AgentLoopState.STOPPED_LIMIT_REACHED,
            )

        # 3. Límite de herramientas / acciones
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

        # 5. Fallos repetidos consecutivos / reintentos agotados
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
            "final_state": str(self.final_state),
            "is_success": self.is_success,
            "iterations_executed": self.iterations_executed,
            "tools_executed": self.tools_executed,
            "tokens_consumed": self.tokens_consumed,
            "duration_seconds": self.duration_seconds,
            "stop_reason": self.stop_reason,
            "output_metadata": dict(self.output_metadata),
            "history_trace_length": len(self.history_trace),
        }
