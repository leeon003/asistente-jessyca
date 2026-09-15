"""Diagnósticos y Telemetría del Pipeline de Voz (voice_diagnostics.py - Fase 51.1).

Proporciona modelos estructurados de telemetría y diagnósticos de audio y VAD
sin registrar contenido de audio crudo ni vulnerar la privacidad del usuario:
- VoiceDiscardReason (clasificación de causas de descarte)
- VoiceCaptureDiagnostic (métricas numéricas de cada captura)
- VoiceTelemetryCollector (agregador de estadísticas en memoria)
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.logger import get_logger

logger = get_logger("jessyca.voice.diagnostics")


class VoiceDiscardReason(StrEnum):
    """Causas formales de descarte o no procesamiento de una captura de voz."""

    NONE = "NONE"
    NO_AUDIO = "NO_AUDIO"
    LOW_ENERGY = "LOW_ENERGY"
    NO_VAD = "NO_VAD"
    TOO_SHORT = "TOO_SHORT"
    LOW_STT_CONFIDENCE = "LOW_STT_CONFIDENCE"
    EMPTY_TRANSCRIPT = "EMPTY_TRANSCRIPT"
    DEVICE_ERROR = "DEVICE_ERROR"
    TIMEOUT = "TIMEOUT"
    OTHER = "OTHER"


class VoiceCaptureDiagnostic(BaseModel):
    """Registro inmutable de diagnóstico técnico de una captura de audio."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    capture_id: str = Field(default_factory=lambda: f"cap-{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mode: str = "IDLE"
    duration_ms: float = 0.0
    sample_rate: int = 16000
    channels: int = 1
    audio_rms: float = 0.0
    audio_peak: float = 0.0
    noise_floor: float = 0.0
    speech_ratio: float = 0.0
    vad_detected: bool = False
    speech_start_ms: float = 0.0
    speech_end_ms: float = 0.0
    frames_total: int = 0
    speech_frames: int = 0
    silence_frames: int = 0
    pre_roll_ms: int = 400
    post_roll_ms: int = 600
    stt_attempted: bool = False
    stt_text: str = ""
    stt_confidence: float = 0.0
    eos_to_stt_start_ms: float = 0.0
    stt_duration_ms: float = 0.0
    discard_reason: VoiceDiscardReason = VoiceDiscardReason.NONE
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serializa el diagnóstico a un diccionario."""
        return dict(self.model_dump(mode="json"))

    def log_diagnostic(self) -> None:
        """Registra el diagnóstico técnico en el logger si VOICE_DIAGNOSTICS está activo."""
        logger.debug(
            f"[VOICE_DIAGNOSTIC] capture_id={self.capture_id} mode={self.mode} "
            f"duration={self.duration_ms:.1f}ms rms={self.audio_rms:.1f} "
            f"noise_floor={self.noise_floor:.1f} vad={self.vad_detected} "
            f"stt_attempted={self.stt_attempted} conf={self.stt_confidence:.2f} "
            f"discard={self.discard_reason.value}"
        )


class UtteranceLatencyTrace(BaseModel):
    """Traza de latencia estructurada por turno/utterance (Fase 75.2-B)."""

    model_config = ConfigDict(extra="ignore")

    utterance_id: str = ""
    eos_to_stt_start: float = 0.0
    stt_duration: float = 0.0
    stt_to_intent: float = 0.0
    intent_duration: float = 0.0
    llm_duration: float = 0.0
    intent_to_execution: float = 0.0
    tts_duration: float = 0.0
    audio_start: float = 0.0
    total_response_time: float = 0.0

    def format_trace(self) -> str:
        """Formatea la traza de latencia exactamente según la especificación de Paso 2."""
        return (
            f"[LATENCY]\n"
            f"utterance_id={self.utterance_id}\n\n"
            f"eos_to_stt_start={self.eos_to_stt_start:.1f}ms\n"
            f"stt_duration={self.stt_duration:.1f}ms\n"
            f"stt_to_intent={self.stt_to_intent:.1f}ms\n"
            f"intent_duration={self.intent_duration:.1f}ms\n"
            f"llm_duration={self.llm_duration:.1f}ms\n"
            f"intent_to_execution={self.intent_to_execution:.1f}ms\n"
            f"tts_duration={self.tts_duration:.1f}ms\n"
            f"audio_start={self.audio_start:.1f}ms\n"
            f"total_response_time={self.total_response_time:.1f}ms"
        )


class VoiceTelemetryCollector:
    """Colector en memoria thread-safe de métricas operativas del pipeline de voz."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._diagnostics: list[VoiceCaptureDiagnostic] = []
        self._max_history = 1000

    def record_capture(self, diagnostic: VoiceCaptureDiagnostic) -> None:
        """Registra un evento de diagnóstico."""
        with self._lock:
            self._diagnostics.append(diagnostic)
            if len(self._diagnostics) > self._max_history:
                self._diagnostics.pop(0)

    def get_metrics(self) -> dict[str, Any]:
        """Calcula métricas agregadas del historial de capturas."""
        with self._lock:
            total = len(self._diagnostics)
            if total == 0:
                return {
                    "total_captures": 0,
                    "success_captures": 0,
                    "success_rate": 0.0,
                    "retry_rate": 0.0,
                    "avg_duration_ms": 0.0,
                    "avg_rms": 0.0,
                    "avg_confidence": 0.0,
                    "discard_breakdown": {},
                }

            success = [d for d in self._diagnostics if d.discard_reason == VoiceDiscardReason.NONE and d.stt_text]
            success_count = len(success)
            discards: dict[str, int] = {}
            for d in self._diagnostics:
                r = d.discard_reason.value
                discards[r] = discards.get(r, 0) + 1

            avg_dur = sum(d.duration_ms for d in self._diagnostics) / total
            avg_rms = sum(d.audio_rms for d in self._diagnostics) / total
            conf_vals = [d.stt_confidence for d in success if d.stt_confidence > 0.0]
            avg_conf = sum(conf_vals) / len(conf_vals) if conf_vals else 0.0

            return {
                "total_captures": total,
                "success_captures": success_count,
                "success_rate": success_count / total,
                "retry_rate": (total - success_count) / total,
                "avg_duration_ms": avg_dur,
                "avg_rms": avg_rms,
                "avg_confidence": avg_conf,
                "discard_breakdown": discards,
            }

    def reset(self) -> None:
        """Limpia el historial de telemetría."""
        with self._lock:
            self._diagnostics.clear()


# Instancia global singleton de telemetría
_telemetry_instance: VoiceTelemetryCollector | None = None
_telemetry_lock = threading.Lock()


def get_voice_telemetry() -> VoiceTelemetryCollector:
    """Obtiene la instancia global del colector de telemetría de voz."""
    global _telemetry_instance
    with _telemetry_lock:
        if _telemetry_instance is None:
            _telemetry_instance = VoiceTelemetryCollector()
        return _telemetry_instance
