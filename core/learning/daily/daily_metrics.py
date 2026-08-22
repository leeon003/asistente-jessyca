"""Métricas y Estados de Ejecución del Ciclo Diario (daily_metrics.py - Fase 63).

Define las estructuras fuertemente tipadas en Pydantic v2 para:
- Estados formales del ciclo de vida de ejecución (DailyRunStatus).
- Modelo de seguimiento y trazabilidad de la corrida diaria (DailyLearningRun).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DailyRunStatus(StrEnum):
    """Estados del ciclo de vida de una ejecución diaria de aprendizaje."""

    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    ANALYZING = "ANALYZING"
    PROPOSING = "PROPOSING"
    TESTING = "TESTING"
    EVALUATING = "EVALUATING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    DEPLOYING = "DEPLOYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class DailyLearningRun(BaseModel):
    """Registro inmutable de trazabilidad de una ejecución del ciclo diario."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    date_iso: str
    status: DailyRunStatus = DailyRunStatus.SCHEDULED
    start_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    end_time: datetime | None = None
    current_step: str = "INITIALIZED"
    errors: list[str] = Field(default_factory=list)
    circuit_breaker_triggered: bool = False
    circuit_breaker_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serializa la ejecución a diccionario JSON."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DailyLearningRun:
        """Reconstruye una ejecución a partir de un diccionario."""
        return cls.model_validate(data)
