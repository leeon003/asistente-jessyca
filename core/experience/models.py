"""Modelos de Dominio de Experiencias de Interacción (models.py - Fase 57).

Define las estructuras de datos fuertemente tipadas basadas en Pydantic v2
para representar experiencias de usuario, comportamiento y rendimiento
del Asistente JESSYCA.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InputSource(StrEnum):
    """Origen formal del estímulo o entrada del usuario."""

    TEXT = "text"
    VOICE = "voice"
    WAKE_WORD = "wake_word"
    SYSTEM = "system"
    SCHEDULED = "scheduled"
    OTHER = "other"


class ExecutionStatus(StrEnum):
    """Estado formal del resultado de la acción ejecutada."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    BLOCKED = "BLOCKED"
    NOT_EXECUTED = "NOT_EXECUTED"
    UNKNOWN = "UNKNOWN"


class VerificationStatus(StrEnum):
    """Estado formal de la verificación en el sistema operativo."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    NOT_PERFORMED = "NOT_PERFORMED"
    UNKNOWN = "UNKNOWN"


class ExperienceCategory(StrEnum):
    """Categorías funcionales de experiencias para clasificación y análisis posterior."""

    ACTION_SUCCESS = "ACTION_SUCCESS"
    ACTION_FAILED = "ACTION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    LOW_STT_CONFIDENCE = "LOW_STT_CONFIDENCE"
    AMBIGUOUS_INTENT = "AMBIGUOUS_INTENT"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    USER_CORRECTION = "USER_CORRECTION"
    TIMEOUT = "TIMEOUT"
    ACTION_BLOCKED = "ACTION_BLOCKED"
    CANCELLED = "CANCELLED"
    GENERAL = "GENERAL"


class ExperienceInput(BaseModel):
    """Representación de la entrada cruda y normalizada recibida."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    source: InputSource = InputSource.TEXT
    raw_text: str
    normalized_text: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class STTResult(BaseModel):
    """Metadatos del reconocimiento de voz y calidad de transcripción."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    text: str
    confidence: float = 1.0
    is_low_confidence: bool = False
    audio_duration_ms: float | None = None


class IntentResult(BaseModel):
    """Intención identificada por el motor conversacional."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    confidence: float = 1.0
    is_ambiguous: bool = False
    raw_intent: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class TargetInfo(BaseModel):
    """Entidad o recurso destino sobre el que opera la acción."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    target_type: str = "general"
    value: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    """Resultado formal de la ejecución técnica de la orden."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    status: ExecutionStatus = ExecutionStatus.UNKNOWN
    tool_name: str | None = None
    action: str | None = None
    duration_ms: float = 0.0
    output_summary: str | None = None
    output_data: dict[str, Any] | None = None


class VerificationResult(BaseModel):
    """Resultado determinista de la verificación en el sistema operativo."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    status: VerificationStatus = VerificationStatus.NOT_PERFORMED
    verification_type: str | None = None
    is_verified: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ResponseResult(BaseModel):
    """Respuesta generada para el usuario final."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    text: str
    spoken_text: str | None = None
    modality: str = "text"


class LatencyInfo(BaseModel):
    """Desglose detallado de tiempos de latencia del turno."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    total_ms: float = 0.0
    stt_ms: float = 0.0
    intent_ms: float = 0.0
    planning_ms: float = 0.0
    execution_ms: float = 0.0
    verification_ms: float = 0.0
    tts_ms: float = 0.0


class ErrorInfo(BaseModel):
    """Información estructurada de errores técnicos o de validación."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    error_type: str
    error_code: str | None = None
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class CorrectionInfo(BaseModel):
    """Información de correcciones de usuario sobre turnos previos."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    is_correction: bool = False
    previous_experience_id: str | None = None
    original_target: str | None = None
    corrected_target: str | None = None
    correction_type: str | None = None


class ExperienceMetadata(BaseModel):
    """Metadatos de contexto de ejecución del agente y entorno."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    version: str = "3.0.0"
    model_used: str | None = None
    agent_used: str | None = None
    skill_used: str | None = None
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class Experience(BaseModel):
    """Entidad principal inmutable representativa de una experiencia de interacción."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    experience_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    category: ExperienceCategory = ExperienceCategory.GENERAL
    session_id: str | None = None
    correlation_id: str | None = None
    input: ExperienceInput
    stt: STTResult | None = None
    intent: IntentResult | None = None
    target: TargetInfo | None = None
    execution: ExecutionResult | None = None
    verification: VerificationResult | None = None
    response: ResponseResult | None = None
    latency: LatencyInfo = Field(default_factory=LatencyInfo)
    error: ErrorInfo | None = None
    correction: CorrectionInfo | None = None
    metadata: ExperienceMetadata = Field(default_factory=ExperienceMetadata)

    def to_dict(self) -> dict[str, Any]:
        """Serializa la experiencia en diccionario compatible con JSON."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Experience:
        """Instancia una experiencia a partir de un diccionario."""
        return cls.model_validate(data)
