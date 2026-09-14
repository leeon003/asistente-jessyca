"""Definiciones de eventos base y eventos iniciales para JESSYCA 4.0.

Estructuras de datos puras y tipadas basadas en dataclasses de Python estándar.
Sin lógica de negocio interna.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(kw_only=True)
class Event:
    """Clase base para todos los eventos del sistema JESSYCA 4.0.

    Atributos:
        event_id: Identificador único universal del evento (UUIDv4).
        timestamp: Fecha y hora en formato UTC en que se generó el evento.
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def event_type(self) -> str:
        """Devuelve el nombre canónico del tipo de evento."""
        return self.__class__.__name__


@dataclass(kw_only=True)
class WakeWordDetected(Event):
    """Notifica la detección de una palabra clave de activación (Wake Word)."""

    wake_word: str = "jessyca"
    confidence: float = 1.0
    detected_at: datetime | None = None


@dataclass(kw_only=True)
class AudioCaptured(Event):
    """Representa un bloque o segmento de audio capturado por el frontend de audio."""

    audio_data: bytes = b""
    sample_rate: int = 16000
    channels: int = 1
    duration_ms: int = 0


@dataclass(kw_only=True)
class UtteranceFinal(Event):
    """Representa la transcripción final reconocida por el subsistema STT."""

    text: str = ""
    confidence: float = 1.0
    language: str = "es"
    is_final: bool = True
    session_id: str | None = None
    action_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)



@dataclass(kw_only=True)
class IntentClassified(Event):
    """Representa la clasificación semántica de una intención del usuario."""

    intent: str = ""
    confidence: float = 1.0
    slots: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    session_id: str | None = None
    action_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class ActionProposed(Event):
    """Propuesta de ejecución de una acción o tool antes de su autorización/validación."""

    action_name: str = ""
    action_id: str = field(default_factory=lambda: f"act-{uuid.uuid4().hex[:8]}")
    parameters: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class ActionExecuted(Event):
    """Resultado de la ejecución de una acción o tool en el sistema."""

    action_name: str = ""
    success: bool = True
    result: Any = None
    error: str | None = None


@dataclass(kw_only=True)
class VerificationResult(Event):
    """Resultado formal de la verificación de una acción ejecutada."""

    action_name: str = ""
    verified: bool = True
    status: str = "VERIFIED"  # "VERIFIED", "FAILED", "NOT_VERIFIABLE"
    intent: str = ""
    session_id: str | None = None
    confidence: float = 1.0
    evidence: dict[str, Any] = field(default_factory=dict)
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class SpeakRequested(Event):
    """Solicitud para emitir una respuesta sintetizada mediante el subsistema TTS."""

    text: str = ""
    priority: int = 50
    voice: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class UserInterrupted(Event):
    """Notifica que el usuario interrumpió la locución o acción en curso (Barge-in)."""

    reason: str = "barge_in"
    interrupted_action: str | None = None
    session_id: str | None = None


@dataclass(kw_only=True)
class ClarificationRequested(Event):
    """Solicita aclaración o confirmación adicional al usuario ante ambigüedades."""

    question: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    original_text: str = ""
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class ErrorOccurred(Event):
    """Registra una condición de error ocurrida dentro de cualquier subsistema."""

    error_message: str = ""
    error_type: str = "GeneralError"
    details: dict[str, Any] = field(default_factory=dict)
    traceback: str | None = None
    session_id: str | None = None
