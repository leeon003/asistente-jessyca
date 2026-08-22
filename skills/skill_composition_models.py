"""Modelos de datos inmutables y estructuras formales para el Skill Composition Engine (Fase 35).

Define las entidades que gobiernan la composición declarativa de múltiples Skills:
- Modos de ejecución (SEQUENTIAL, PARALLEL, CONDITIONAL).
- Políticas de fallo y recuperación (FAIL_FAST, CONTINUE_WHERE_SAFE, ROLLBACK_WHERE_SUPPORTED).
- Estados de la composición (PENDING, RUNNING, WAITING_CONFIRMATION, PAUSED, COMPLETED, FAILED, CANCELLED).
- Pasos, contextos y resultados agregados.

PRINCIPIO INVIOLABLE:
Una Skill compuesta NO obtiene privilegios superiores a las Skills que contiene.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.cancellation import CancellationToken
from core.control_plane.models import AgentBudget
from core.security_architecture import SecurityLevel
from skills.skill_models import SkillStatus


class CompositionExecutionMode(StrEnum):
    """Modos formales de ejecución de una composición de Skills."""

    SEQUENTIAL = "SEQUENTIAL"
    PARALLEL = "PARALLEL"
    CONDITIONAL = "CONDITIONAL"


class CompositionErrorPolicy(StrEnum):
    """Políticas de gestión de errores en la ejecución de pasos de una composición."""

    FAIL_FAST = "FAIL_FAST"
    CONTINUE_WHERE_SAFE = "CONTINUE_WHERE_SAFE"
    ROLLBACK_WHERE_SUPPORTED = "ROLLBACK_WHERE_SUPPORTED"


class CompositionStatus(StrEnum):
    """Estados del ciclo de vida de una composición de Skills."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class SkillCompositionStep:
    """Paso individual estructurado dentro de una composición de Skills."""

    step_id: str
    skill_id: str
    version_constraint: str | None = None
    input_mapping: dict[str, Any] = field(default_factory=dict)
    condition: str | dict[str, Any] | None = None
    timeout_seconds: float = 60.0
    error_policy: CompositionErrorPolicy = CompositionErrorPolicy.FAIL_FAST
    requires_confirmation: bool = False
    depends_on: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "skill_id": self.skill_id,
            "version_constraint": self.version_constraint,
            "input_mapping": dict(self.input_mapping),
            "condition": self.condition,
            "timeout_seconds": self.timeout_seconds,
            "error_policy": str(self.error_policy),
            "requires_confirmation": self.requires_confirmation,
            "depends_on": list(self.depends_on),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SkillComposition:
    """Definición declarativa inmutable de una composición de Skills."""

    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    steps: tuple[SkillCompositionStep, ...] = ()
    execution_mode: CompositionExecutionMode = CompositionExecutionMode.SEQUENTIAL
    error_policy: CompositionErrorPolicy = CompositionErrorPolicy.FAIL_FAST
    inputs_schema: dict[str, Any] = field(default_factory=dict)
    outputs_schema: dict[str, Any] = field(default_factory=dict)
    output_mapping: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 300.0
    max_steps: int = 50
    risk_ceiling: SecurityLevel | None = None
    author: str = "JESSYCA Composer"
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps],
            "execution_mode": str(self.execution_mode),
            "error_policy": str(self.error_policy),
            "inputs_schema": dict(self.inputs_schema),
            "outputs_schema": dict(self.outputs_schema),
            "output_mapping": dict(self.output_mapping),
            "timeout_seconds": self.timeout_seconds,
            "max_steps": self.max_steps,
            "risk_ceiling": str(self.risk_ceiling) if self.risk_ceiling else None,
            "author": self.author,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class SkillCompositionStepResult:
    """Resultado estructurado inmutable de la ejecución de un paso de composición."""

    step_id: str
    skill_id: str
    success: bool
    status: SkillStatus
    input_parameters: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    security_decision: str = "ALLOW"
    skipped: bool = False
    skip_reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "skill_id": self.skill_id,
            "success": self.success,
            "status": str(self.status),
            "input_parameters": dict(self.input_parameters),
            "output": self.output,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "security_decision": self.security_decision,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "timestamp": self.timestamp,
        }


@dataclass
class SkillCompositionContext:
    """Contexto dinámico de ejecución de una composición de Skills."""

    composition_id: str
    execution_id: str = field(default_factory=lambda: f"compexec-{uuid.uuid4().hex[:8]}")
    inputs: dict[str, Any] = field(default_factory=dict)
    step_results: dict[str, SkillCompositionStepResult] = field(default_factory=dict)
    session_id: str = "default_session"
    user: str = "user"
    cancellation_token: CancellationToken | None = None
    budget: AgentBudget | None = None
    nesting_level: int = 0
    max_nesting_level: int = 5
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "composition_id": self.composition_id,
            "execution_id": self.execution_id,
            "inputs": dict(self.inputs),
            "step_results": {k: v.to_dict() for k, v in self.step_results.items()},
            "session_id": self.session_id,
            "user": self.user,
            "nesting_level": self.nesting_level,
            "max_nesting_level": self.max_nesting_level,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class SkillCompositionResult:
    """Resultado formal inmutable y explicable de la ejecución de una composición."""

    composition_id: str
    execution_id: str
    success: bool
    status: CompositionStatus
    output: dict[str, Any] = field(default_factory=dict)
    step_results: dict[str, SkillCompositionStepResult] = field(default_factory=dict)
    aggregated_risk: SecurityLevel = SecurityLevel.SAFE
    error: str | None = None
    duration_ms: float = 0.0
    warnings: tuple[str, ...] = ()
    steps_executed: int = 0
    steps_skipped: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "composition_id": self.composition_id,
            "execution_id": self.execution_id,
            "success": self.success,
            "status": str(self.status),
            "output": dict(self.output),
            "step_results": {k: v.to_dict() for k, v in self.step_results.items()},
            "aggregated_risk": str(self.aggregated_risk),
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "warnings": list(self.warnings),
            "steps_executed": self.steps_executed,
            "steps_skipped": self.steps_skipped,
            "timestamp": self.timestamp,
        }
