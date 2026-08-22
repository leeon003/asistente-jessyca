"""Modelos de Datos para Propuestas de Aprendizaje (proposal_models.py - Fase 59).

Define las estructuras fuertemente tipadas en Pydantic v2 para:
- Estados y ciclo de vida de propuestas (ProposalStatus).
- Categorías funcionales de mejora (ProposalCategory).
- Niveles de riesgo técnico (ProposalRiskLevel).
- Propuestas estructuradas inmutables de aprendizaje (LearningProposal).
- Resultados de simulación de verificación (SimulationResult).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProposalStatus(StrEnum):
    """Estados formales del ciclo de vida de una propuesta de aprendizaje."""

    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    SIMULATION_PENDING = "SIMULATION_PENDING"
    READY_FOR_EVALUATION = "READY_FOR_EVALUATION"
    APPROVED = "APPROVED"
    DEPLOYED = "DEPLOYED"
    REJECTED = "REJECTED"
    SIMULATION_FAILED = "SIMULATION_FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    EXPIRED = "EXPIRED"


class ProposalCategory(StrEnum):
    """Categorías funcionales donde se proponen mejoras."""

    STT = "STT"
    INTENT = "INTENT"
    CLARIFICATION = "CLARIFICATION"
    TOOL = "TOOL"
    BROWSER = "BROWSER"
    DESKTOP = "DESKTOP"
    PERFORMANCE = "PERFORMANCE"
    MEMORY = "MEMORY"
    PERSONALIZATION = "PERSONALIZATION"
    UX = "UX"


class ProposalRiskLevel(StrEnum):
    """Nivel de riesgo estimado para la propuesta."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class LearningProposal(BaseModel):
    """Entidad inmutable representativa de una propuesta formal de aprendizaje."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    proposal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_analysis_ids: list[str] = Field(default_factory=list)
    source_pattern_ids: list[str] = Field(default_factory=list)
    category: ProposalCategory = ProposalCategory.UX
    problem: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    occurrences: int = 1
    current_behavior: str = ""
    suggested_improvement: str = ""
    expected_benefit: str = ""
    risk: ProposalRiskLevel = ProposalRiskLevel.LOW
    confidence: float = 1.0
    affected_components: list[str] = Field(default_factory=list)
    required_tests: list[str] = Field(default_factory=list)
    potential_breakage: list[str] = Field(default_factory=list)
    status: ProposalStatus = ProposalStatus.DRAFT
    version: str = "1.0.0"
    created_by: str = "LearningProposalEngine@3.0"
    rejection_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serializa la propuesta en un diccionario JSON."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearningProposal:
        """Reconstruye una propuesta a partir de un diccionario."""
        return cls.model_validate(data)


class SimulationResult(BaseModel):
    """Resultado determinista de una simulación de propuesta en entorno controlado."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    passed: bool = True
    failed: bool = False
    tests_run: int = 0
    regressions: list[str] = Field(default_factory=list)
    metrics_before: dict[str, float] = Field(default_factory=dict)
    metrics_after: dict[str, float] = Field(default_factory=dict)
    notes: str = ""
