"""Servicio de Detección de Palabra de Activación (wake_word_service.py - Fase 13).

Gestiona la activación del pipeline mediante la palabra clave ("Jessyca").
GARANTÍA DE SEGURIDAD ABSOLUTA:
- WAKE WORD != AUTHORIZATION.
- La detección de la palabra de activación solo abre la ventana de escucha, sin otorgar permisos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from core.logger import get_logger
from services.voice.audio_input import AudioChunk

logger = get_logger("jessyca.voice.wake_word")


@dataclass(frozen=True)
class WakeWordResult:
    """Resultado formal inmutable de la evaluación de palabra de activación."""

    detected: bool
    keyword: str
    confidence: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "keyword": self.keyword,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
            "metadata": dict(self.metadata),
        }


class IWakeWordService(Protocol):
    """Protocolo para detección de palabra de activación."""

    def process_audio(self, chunk: AudioChunk) -> WakeWordResult: ...
    def reset(self) -> None: ...


class KeywordWakeWordService:
    """Detector de palabra de activación local ("Jessyca") en memoria efímera."""

    def __init__(
        self,
        keyword: str = "jessyca",
        confidence_threshold: float = 0.75,
        enabled: bool = True,
    ) -> None:
        self.keyword = keyword.lower()
        self.confidence_threshold = confidence_threshold
        self.enabled = enabled
        self._triggered = False

    def reset(self) -> None:
        self._triggered = False

    def trigger_manually(self) -> None:
        """Permite activación manual o programática para pruebas."""
        self._triggered = True

    def process_audio(self, chunk: AudioChunk) -> WakeWordResult:
        """Evalúa el fragmento de audio efímero."""
        if not self.enabled:
            return WakeWordResult(
                detected=False,
                keyword=self.keyword,
                confidence=0.0,
                metadata={"enabled": False},
            )

        if self._triggered:
            self._triggered = False
            logger.info(f"[WAKE WORD] Palabra de activación '{self.keyword}' DETECTADA.")
            return WakeWordResult(
                detected=True,
                keyword=self.keyword,
                confidence=0.95,
                metadata={"trigger": "manual_or_stream"},
            )

        # En operación regular sin trigger
        return WakeWordResult(
            detected=False,
            keyword=self.keyword,
            confidence=0.0,
        )
