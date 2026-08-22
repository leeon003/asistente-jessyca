"""Modelos de Datos para Casos de Prueba de Regresión (regression_models.py - Fase 61).

Define las estructuras fuertemente tipadas en Pydantic v2 para:
- Estados del ciclo de vida de casos de regresión (RegressionStatus).
- Categorías funcionales de regresión (RegressionCategory).
- Severidad de la regresión (RegressionSeverity).
- Entidad inmutable RegressionCase con firma de fallo y trazabilidad a la experiencia origen.
- Estadísticas dinámicas de la suite de regresión (RegressionSuiteStats).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RegressionStatus(StrEnum):
    """Estados del ciclo de vida de un caso de prueba de regresión."""

    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    RETIRED = "RETIRED"


class RegressionCategory(StrEnum):
    """Categorías funcionales donde opera el test de regresión."""

    STT = "STT"
    INTENT = "INTENT"
    CLARIFICATION = "CLARIFICATION"
    TOOL = "TOOL"
    BROWSER = "BROWSER"
    DESKTOP = "DESKTOP"
    MEMORY = "MEMORY"
    PERFORMANCE = "PERFORMANCE"


class RegressionSeverity(StrEnum):
    """Nivel de severidad asignado a la regresión."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RegressionCase(BaseModel):
    """Caso de prueba de regresión determinista generado a partir de fallos o correcciones."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    case_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_experience_id: str | None = None
    source_proposal_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    category: RegressionCategory = RegressionCategory.INTENT
    description: str
    input_text: str
    expected_behavior: dict[str, Any] = Field(default_factory=dict)
    failure_signature: str
    test_reference: str
    test_code_snippet: str | None = None
    status: RegressionStatus = RegressionStatus.CANDIDATE
    severity: RegressionSeverity = RegressionSeverity.MEDIUM
    requires_real_windows: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serializa el caso de regresión a un diccionario JSON."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegressionCase:
        """Reconstruye un caso de regresión a partir de un diccionario."""
        return cls.model_validate(data)


class RegressionSuiteStats(BaseModel):
    """Estadísticas dinámicas y agregadas de la suite de pruebas de regresión."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    initial_tests: int = 0
    generated_tests: int = 0
    active_regressions: int = 0
    disabled_regressions: int = 0
    retired_regressions: int = 0
    total_tests: int = 0
