"""Modelos inmutables de Planificación y Ejecución Estructurada (plan_models.py - Fase 23).

Define las estructuras formales para:
USER GOAL -> INTENT -> PLAN -> VALIDATION -> SECURITY -> EXECUTION -> VERIFICATION -> RESULT

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. PLANNER != AUTHORIZATION (El plan es una propuesta de pasos, no confiere autoridad ni permisos).
2. UNTRUSTED DATA: Todo paso del plan debe ser re-validado por el SecurityPipeline antes de ACT.
3. Grafo Acíclico (DAG): Queda estrictamente prohibida la dependencia cíclica entre pasos.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.control_plane.models import AgentBudget
from core.security_architecture import SecurityLevel


class StepStatus(StrEnum):
    """Estado de ejecución de un paso individual del plan."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class PlanStatus(StrEnum):
    """Estado global del ciclo de vida del plan de ejecución."""

    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PAUSED = "PAUSED"


@dataclass(frozen=True)
class PlanStep:
    """Paso individual inmutable dentro de un plan estructurado y verificable."""

    step_id: str
    description: str
    required_agent: str
    required_tool: str | None = None
    tool_parameters: dict[str, Any] = field(default_factory=dict)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    risk_level: SecurityLevel = SecurityLevel.SAFE
    preconditions: tuple[str, ...] = field(default_factory=tuple)
    expected_outcome: str = ""
    success_criteria: str | None = None
    timeout_seconds: float = 30.0
    budget: AgentBudget | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "description": self.description,
            "required_agent": self.required_agent,
            "required_tool": self.required_tool,
            "tool_parameters": dict(self.tool_parameters),
            "dependencies": list(self.dependencies),
            "risk_level": str(self.risk_level),
            "preconditions": list(self.preconditions),
            "expected_outcome": self.expected_outcome,
            "success_criteria": self.success_criteria,
            "timeout_seconds": self.timeout_seconds,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ExecutionPlan:
    """Plan formal, acíclico y verificable para alcanzar un objetivo del usuario."""

    plan_id: str
    goal: str
    steps: tuple[PlanStep, ...]
    status: PlanStatus = PlanStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    max_total_timeout_seconds: float = 120.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        goal: str,
        steps: list[PlanStep] | tuple[PlanStep, ...],
        plan_id: str | None = None,
        max_total_timeout_seconds: float = 120.0,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionPlan:
        """Constructor seguro para crear un ExecutionPlan inmutable."""
        pid = plan_id or f"plan_{uuid.uuid4().hex[:10]}"
        return cls(
            plan_id=pid,
            goal=str(goal).strip(),
            steps=tuple(steps),
            status=PlanStatus.DRAFT,
            created_at=datetime.now(UTC),
            max_total_timeout_seconds=max_total_timeout_seconds,
            metadata=dict(metadata or {}),
        )

    def with_status(self, new_status: PlanStatus) -> ExecutionPlan:
        """Retorna una copia inmutable con el nuevo estado del plan."""
        return ExecutionPlan(
            plan_id=self.plan_id,
            goal=self.goal,
            steps=self.steps,
            status=new_status,
            created_at=self.created_at,
            max_total_timeout_seconds=self.max_total_timeout_seconds,
            metadata=self.metadata,
        )

    def get_step(self, step_id: str) -> PlanStep | None:
        """Busca un paso por su identificador."""
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "status": str(self.status),
            "step_count": len(self.steps),
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at.isoformat(),
            "max_total_timeout_seconds": self.max_total_timeout_seconds,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PlanStepResult:
    """Resultado inmutable de la ejecución de un paso del plan."""

    step_id: str
    status: StepStatus
    output: Any = None
    error: str | None = None
    duration_seconds: float = 0.0
    verified: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": str(self.status),
            "output": self.output,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "verified": self.verified,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PlanExecutionResult:
    """Resultado consolidado e inmutable de la ejecución total del plan."""

    plan_id: str
    goal: str
    status: PlanStatus
    steps_executed: int
    step_results: tuple[PlanStepResult, ...]
    duration_seconds: float
    error: str | None = None
    is_success: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "status": str(self.status),
            "is_success": self.is_success,
            "steps_executed": self.steps_executed,
            "step_results": [r.to_dict() for r in self.step_results],
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "metadata": dict(self.metadata),
        }
