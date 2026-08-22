"""Interfaz y Adaptador de Voz para JESSYCA Local Agent (voice_interface.py - Fases 45 y 51).

Orquesta el pipeline de audio integrado y sesiones continuas de voz:
Wake Word -> Audio Input / VAD -> STT -> Agent Resolution -> TTS Synthesis -> Follow-up Window.

Evalúa:
- STT Accuracy y latencia
- TTS Latency
- Wake Word Reliability y Bypass condicional en Follow-up (Fase 51)
- ContinuousVoiceSession & VoiceSessionMode
- Interrupciones / Barge-in
- Activación de Parada de Emergencia y Cancelación por Voz
"""

from __future__ import annotations

import time

from core.cancellation import CancellationToken
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.local_agent.local_agent_models import (
    InputModality,
    JessycaRequest,
    LocalAgentMetrics,
)
from core.logger import get_logger
from services.voice.audio_input import IAudioSource, SyntheticAudioSource
from services.voice.barge_in_controller import BargeInController
from services.voice.continuous_voice_session import (
    ContinuousVoiceSession,
)
from services.voice.stt_service import ISTTService, MockSTTService, TranscriptResult
from services.voice.tts_service import ITTSService, MockTTSService
from services.voice.vad_service import EnergyVADService, IVADService
from services.voice.voice_pipeline import (
    EMERGENCY_VOICE_PHRASES,
    STOP_VOICE_PHRASES,
)
from services.voice.wake_word_service import (
    IWakeWordService,
    KeywordWakeWordService,
)

logger = get_logger("jessyca.local_agent.voice")


class LocalVoiceInterface:
    """Adaptador de alto nivel para la interacción por voz continua con JESSYCA Local Agent."""

    def __init__(
        self,
        audio_source: IAudioSource | None = None,
        vad_service: IVADService | None = None,
        wake_word_service: IWakeWordService | None = None,
        stt_service: ISTTService | None = None,
        tts_service: ITTSService | None = None,
        emergency_stop: EmergencyStopManager | None = None,
        barge_in_controller: BargeInController | None = None,
        conversation_idle_timeout: float = 10.0,
    ) -> None:
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self.audio_source = audio_source or SyntheticAudioSource()
        self.vad_service = vad_service or EnergyVADService()
        self.wake_word_service = wake_word_service or KeywordWakeWordService()
        self.stt_service = stt_service or MockSTTService()
        self.tts_service = tts_service or MockTTSService()
        self.barge_in = barge_in_controller or BargeInController(
            tts_service=self.tts_service,
        )
        self.conversation_idle_timeout = conversation_idle_timeout
        self._continuous_sessions: dict[str, ContinuousVoiceSession] = {}

    def get_or_create_continuous_session(
        self,
        session_id: str,
        idle_timeout: float | None = None,
    ) -> ContinuousVoiceSession:
        """Obtiene o crea una sesión conversacional de voz continua."""
        timeout = idle_timeout or self.conversation_idle_timeout
        sess = self._continuous_sessions.get(session_id)
        if sess is None:
            sess = ContinuousVoiceSession(
                session_id=session_id,
                conversation_idle_timeout=timeout,
            )
            self._continuous_sessions[session_id] = sess
        return sess

    def reset_continuous_sessions(self) -> None:
        """Restablece todas las sesiones de voz continua para aislamiento en pruebas."""
        for s in self._continuous_sessions.values():
            s.end_session()
        self._continuous_sessions.clear()

    def capture_voice_request(
        self,
        require_wake_word: bool | None = None,
        cancellation_token: CancellationToken | None = None,
        session_id: str = "voice_session",
    ) -> tuple[JessycaRequest | None, LocalAgentMetrics, str | None]:
        """Captura y transcribe un turno de voz gestionando la sesión continua.

        Returns:
            (jessyca_request, metrics, error_message)
        """
        metrics = LocalAgentMetrics()
        start_time = time.perf_counter()

        # 0. Verificación inmediata de Parada de Emergencia
        if self.emergency_stop.is_stopped():
            metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
            return None, metrics, "Parada de Emergencia activa. Captura de voz cancelada."

        # Asegurar que la fuente de audio esté activa
        if hasattr(self.audio_source, "is_active") and not self.audio_source.is_active():
            if hasattr(self.audio_source, "start"):
                self.audio_source.start()

        session = self.get_or_create_continuous_session(session_id)

        # 1. Determinar si se requiere wake word (Modo IDLE vs WAITING_FOR_FOLLOWUP)
        if require_wake_word is None:
            must_require_ww = session.should_require_wake_word()
        else:
            must_require_ww = require_wake_word

        if must_require_ww:
            t_ww_0 = time.perf_counter()
            ww_chunk = self.audio_source.read_chunk()
            session.pre_roll_buffer.append(ww_chunk.data)
            ww_res = self.wake_word_service.process_audio(ww_chunk)
            ww_detected = getattr(ww_res, "detected", bool(ww_res))
            ww_conf = getattr(ww_res, "confidence", 1.0)
            metrics.wake_word_latency_ms = (time.perf_counter() - t_ww_0) * 1000
            metrics.wake_word_detected = ww_detected
            metrics.wake_word_confidence = ww_conf if ww_detected else 0.0

            if not ww_detected:
                metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
                return None, metrics, "Wake word 'Jessyca' no detectada."

            session.on_wake_detected()
        else:
            session.on_listening_started()

        # 2. VAD: Detección de actividad vocal
        audio_chunk = self.audio_source.read_chunk()
        session.pre_roll_buffer.append(audio_chunk.data)
        vad_state = self.vad_service.process_chunk(audio_chunk)

        # 3. STT: Transcripción del audio a texto
        session.on_processing_started()
        t_stt_0 = time.perf_counter()
        transcript_res: TranscriptResult = self.stt_service.transcribe(audio_chunk.data)
        metrics.stt_latency_ms = (time.perf_counter() - t_stt_0) * 1000
        metrics.stt_accuracy = transcript_res.confidence

        transcribed_text = transcript_res.text.strip()

        # 4. Chequeo de cancelación por token
        if cancellation_token and cancellation_token.is_cancelled:
            session.end_session()
            metrics.interruption_handled = True
            metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
            return None, metrics, "Interacción de voz cancelada por el usuario."

        # 5. Detección de Frases Críticas por Voz (Emergency Stop / Cancellation)
        lower_transcript = transcribed_text.lower()
        if any(phrase in lower_transcript for phrase in EMERGENCY_VOICE_PHRASES):
            session.end_session()
            self.emergency_stop.trigger_stop(
                reason=f"Parada de emergencia activada por comando de voz: '{transcribed_text}'",
                source="voice_interface",
            )
            metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
            return None, metrics, f"Parada de emergencia activada por voz: '{transcribed_text}'"

        if any(phrase in lower_transcript for phrase in STOP_VOICE_PHRASES):
            session.end_session()
            metrics.interruption_handled = True
            metrics.total_latency_ms = (time.perf_counter() - start_time) * 1000
            return None, metrics, f"Cancelación por voz recibida: '{transcribed_text}'"

        request = JessycaRequest(
            session_id=session_id,
            modality=InputModality.VOICE,
            user_input=transcribed_text,
            audio_data=audio_chunk.data,
            require_wake_word=must_require_ww,
            metadata={
                "vad_state": str(vad_state),
                "stt_confidence": transcript_res.confidence,
                "voice_session_mode": session.mode.value,
            },
        )

        return request, metrics, None

    def synthesize_response(
        self,
        text: str,
        cancellation_token: CancellationToken | None = None,
        session_id: str = "voice_session",
    ) -> tuple[bool, float]:
        """Sintetiza la respuesta por voz y transiciona la sesión a WAITING_FOR_FOLLOWUP.

        Returns:
            (tts_success, tts_latency_ms)
        """
        session = self.get_or_create_continuous_session(session_id)

        if not text or not text.strip():
            session.on_speaking_finished()
            return True, 0.0

        if self.emergency_stop.is_stopped():
            session.end_session()
            return False, 0.0

        t0 = time.perf_counter()
        session.on_speaking_started()
        try:
            # Comprobar interrupción antes de sintetizar
            if cancellation_token and cancellation_token.is_cancelled:
                session.end_session()
                return False, (time.perf_counter() - t0) * 1000

            success = self.tts_service.speak(text)
            session.on_speaking_finished()
            latency_ms = (time.perf_counter() - t0) * 1000
            return success, latency_ms
        except Exception as ex:
            logger.error(f"[VOICE TTS ERROR] {ex}")
            session.end_session()
            return False, (time.perf_counter() - t0) * 1000
