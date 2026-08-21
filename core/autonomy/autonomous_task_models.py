"""Modelos formales de datos para tareas autónomas persistentes (autonomous_task_models.py - Fase 15).

Define el ciclo de vida, estados y presupuestos para la ejecución de tareas programadas multi-step.
INVARIANTE DE SEGURIDAD ABSOLUTA:
- Task != Authorization / Scheduler != Authorization.
- Ninguna tarea programada puede auto-concederse permisos ni evadir la AutonomyPolicy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.autonomy.autonomy_level import TaskActionRisk
from core.control_plane.models import AgentBudget


class AutonomousTaskStatus(StrEnum):
    """Estados del ciclo de vida formal de una tarea autónoma."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class AutonomousTaskDefinition:
    """Definición inmutable y serializable de una tarea autónoma persistente."""

    task_id: str
    owner: str
    schedule: str  # Cron o Interval (ej. "cron:0 9 * * *", "interval:86400")
    agent_id: str
    intent: str
    allowed_tools: tuple[str, ...]
    budget: AgentBudget
    max_steps: int
    max_time_seconds: float
    risk_ceiling: TaskActionRisk
    status: AutonomousTaskStatus = AutonomousTaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_run_at: datetime | None = None
    last_error: str | None = None
    execution_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_status(
        self,
        new_status: AutonomousTaskStatus,
        error: str | None = None,
        last_run_at: datetime | None = None,
    ) -> AutonomousTaskDefinition:
        """Retorna una copia inmutable con el estado actualizado."""
        now = datetime.now(UTC)
        new_exec_count = self.execution_count + 1 if new_status == AutonomousTaskStatus.RUNNING else self.execution_count
        return AutonomousTaskDefinition(
            task_id=self.task_id,
            owner=self.owner,
            schedule=self.schedule,
            agent_id=self.agent_id,
            intent=self.intent,
            allowed_tools=self.allowed_tools,
            budget=self.budget,
            max_steps=self.max_steps,
            max_time_seconds=self.max_time_seconds,
            risk_ceiling=self.risk_ceiling,
            status=new_status,
            created_at=self.created_at,
            updated_at=now,
            last_run_at=last_run_at or self.last_run_at or (now if new_status == AutonomousTaskStatus.RUNNING else None),
            last_error=error if error is not None else self.last_error,
            execution_count=new_exec_count,
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa la tarea a un diccionario estructurado."""
        return {
            "task_id": self.task_id,
            "owner": self.owner,
            "schedule": self.schedule,
            "agent_id": self.agent_id,
            "intent": self.intent,
            "allowed_tools": list(self.allowed_tools),
            "max_steps": self.max_steps,
            "max_time_seconds": self.max_time_seconds,
            "risk_ceiling": str(self.risk_ceiling),
            "status": str(self.status),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_error": self.last_error,
            "execution_count": self.execution_count,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AutonomousTaskDefinition:
        """Reconstruye una tarea autónoma desde un diccionario persistido."""
        risk_str = str(data.get("risk_ceiling", "MEDIUM_RISK"))
        try:
            risk = TaskActionRisk(risk_str.upper())
        except ValueError:
            risk = TaskActionRisk.MEDIUM_RISK

        budget = AgentBudget.create(
            max_steps=data.get("max_steps", 10),
            max_time=data.get("max_time_seconds", 30.0),
            max_actions=data.get("max_steps", 10),
            max_risk=risk,
        )

        status_str = data.get("status", "PENDING")
        try:
            status = AutonomousTaskStatus(status_str)
        except ValueError:
            status = AutonomousTaskStatus.PENDING

        created_str = data.get("created_at")
        created_at = datetime.fromisoformat(created_str) if created_str else datetime.now(UTC)

        updated_str = data.get("updated_at")
        updated_at = datetime.fromisoformat(updated_str) if updated_str else datetime.now(UTC)

        last_run_str = data.get("last_run_at")
        last_run_at = datetime.fromisoformat(last_run_str) if last_run_str else None

        return cls(
            task_id=data["task_id"],
            owner=data.get("owner", "user"),
            schedule=data.get("schedule", "interval:86400"),
            agent_id=data.get("agent_id", "agent_system"),
            intent=data.get("intent", ""),
            allowed_tools=tuple(data.get("allowed_tools", [])),
            budget=budget,
            max_steps=data.get("max_steps", 10),
            max_time_seconds=data.get("max_time_seconds", 30.0),
            risk_ceiling=risk,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            last_run_at=last_run_at,
            last_error=data.get("last_error"),
            execution_count=data.get("execution_count", 0),
            metadata=dict(data.get("metadata", {})),
        )
