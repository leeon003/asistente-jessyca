"""Modelos de Datos para el Motor de Workflows Multi-Step (Etapa 18.0 / 18.1).

Define:
  - WorkflowState: Los 9 estados formales del ciclo de vida del workflow.
  - StepState: Estados atómicos de cada paso en el pipeline.
  - WorkflowStep: Definición declarativa de un paso explícito.
  - StepVerificationRule: Regla determinista de aserción post-ejecución.
  - StepExecutionResult & WorkflowExecutionResult: Resultados tipados.
  - WorkflowDefinition: Contrato inmutable del flujo multi-paso.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk


class WorkflowState(StrEnum):
    """Estados canónicos del ciclo de vida de un Workflow (Etapas 18.0 y 18.2)."""

    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    PAUSED_REQUIRES_REVIEW = "PAUSED_REQUIRES_REVIEW"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    ROLLING_BACK = "ROLLING_BACK"


class StepState(StrEnum):
    """Estados del ciclo de vida individual de un paso (Step)."""

    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    AUTHORIZING = "AUTHORIZING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RECORDING = "RECORDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    ROLLED_BACK = "ROLLED_BACK"


class WorkflowSource(StrEnum):
    """Fuentes legítimas autorizadas para la definición de workflows."""

    SYSTEM = "SYSTEM"
    USER = "USER"
    ADMINISTRATOR = "ADMINISTRATOR"
    CONFIGURATION = "CONFIGURATION"
    BUILTIN = "BUILTIN"


@dataclass(frozen=True)
class StepVerificationRule:
    """Regla inmutable de verificación y aserción post-ejecución de un paso."""

    rule_name: str
    validator_fn: Callable[[Any], bool]
    expected_description: str = ""

    def verify(self, output: Any) -> bool:
        """Ejecuta la función validadora de forma segura."""
        try:
            return bool(self.validator_fn(output))
        except Exception:
            return False


@dataclass(frozen=True)
class WorkflowStep:
    """Definición declarativa inmutable de un paso individual en un Workflow."""

    step_id: str
    name: str
    tool_name: str
    operation: str
    parameters: dict[str, Any] = field(default_factory=dict)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    timeout_sec: float = 30.0
    risk_level: TaskActionRisk = TaskActionRisk.LOW_RISK
    required_autonomy_level: AutonomyLevel = AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION
    requires_confirmation: bool = False
    requires_verification: bool = False
    verification_rule: StepVerificationRule | None = None
    expected_state: Any | None = None  # ExpectedState (Etapa 18.3)
    observer_fn: Callable[[], Any] | None = None
    compensation_tool: str | None = None
    compensation_operation: str | None = None
    compensation_parameters: dict[str, Any] = field(default_factory=dict)
    max_retries: int = 0  # Reintentos acotados a nivel de step (solo permitido si risk es seguro)

    def to_dict(self) -> dict[str, Any]:
        """Serializa el paso a formato estructurado."""
        return {
            "step_id": self.step_id,
            "name": self.name,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "parameters": self.parameters,
            "dependencies": list(self.dependencies),
            "timeout_sec": self.timeout_sec,
            "risk_level": self.risk_level.value,
            "required_autonomy_level": self.required_autonomy_level.label,
            "requires_confirmation": self.requires_confirmation,
            "requires_verification": self.requires_verification or (self.expected_state is not None),
            "has_expected_state": self.expected_state is not None,
            "has_compensation": self.compensation_tool is not None,
            "max_retries": self.max_retries,
        }


@dataclass(frozen=True)
class StepExecutionResult:
    """Resultado inmutable del procesamiento atómico de un paso a través del Secure Pipeline."""

    step_id: str
    state: StepState
    success: bool
    output: Any = None
    error: str | None = None
    verification_passed: bool = True
    verification_result: Any | None = None  # WorkflowVerificationResult (Etapa 18.3)
    attempts: int = 1
    duration_ms: float = 0.0
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "state": self.state.value,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "verification_passed": self.verification_passed,
            "verification_result": self.verification_result.to_dict() if hasattr(self.verification_result, "to_dict") else None,
            "attempts": self.attempts,
            "duration_ms": round(self.duration_ms, 2),
            "completed_at": self.completed_at.isoformat(),
        }


@dataclass(frozen=True)
class WorkflowDefinition:
    """Definición declarativa completa de un Workflow multi-paso."""

    workflow_id: str
    name: str
    version: str = "1.0.0"
    owner_source: WorkflowSource = WorkflowSource.USER
    steps: tuple[WorkflowStep, ...] = field(default_factory=tuple)
    timeout_sec: float = 60.0
    stop_on_failure: bool = True
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        name: str,
        steps: list[WorkflowStep],
        workflow_id: str | None = None,
        timeout_sec: float = 60.0,
        stop_on_failure: bool = True,
        version: str = "1.0.0",
        owner_source: WorkflowSource = WorkflowSource.USER,
        description: str = "",
    ) -> "WorkflowDefinition":
        return cls(
            workflow_id=workflow_id or f"wf_{uuid.uuid4().hex[:12]}",
            name=name,
            version=version,
            owner_source=owner_source,
            steps=tuple(steps),
            timeout_sec=timeout_sec,
            stop_on_failure=stop_on_failure,
            description=description,
        )

    def get_step(self, step_id: str) -> WorkflowStep | None:
        """Obtiene un paso por su ID."""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def get_dependencies_map(self) -> dict[str, list[str]]:
        """Construye el mapa de dependencias de todos los pasos."""
        return {s.step_id: list(s.dependencies) for s in self.steps}

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "version": self.version,
            "owner_source": self.owner_source.value,
            "steps": [s.to_dict() for s in self.steps],
            "timeout_sec": self.timeout_sec,
            "stop_on_failure": self.stop_on_failure,
            "description": self.description,
        }


@dataclass(frozen=True)
class WorkflowExecutionResult:
    """Resultado global consolidado tras la ejecución de un Workflow."""

    workflow_id: str
    state: WorkflowState
    success: bool
    completed_steps: tuple[str, ...]
    failed_step_id: str | None = None
    step_results: dict[str, StepExecutionResult] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: str | None = None
    executed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "state": self.state.value,
            "success": self.success,
            "completed_steps": list(self.completed_steps),
            "failed_step_id": self.failed_step_id,
            "step_results": {k: v.to_dict() for k, v in self.step_results.items()},
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
            "executed_at": self.executed_at.isoformat(),
        }


@dataclass(frozen=True)
class WorkflowStateSnapshot:
    """Instantánea persistible del estado de un workflow (Etapa 18.2).

    Almacena ÚNICAMENTE la información esencial:
      - workflow_id, current_step_id, status
      - completed_steps, failure_reason
      - risk_level, requires_user_review
      - timestamps (creación, actualización)
      - metadatos sanitizados (sin contraseñas ni secretos)
    """

    workflow_id: str
    name: str
    status: WorkflowState
    risk_level: TaskActionRisk
    current_step_id: str | None = None
    completed_steps: tuple[str, ...] = field(default_factory=tuple)
    step_results_summary: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None
    requires_user_review: bool = False
    auto_resume_allowed: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "status": self.status.value,
            "risk_level": self.risk_level.value,
            "current_step_id": self.current_step_id,
            "completed_steps": list(self.completed_steps),
            "step_results_summary": self.step_results_summary,
            "failure_reason": self.failure_reason,
            "requires_user_review": self.requires_user_review,
            "auto_resume_allowed": self.auto_resume_allowed,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowStateSnapshot":
        def _parse_ts(ts_val: Any) -> datetime:
            if isinstance(ts_val, str):
                return datetime.fromisoformat(ts_val)
            elif isinstance(ts_val, datetime):
                return ts_val
            return datetime.now(UTC)

        return cls(
            workflow_id=str(data["workflow_id"]),
            name=str(data.get("name", "Workflow")),
            status=WorkflowState(data["status"]),
            risk_level=TaskActionRisk(data.get("risk_level", TaskActionRisk.LOW_RISK.value)),
            current_step_id=data.get("current_step_id"),
            completed_steps=tuple(data.get("completed_steps", ())),
            step_results_summary=dict(data.get("step_results_summary", {})),
            failure_reason=data.get("failure_reason"),
            requires_user_review=bool(data.get("requires_user_review", False)),
            auto_resume_allowed=bool(data.get("auto_resume_allowed", False)),
            created_at=_parse_ts(data.get("created_at")),
            updated_at=_parse_ts(data.get("updated_at")),
        )
