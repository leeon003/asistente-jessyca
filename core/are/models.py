"""Modelos formales de datos y contratos para ARE Runtime Binding en JESSYCA PC.

Define las estructuras canónicas para propuestas de descomposición (DAG),
validación de planes, diagnóstico reflexivo de fallos y replanificación bajo
estricta subordinación a la autoridad de JDE.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ARERuntimeMode(StrEnum):
    """Modos operativos canónicos para ARE Runtime."""

    DISABLED = "DISABLED"      # ARE desactivado; el sistema recurre al planificador nativo lineal
    SHADOW = "SHADOW"          # ARE observa, descompone y registra propuestas sin alterar el flujo físico
    CONTROLLED = "CONTROLLED"  # ARE activo para tareas complejas; toda propuesta subordinada a JDE
    ACTIVE = "ACTIVE"          # Prohibido en esta fase (protección estricta de seguridad)


class AREStepProposal(BaseModel):
    """Propuesta atómica de un paso dentro del grafo de tareas generado por ARE."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    step_id: str
    title: str = ""
    action_type: str = ""
    action: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    risk_level: str = "SAFE"
    is_critical: bool = True
    status: str = "PENDING"
    retry_count: int = 0

    def model_post_init(self, __context: Any) -> None:
        # Normalizar action/action_type
        act = self.action or self.action_type
        if not self.title:
            object.__setattr__(self, "title", self.step_id)
        if not self.action_type and act:
            object.__setattr__(self, "action_type", act)
        if not self.action and act:
            object.__setattr__(self, "action", act)
        # Normalizar depends_on / dependencies
        deps = list(self.depends_on or self.dependencies or [])
        object.__setattr__(self, "depends_on", deps)
        object.__setattr__(self, "dependencies", deps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "action_type": self.action_type or self.action,
            "parameters": self.parameters,
            "depends_on": self.depends_on,
            "required_capabilities": self.required_capabilities,
            "risk_level": self.risk_level,
            "is_critical": self.is_critical,
            "status": self.status,
            "retry_count": self.retry_count,
        }


class AREPlanProposal(BaseModel):
    """Propuesta formal de plan de ejecución estructurado (DAG) emitida por ARE."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    task_id: str = ""
    plan_id: str = ""
    goal: str = "Plan proposal"
    steps: list[AREStepProposal] = Field(default_factory=list)
    execution_order: list[str] = Field(default_factory=list)
    dependencies: dict[str, list[str]] = Field(default_factory=dict)
    required_capabilities: list[str] = Field(default_factory=list)
    risk_context: dict[str, Any] = Field(default_factory=dict)
    recovery_strategy: str | None = None
    confidence: float = 0.95
    provenance: str = "ARE.TaskDecomposer"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    integrity_hash: str = ""
    is_evaluated: bool = False
    is_valid: bool = True
    evaluation_errors: list[str] = Field(default_factory=list)

    @classmethod
    def compute_integrity_hash(
        cls,
        task_id: str,
        plan_id: str,
        goal: str,
        execution_order: list[str],
        steps: list[AREStepProposal],
    ) -> str:
        """Calcula el hash criptográfico SHA-256 de integridad para la propuesta de plan."""
        canonical_repr = {
            "task_id": task_id,
            "plan_id": plan_id,
            "goal": goal,
            "execution_order": execution_order,
            "steps": [s.to_dict() for s in steps],
        }
        encoded = json.dumps(canonical_repr, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def verify_integrity(self) -> bool:
        """Verifica que el hash de integridad coincida con el contenido del plan."""
        expected = self.compute_integrity_hash(
            task_id=self.task_id,
            plan_id=self.plan_id,
            goal=self.goal,
            execution_order=self.execution_order,
            steps=self.steps,
        )
        return self.integrity_hash == expected


class AREDiagnosis(BaseModel):
    """Diagnóstico reflexivo de fallo y cálculo de radio de impacto emitido por ARE."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    failed_step_id: str = ""
    failure_step_id: str = ""
    root_cause: str = ""
    is_critical: bool = True
    recoverable: bool = True
    blocked_steps: list[str] = Field(default_factory=list)
    independent_steps: list[str] = Field(default_factory=list)
    raw_error: str = ""
    confidence: float = 0.95

    def model_post_init(self, __context: Any) -> None:
        fid = self.failure_step_id or self.failed_step_id
        if not self.failure_step_id and fid:
            object.__setattr__(self, "failure_step_id", fid)
        if not self.failed_step_id and fid:
            object.__setattr__(self, "failed_step_id", fid)


class ARERecoveryProposal(BaseModel):
    """Propuesta de contingencia y recuperación sintetizada por ARE ante un fallo."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    task_id: str = ""
    plan_id: str = ""
    failed_step_id: str = ""
    recommended_action: str = "ASK_USER"  # SKIP, RETRY, ASK_USER, ALTERNATIVE_BRANCH, ABORT
    rationale: str = ""
    reason: str = ""
    recovery_steps: list[dict[str, Any]] = Field(default_factory=list)
    attempt_number: int = 1
    max_attempts: int = 2
    integrity_hash: str = ""

    def model_post_init(self, __context: Any) -> None:
        rat = self.rationale or self.reason
        if not self.rationale and rat:
            object.__setattr__(self, "rationale", rat)
        if not self.reason and rat:
            object.__setattr__(self, "reason", rat)

    @classmethod
    def compute_integrity_hash(
        cls,
        task_id: str,
        plan_id: str,
        failed_step_id: str,
        recommended_action: str,
        attempt_number: int,
    ) -> str:
        canonical_repr = {
            "task_id": task_id,
            "plan_id": plan_id,
            "failed_step_id": failed_step_id,
            "recommended_action": recommended_action,
            "attempt_number": attempt_number,
        }
        encoded = json.dumps(canonical_repr, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
