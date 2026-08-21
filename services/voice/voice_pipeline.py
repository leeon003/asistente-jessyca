"""Orquestador integral del Pipeline de Voz (voice_pipeline.py - Fase 13).

Coordina:
MICROPHONE -> VAD -> WAKE WORD -> STT -> ORCHESTRATOR / AGENT LOOP -> SECURITY -> TTS -> SPEAKER.

INVARIANTE DE SEGURIDAD ABSOLUTA:
- La voz sigue exactamente el mismo pipeline de seguridad que el texto (USER INPUT = UNTRUSTED DATA).
- WAKE WORD != AUTHORIZATION.
- No existen atajos ni bypasses para comandos de voz.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.cancellation import CancellationToken
from core.control_plane.models import AgentLoopResult
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger
from services.voice.audio_input import IAudioSource, SyntheticAudioSource
from services.voice.stt_service import ISTTService, MockSTTService, TranscriptResult
from services.voice.tts_service import ITTSService, MockTTSService
from services.voice.vad_service import EnergyVADService, IVADService, VADEvent
from services.voice.voice_errors import VoiceCancelledError
from services.voice.wake_word_service import (
    IWakeWordService,
    KeywordWakeWordService,
)

logger = get_logger("jessyca.voice.pipeline")


@dataclass(frozen=True)
class VoiceInteractionResult:
    """Resultado formal inmutable de un ciclo completo de interacción por voz."""

    transcript: TranscriptResult
    agent_result: AgentLoopResult | None
    spoken_response: str
    tts_success: bool
    is_success: bool
    error: str | None = None
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "transcript": self.transcript.to_dict(),
            "agent_result": self.agent_result.to_dict() if self.agent_result else None,
            "spoken_response": self.spoken_response,
            "tts_success": self.tts_success,
            "is_success": self.is_success,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
        }


class VoicePipeline:
    """Pipeline de procesamiento de voz de extremo a extremo."""

    def __init__(
        self,
        audio_source: IAudioSource | None = None,
        vad_service: IVADService | None = None,
        wake_word_service: IWakeWordService | None = None,
        stt_service: ISTTService | None = None,
        tts_service: ITTSService | None = None,
        agent_executor: Callable[[str], AgentLoopResult] | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.audio_source = audio_source or SyntheticAudioSource()
        self.vad_service = vad_service or EnergyVADService()
        self.wake_word_service = wake_word_service or KeywordWakeWordService()
        self.stt_service = stt_service or MockSTTService()
        self.tts_service = tts_service or MockTTSService()
        self.agent_executor = agent_executor
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()

    def process_voice_turn(
        self,
        audio_data: bytes | None = None,
        cancellation_token: CancellationToken | None = None,
        require_wake_word: bool = True,
    ) -> VoiceInteractionResult:
        """Ejecuta un turno completo de interacción de voz."""
        start_time = time.monotonic()

        # 0. Verificación de parada de emergencia y cancelación
        if self.emergency_stop.is_stopped():
            return VoiceInteractionResult(
                transcript=TranscriptResult(text="", confidence=0.0, language="es", duration_ms=0.0),
                agent_result=None,
                spoken_response="Parada de emergencia activa. Operación cancelada.",
                tts_success=False,
                is_success=False,
                error="EMERGENCY_STOP_ACTIVE",
                duration_ms=(time.monotonic() - start_time) * 1000.0,
            )

        if cancellation_token and cancellation_token.is_cancelled:
            raise VoiceCancelledError("Operación de voz cancelada antes de iniciar.")

        # 1. Captura de audio y Wake Word si es requerido
        if not self.audio_source.is_active():
            self.audio_source.start()

        chunk = self.audio_source.read_chunk()

        if require_wake_word:
            ww_result = self.wake_word_service.process_audio(chunk)
            if not ww_result.detected:
                return VoiceInteractionResult(
                    transcript=TranscriptResult(text="", confidence=0.0, language="es", duration_ms=0.0),
                    agent_result=None,
                    spoken_response="",
                    tts_success=False,
                    is_success=False,
                    error="WAKE_WORD_NOT_DETECTED",
                    duration_ms=(time.monotonic() - start_time) * 1000.0,
                )

        # 2. Evaluación de VAD
        vad_res = self.vad_service.process_chunk(chunk)
        if vad_res.event == VADEvent.TIMEOUT:
            return VoiceInteractionResult(
                transcript=TranscriptResult(text="", confidence=0.0, language="es", duration_ms=0.0),
                agent_result=None,
                spoken_response="",
                tts_success=False,
                is_success=False,
                error="VAD_TIMEOUT",
                duration_ms=(time.monotonic() - start_time) * 1000.0,
            )

        # 3. Transcripción STT
        raw_audio_to_transcribe = audio_data or chunk.data
        try:
            transcript = self.stt_service.transcribe(raw_audio_to_transcribe)
        except Exception as e:
            logger.error(f"[VOICE PIPELINE] Error en STT: {e}")
            return VoiceInteractionResult(
                transcript=TranscriptResult(text="", confidence=0.0, language="es", duration_ms=0.0),
                agent_result=None,
                spoken_response="No se pudo procesar el audio.",
                tts_success=False,
                is_success=False,
                error=f"STT_ERROR: {e}",
                duration_ms=(time.monotonic() - start_time) * 1000.0,
            )

        if transcript.is_empty:
            return VoiceInteractionResult(
                transcript=transcript,
                agent_result=None,
                spoken_response="",
                tts_success=False,
                is_success=False,
                error="EMPTY_TRANSCRIPT",
                duration_ms=(time.monotonic() - start_time) * 1000.0,
            )

        logger.info(f"[VOICE PIPELINE] Texto transcrito: '{transcript.text}' (Confianza: {transcript.confidence:.2f})")

        # 4. Orquestación y Seguridad (Orchestrator / Agent System)
        agent_result: AgentLoopResult | None = None
        spoken_response = ""

        if self.agent_executor:
            try:
                agent_result = self.agent_executor(transcript.text)
                if agent_result.is_success:
                    spoken_response = f"Operación completada: {transcript.text}"
                else:
                    spoken_response = f"No se pudo completar la acción: {agent_result.stop_reason or 'Denegado por seguridad'}"
            except Exception as e:
                logger.error(f"[VOICE PIPELINE] Error en ejecución de agente: {e}")
                spoken_response = "Ocurrió un error al procesar la solicitud."
        else:
            spoken_response = f"Recibido: {transcript.text}"

        # 5. Síntesis de respuesta TTS
        tts_ok = False
        if spoken_response:
            try:
                tts_ok = self.tts_service.speak(spoken_response, cancellation_token=cancellation_token)
            except VoiceCancelledError:
                raise
            except Exception as e:
                logger.warning(f"[VOICE PIPELINE] Fallo en síntesis TTS (continuando sin crash): {e}")
                tts_ok = False

        duration = (time.monotonic() - start_time) * 1000.0

        return VoiceInteractionResult(
            transcript=transcript,
            agent_result=agent_result,
            spoken_response=spoken_response,
            tts_success=tts_ok,
            is_success=agent_result.is_success if agent_result else True,
            duration_ms=duration,
        )
