"""Voice Activity Detection Service con Histeresis y Umbrales Adaptativos (vad_service.py - Fases 13 & 51.1).

Detecta inicio de habla (speech_start), continuación (speech_continue), fin de habla (speech_end),
silencio y timeout mediante análisis RMS con histeresis (start_threshold > end_threshold)
para evitar truncamientos prematuros y rechazar falsos positivos por ruido ambiental.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from core.logger import get_logger
from services.voice.audio_input import AudioChunk

logger = get_logger("jessyca.voice.vad")


class VADEvent(StrEnum):
    """Eventos de actividad de voz detectados."""

    SPEECH_START = "SPEECH_START"
    SPEECH_CONTINUE = "SPEECH_CONTINUE"
    SPEECH_END = "SPEECH_END"
    SILENCE = "SILENCE"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class VADResult:
    """Resultado formal inmutable de una evaluación de VAD."""

    event: VADEvent
    is_speech: bool
    confidence: float
    energy: float
    duration_ms: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": str(self.event),
            "is_speech": self.is_speech,
            "confidence": self.confidence,
            "energy": self.energy,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
        }


class IVADService(Protocol):
    """Protocolo abstracto para servicios de detección de actividad de voz."""

    def process_chunk(self, chunk: AudioChunk) -> VADResult: ...
    def reset(self) -> None: ...


class EnergyVADService:
    """Detector de Actividad de Voz basado en análisis de energía RMS con histeresis y End-of-Speech adaptativo."""

    def __init__(
        self,
        energy_threshold: float = 300.0,
        start_threshold: float | None = None,
        end_threshold: float | None = None,
        speech_pad_chunks: int = 2,
        silence_timeout_seconds: float = 3.0,
        silence_end_seconds: float = 1.0,
        silence_end_short_seconds: float | None = None,
        silence_end_extended_seconds: float = 1.35,
        pause_tolerance_seconds: float = 1.2,
        adaptive_eos_enabled: bool = True,
        max_speech_duration_seconds: float = 300.0,
    ) -> None:
        self.energy_threshold = energy_threshold
        self.start_threshold = start_threshold if start_threshold is not None else energy_threshold
        self.end_threshold = end_threshold if end_threshold is not None else (self.start_threshold * 0.65)
        self.speech_pad_chunks = speech_pad_chunks
        self.silence_timeout_seconds = silence_timeout_seconds
        self.silence_end_seconds = silence_end_seconds
        self.silence_end_short_seconds = (
            silence_end_short_seconds
            if silence_end_short_seconds is not None
            else silence_end_seconds
        )
        self.silence_end_extended_seconds = (
            silence_end_extended_seconds
            if silence_end_extended_seconds is not None
            else max(self.silence_end_short_seconds, 1.35)
        )
        self.pause_tolerance_seconds = pause_tolerance_seconds
        self.adaptive_eos_enabled = adaptive_eos_enabled
        # Watchdog técnico contra micrófono o buffer atascado (5 min). NO es el fin normal de habla.
        self.max_speech_duration_seconds = max_speech_duration_seconds

        self._in_speech = False
        self._consecutive_speech_chunks = 0
        self._consecutive_silence_chunks = 0
        self._speech_duration_seconds = 0.0
        self._silence_duration_seconds = 0.0

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def reset(self) -> None:
        """Reinicia el estado interno del detector VAD."""
        self._in_speech = False
        self._consecutive_speech_chunks = 0
        self._consecutive_silence_chunks = 0
        self._speech_duration_seconds = 0.0
        self._silence_duration_seconds = 0.0

    def get_adaptive_silence_threshold(self) -> float:
        """Calcula el umbral de silencio adaptativo necesario para determinar fin de habla.

        Distingue:
        1. Comandos cortos (< 1.2s de habla activa): umbral de 1.0s para respuesta ágil.
        2. Preguntas conversacionales o complejas (>= 1.2s): umbral de 1.35s tolerando pausas
           naturales de pensamiento sin cortar la intervención.
        """
        if not self.adaptive_eos_enabled:
            return self.silence_end_seconds
        if self._speech_duration_seconds < 1.2:
            return self.silence_end_short_seconds
        return self.silence_end_extended_seconds

    def update_thresholds(self, start_threshold: float, end_threshold: float) -> None:
        """Actualiza dinámicamente los umbrales de histeresis tras una calibración."""
        self.start_threshold = start_threshold
        self.end_threshold = end_threshold
        self.energy_threshold = start_threshold
        logger.debug(f"[VAD] Umbrales actualizados: start={start_threshold:.1f}, end={end_threshold:.1f}")

    def process_chunk(self, chunk: AudioChunk) -> VADResult:
        """Evalúa un AudioChunk con histeresis para detectar transiciones de habla o silencio."""
        energy = chunk.energy_rms
        chunk_duration = chunk.duration_seconds

        # Aplicación de Histeresis:
        # Si NO estamos en habla -> Requiere superar start_threshold (más exigente para no disparar con ruidos breves)
        # Si YA estamos en habla -> Basta con superar end_threshold (más permisivo para no cortar pausas o finales)
        threshold_to_use = self.end_threshold if self._in_speech else self.start_threshold
        is_above_threshold = energy >= threshold_to_use

        if is_above_threshold:
            if self._in_speech and self._silence_duration_seconds >= 0.25:
                logger.info(f"[EOS] voice_resumed (tras pausa de {self._silence_duration_seconds:.2f}s)")

            self._consecutive_speech_chunks += 1
            self._consecutive_silence_chunks = 0
            self._silence_duration_seconds = 0.0
            self._speech_duration_seconds += chunk_duration

            # Failsafe Watchdog de seguridad técnica (protección contra micrófono atascado, NO fin normal de habla)
            if self._speech_duration_seconds >= self.max_speech_duration_seconds:
                self._in_speech = False
                logger.warning(
                    f"[VAD] [FAILSAFE WATCHDOG] Límite de seguridad alcanzado ({self._speech_duration_seconds:.1f}s >= "
                    f"{self.max_speech_duration_seconds:.1f}s). Protección técnica contra micrófono o VAD atascado."
                )
                return VADResult(
                    event=VADEvent.TIMEOUT,
                    is_speech=False,
                    confidence=1.0,
                    energy=energy,
                    duration_ms=self._speech_duration_seconds * 1000.0,
                )

            # Transición a SPEECH_START
            if not self._in_speech and self._consecutive_speech_chunks >= self.speech_pad_chunks:
                self._in_speech = True
                logger.info(f"[EOS] voice_started (Energía: {energy:.1f} >= {self.start_threshold:.1f})")
                return VADResult(
                    event=VADEvent.SPEECH_START,
                    is_speech=True,
                    confidence=min(1.0, energy / max(1.0, self.start_threshold * 1.5)),
                    energy=energy,
                    duration_ms=self._speech_duration_seconds * 1000.0,
                )

            if self._in_speech:
                return VADResult(
                    event=VADEvent.SPEECH_CONTINUE,
                    is_speech=True,
                    confidence=min(1.0, energy / max(1.0, self.start_threshold * 1.5)),
                    energy=energy,
                    duration_ms=self._speech_duration_seconds * 1000.0,
                )

        else:
            self._consecutive_silence_chunks += 1
            self._consecutive_speech_chunks = 0
            self._silence_duration_seconds += chunk_duration

            # Si estábamos hablando y se acumula suficiente silencio -> SPEECH_END adaptativo
            if self._in_speech:
                adaptive_threshold = self.get_adaptive_silence_threshold()
                if self._silence_duration_seconds >= adaptive_threshold:
                    self._in_speech = False
                    total_speech = self._speech_duration_seconds
                    silence_dur = self._silence_duration_seconds
                    self.reset()
                    logger.info(
                        f"[EOS] end_of_speech duration={silence_dur:.2f}s total_speech={total_speech:.2f}s "
                        f"(umbral_adaptativo={adaptive_threshold:.2f}s)"
                    )
                    return VADResult(
                        event=VADEvent.SPEECH_END,
                        is_speech=False,
                        confidence=1.0,
                        energy=energy,
                        duration_ms=total_speech * 1000.0,
                    )
                else:
                    # Pausa natural o silencio breve dentro de la intervención
                    if self._silence_duration_seconds >= 0.35 and (self._silence_duration_seconds - chunk_duration) < 0.35:
                        logger.info(f"[EOS] silence_started duration={self._silence_duration_seconds:.2f}s")
                    return VADResult(
                        event=VADEvent.SPEECH_CONTINUE,
                        is_speech=True,
                        confidence=0.5,
                        energy=energy,
                        duration_ms=self._speech_duration_seconds * 1000.0,
                    )

            # Si no estábamos hablando y hay silencio prolongado
            if self._silence_duration_seconds >= self.silence_timeout_seconds:
                return VADResult(
                    event=VADEvent.TIMEOUT,
                    is_speech=False,
                    confidence=1.0,
                    energy=energy,
                    duration_ms=self._silence_duration_seconds * 1000.0,
                )

        return VADResult(
            event=VADEvent.SILENCE,
            is_speech=False,
            confidence=1.0,
            energy=energy,
            duration_ms=chunk_duration * 1000.0,
        )
