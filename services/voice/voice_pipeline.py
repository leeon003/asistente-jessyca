"""Orquestador integral del Pipeline de Voz 2.0 (voice_pipeline.py - Fase 30).

Coordina el flujo conversacional completo:
WAKE -> LISTEN -> STT -> INTENT -> PLAN -> SECURITY -> ACTION -> TTS.

Funciones integradas:
- Barge-in e interrupción durante TTS.
- Detección de comandos de parada y cancelación por voz.
- Parada de emergencia activada por voz.
- Confirmación por voz con evaluación estricta anti-ruido / anti-ambigüedad.
- Respuestas progresivas / feedback inmediato.
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
from services.voice.barge_in_controller import BargeInController
from services.voice.stt_service import ISTTService, MockSTTService, TranscriptResult
from services.voice.tts_service import ITTSService, MockTTSService
from services.voice.vad_service import EnergyVADService, IVADService, VADEvent
from services.voice.voice_confirmation import (
    VoiceConfirmationDecision,
    VoiceConfirmationEvaluator,
)
from services.voice.voice_errors import VoiceCancelledError
from services.voice.wake_word_service import (
    IWakeWordService,
    KeywordWakeWordService,
)

logger = get_logger("jessyca.voice.pipeline")

EMERGENCY_VOICE_PHRASES: frozenset[str] = frozenset({
    "emergencia",
    "parada de emergencia",
    "alto al sistema",
    "emergency stop",
    "parada total",
    "apágate ya",
    "apagate ya",
})

STOP_VOICE_PHRASES: frozenset[str] = frozenset({
    "cancela",
    "cancelar",
    "detente",
    "para",
    "olvídalo",
    "olvidalo",
    "silencio",
    "cállate",
    "callate",
})


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
    """Pipeline de procesamiento de voz conversacional de extremo a extremo (Fase 30)."""

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
        self.barge_in_controller = BargeInController(tts_service=self.tts_service)

    def process_voice_turn(
        self,
        audio_data: bytes | None = None,
        cancellation_token: CancellationToken | None = None,
        require_wake_word: bool = True,
        progressive_feedback: bool = False,
    ) -> VoiceInteractionResult:
        """Ejecuta un turno completo de interacción de voz con validación de seguridad y barge-in."""
        start_time = time.monotonic()

        # 0. Verificación de parada de emergencia previa y cancelación
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

        # 2. Evaluación de VAD (detección de voz y silencio)
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
        text_lower = transcript.text.lower().strip()

        # 4. Verificación de Comandos de Parada de Emergencia por Voz
        if any(phrase in text_lower for phrase in EMERGENCY_VOICE_PHRASES):
            logger.critical(f"[VOICE PIPELINE] Parada de emergencia activada por voz: '{transcript.text}'")
            self.emergency_stop.trigger_stop(reason=f"Comando de voz: {transcript.text}")
            spoken_msg = "Parada de emergencia ejecutada inmediatamente."
            self._safe_speak(spoken_msg, cancellation_token)
            return VoiceInteractionResult(
                transcript=transcript,
                agent_result=None,
                spoken_response=spoken_msg,
                tts_success=True,
                is_success=False,
                error="EMERGENCY_STOP_TRIGGERED_BY_VOICE",
                duration_ms=(time.monotonic() - start_time) * 1000.0,
            )

        # 5. Verificación de Comandos de Cancelación / Stop por Voz
        if any(phrase == text_lower or text_lower.startswith(phrase + " ") for phrase in STOP_VOICE_PHRASES):
            logger.info(f"[VOICE PIPELINE] Cancelación por voz solicitada: '{transcript.text}'")
            self.barge_in_controller.trigger_barge_in(reason="Voice cancel command")
            spoken_msg = "Operación cancelada."
            self._safe_speak(spoken_msg, cancellation_token)
            return VoiceInteractionResult(
                transcript=transcript,
                agent_result=None,
                spoken_response=spoken_msg,
                tts_success=True,
                is_success=True,
                error="VOICE_CANCELLED_BY_USER",
                duration_ms=(time.monotonic() - start_time) * 1000.0,
            )

        # 6. Feedback Progresivo Inmediato si está habilitado
        if progressive_feedback:
            self._safe_speak("Entendido, procesando...", cancellation_token)

        # 7. Orquestación y Seguridad (Orchestrator / Agent System)
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

        # 8. Síntesis y Reproducción de Respuesta TTS
        tts_ok = self._safe_speak(spoken_response, cancellation_token)

        duration = (time.monotonic() - start_time) * 1000.0

        return VoiceInteractionResult(
            transcript=transcript,
            agent_result=agent_result,
            spoken_response=spoken_response,
            tts_success=tts_ok,
            is_success=agent_result.is_success if agent_result else True,
            duration_ms=duration,
        )

    def request_voice_confirmation(
        self,
        confirmation_prompt: str,
        user_response_audio: bytes | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> VoiceConfirmationDecision:
        """Solicita verbalmente una confirmación y evalúa de forma unívoca la respuesta del usuario."""
        # 1. Hablar la pregunta de confirmación
        self._safe_speak(confirmation_prompt, cancellation_token)

        # 2. Capturar y transcribir la respuesta verbal
        if user_response_audio:
            raw_audio = user_response_audio
        else:
            if not self.audio_source.is_active():
                self.audio_source.start()
            chunk = self.audio_source.read_chunk()
            raw_audio = chunk.data

        transcript = self.stt_service.transcribe(raw_audio)

        # 3. Evaluar con reglas estrictas de VoiceConfirmationEvaluator
        decision = VoiceConfirmationEvaluator.evaluate(transcript)
        logger.info(
            f"[VOICE CONFIRMATION] Resultado: confirmed={decision.is_confirmed}, "
            f"rejected={decision.is_rejected}, ambiguous={decision.is_ambiguous} (Razón: {decision.reason})"
        )
        return decision

    def _safe_speak(self, text: str, cancellation_token: CancellationToken | None = None) -> bool:
        """Emite voz gestionando el controlador de Barge-in y cancelaciones."""
        if not text or not text.strip():
            return True

        self.barge_in_controller.notify_tts_started(cancellation_token)
        try:
            res = self.tts_service.speak(text, cancellation_token=cancellation_token)
            return res
        except VoiceCancelledError:
            logger.info("[VOICE PIPELINE] TTS cancelado por token.")
            return False
        except Exception as exc:
            logger.warning(f"[VOICE PIPELINE] Fallo en TTS speak: {exc}")
            return False
        finally:
            self.barge_in_controller.notify_tts_finished()
