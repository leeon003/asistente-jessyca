"""Modelos de Datos para el Motor de Personalización (preference_models.py - Fase 62).

Define las estructuras fuertemente tipadas en Pydantic v2 para:
- Estados de preferencias (PreferenceStatus).
- Categorías funcionales de preferencias y aliases (PreferenceCategory).
- Fuentes de origen de la preferencia (PreferenceSource).
- Entidad inmutable UserPreference con métricas de evidencia y confianza.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PreferenceStatus(StrEnum):
    """Estados formales del ciclo de vida de una preferencia de usuario."""

    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FORGOTTEN = "FORGOTTEN"


class PreferenceCategory(StrEnum):
    """Categorías funcionales de preferencias del usuario."""

    COMMAND_ALIAS = "COMMAND_ALIAS"
    APPLICATION_PREFERENCE = "APPLICATION_PREFERENCE"
    BROWSER_PREFERENCE = "BROWSER_PREFERENCE"
    RESPONSE_STYLE = "RESPONSE_STYLE"
    CLARIFICATION_PREFERENCE = "CLARIFICATION_PREFERENCE"
    WORKFLOW_PREFERENCE = "WORKFLOW_PREFERENCE"
    LANGUAGE_PREFERENCE = "LANGUAGE_PREFERENCE"
    TIMING_PREFERENCE = "TIMING_PREFERENCE"


class PreferenceSource(StrEnum):
    """Origen de detección de la preferencia."""

    INFERRED = "INFERRED"
    USER_EXPLICIT = "USER_EXPLICIT"
    EXPERIENCE_ANALYSIS = "EXPERIENCE_ANALYSIS"


class UserPreference(BaseModel):
    """Entidad inmutable que representa un patrón o preferencia aprendida del usuario."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    preference_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: PreferenceCategory = PreferenceCategory.COMMAND_ALIAS
    key: str
    value: Any
    confidence: float = 0.35
    evidence_count: int = 1
    contradiction_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_confirmed: datetime | None = None
    last_observed: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: PreferenceSource = PreferenceSource.INFERRED
    status: PreferenceStatus = PreferenceStatus.CANDIDATE
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serializa la preferencia en un diccionario JSON."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserPreference:
        """Reconstruye una preferencia a partir de un diccionario."""
        return cls.model_validate(data)
