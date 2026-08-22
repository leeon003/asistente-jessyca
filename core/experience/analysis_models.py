"""Modelos de Datos para el Análisis de Experiencias (analysis_models.py - Fase 58).

Define las estructuras inmutables fuertemente tipadas en Pydantic v2 para:
- Definición de ventanas de análisis temporal y por volumen (AnalysisWindow).
- Clasificación y representación de patrones detectados (Pattern, STTPattern, FailurePattern, etc.).
- Métricas agregadas y percentiles de rendimiento (ExperienceMetrics).
- Resultado global y auditable del análisis (ExperienceAnalysis).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PatternType(StrEnum):
    """Tipos formales de patrones detectados en el historial de experiencias."""

    REPEATED_FAILURE = "REPEATED_FAILURE"
    REPEATED_SUCCESS = "REPEATED_SUCCESS"
    LOW_STT_CONFIDENCE = "LOW_STT_CONFIDENCE"
    LOW_INTENT_CONFIDENCE = "LOW_INTENT_CONFIDENCE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    REPEATED_CLARIFICATION = "REPEATED_CLARIFICATION"
    USER_CORRECTION = "USER_CORRECTION"
    LATENCY_DEGRADATION = "LATENCY_DEGRADATION"
    REPEATED_ACTION = "REPEATED_ACTION"
    TOOL_SKILL_FAILURE = "TOOL_SKILL_FAILURE"
    STT_RECOGNITION = "STT_RECOGNITION"
    GENERAL = "GENERAL"


class PatternSeverity(StrEnum):
    """Nivel de severidad o prioridad del patrón detectado."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AnalysisWindow(BaseModel):
    """Delimita el rango de análisis para evitar procesar el historial indiscriminadamente."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    limit: int | None = None
    hours: float | None = None
    days: float | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    action_type: str | None = None
    skill: str | None = None
    intent: str | None = None


class Pattern(BaseModel):
    """Representación estructurada de un patrón empírico detectado con evidencia."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    pattern_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: PatternType
    description: str
    frequency: int = 1
    confidence: float = 1.0
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    first_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    affected_operations: list[str] = Field(default_factory=list)
    severity: PatternSeverity = PatternSeverity.INFO
    metadata: dict[str, Any] = Field(default_factory=dict)


class FailurePattern(Pattern):
    """Patrón de fallo recurrente o sistemático."""

    failure_rate: float = 0.0
    error_types: list[str] = Field(default_factory=list)


class SuccessPattern(Pattern):
    """Patrón de éxito consistente y repetido."""

    success_rate: float = 1.0


class STTPattern(Pattern):
    """Patrón de transcripción, baja confianza o variantes de reconocimiento STT."""

    canonical_target: str | None = None
    variants: list[str] = Field(default_factory=list)
    avg_stt_confidence: float = 0.0


class IntentPattern(Pattern):
    """Patrón de intención ambigua, no concluyente o baja confianza."""

    intent_name: str | None = None
    ambiguity_rate: float = 0.0


class LatencyPattern(Pattern):
    """Patrón de degradación o anomalía en los tiempos de respuesta."""

    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0


class CorrectionPattern(Pattern):
    """Patrón de correcciones sistemáticas realizadas por el usuario."""

    original_values: list[str] = Field(default_factory=list)
    corrected_values: list[str] = Field(default_factory=list)


class ExperienceMetrics(BaseModel):
    """Métricas cuantitativas agregadas del lote de experiencias analizadas."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    total_experiences: int = 0
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 0.0
    failure_rate: float = 0.0
    verification_success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    stt_confidence_avg: float = 0.0
    intent_confidence_avg: float = 0.0
    clarification_rate: float = 0.0
    correction_rate: float = 0.0
    repeated_failure_rate: float = 0.0


class ExperienceAnalysis(BaseModel):
    """Resultado formal inmutable y auditable del análisis de experiencias."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    analysis_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    window: AnalysisWindow = Field(default_factory=AnalysisWindow)
    metrics: ExperienceMetrics = Field(default_factory=ExperienceMetrics)
    patterns: list[Pattern] = Field(default_factory=list)
    summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serializa el análisis completo a un diccionario JSON."""
        return self.model_dump(mode="json")
