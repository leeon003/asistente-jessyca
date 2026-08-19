"""Definición inmutable de Decisión de Autonomía (AutonomyDecision - Subetapa 16.2).

Representa el resultado formal determinista emitido por la AutonomyPolicy / AutonomyGovernor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk


class AutonomyDecisionValue(StrEnum):
    """Valores formales permitidos para una decisión de autonomía."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    REQUIRE_REVIEW = "REQUIRE_REVIEW"
    STOP = "STOP"


@dataclass(frozen=True)
class AutonomyDecision:
    """Decisión inmutable emitida por la política de autonomía.

    INVARIANTE DE SEGURIDAD:
    Toda decisión es inmutable y captura de forma explícita el contexto de auditoría
    (capability, risk, permission, level, task_source, workflow_context, scheduler_context, plugin_context).
    """

    decision: AutonomyDecisionValue
    autonomy_level: AutonomyLevel
    risk_level: TaskActionRisk
    allowed: bool
    requires_confirmation: bool
    reason: str
    task_id: str = "default_task"
    tool_name: str = "unknown"
    operation: str = "unknown"
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_allowed_without_confirmation(self) -> bool:
        """Determina si la acción puede ser ejecutada autónomamente de inmediato."""
        return self.decision == AutonomyDecisionValue.ALLOW and self.allowed and not self.requires_confirmation

    def to_dict(self) -> dict[str, Any]:
        """Convierte la decisión a un diccionario serializable para auditoría."""
        return {
            "decision": str(self.decision),
            "autonomy_level": self.autonomy_level.label,
            "risk_level": str(self.risk_level),
            "allowed": self.allowed,
            "requires_confirmation": self.requires_confirmation,
            "reason": self.reason,
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "evaluated_at": self.evaluated_at.isoformat(),
            "metadata": self.metadata,
        }
