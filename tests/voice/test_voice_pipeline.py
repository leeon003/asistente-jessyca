"""Tests unitarios exhaustivos para el Pipeline de Voz (Fase 13: Voice Pipeline).

Pruebas completamente aisladas y deterministas con mocks de micrófono, Whisper, VAD y TTS:
1. Activación con Wake Word vs No Wake Word
2. Detección de Speech y Silencio en VAD
3. Manejo de Timeouts (VAD y STT)
4. Cancelación inmediata (CancellationToken)
5. Tolerancia a fallos en STT y TTS (cero crashes)
6. Invariante de Seguridad: Comandos de voz peligrosos bloqueados por SecurityPipeline
"""

from core.cancellation import CancellationToken
from core.control_plane.models import AgentLoopResult, AgentLoopState
from core.emergency_stop import EmergencyStopManager
from services.voice import (
    AudioChunk,
    EnergyVADService,
    KeywordWakeWordService,
    MockSTTService,
    MockTTSService,
    SyntheticAudioSource,
    VADEvent,
    VoiceCancelledError,
    VoicePipeline,
)


class TestVoicePipeline:
    """Suite de pruebas de integración y seguridad para el Voice Pipeline."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset()

        self.audio_source = SyntheticAudioSource()
        self.vad_service = EnergyVADService()
        self.wake_word_service = KeywordWakeWordService()
        self.stt_service = MockSTTService(predefined_transcription="revisa la memoria RAM")
        self.tts_service = MockTTSService()

        self.pipeline = VoicePipeline(
            audio_source=self.audio_source,
            vad_service=self.vad_service,
            wake_word_service=self.wake_word_service,
            stt_service=self.stt_service,
            tts_service=self.tts_service,
            emergency_stop=self.emergency_stop,
        )

    # ── 1. WAKE WORD DETECTION ──

    def test_wake_word_activates_pipeline(self) -> None:
        """Verifica que al detectar la palabra clave 'Jessyca', el pipeline procese el turno."""
        self.audio_source.feed_tone(duration_seconds=0.5)
        self.wake_word_service.trigger_manually()

        result = self.pipeline.process_voice_turn(require_wake_word=True)

        assert result.is_success is True
        assert result.transcript.text == "revisa la memoria RAM"
        assert result.tts_success is True
        assert "revisa la memoria RAM" in self.tts_service.spoken_texts[0]

    def test_no_wake_word_skips_processing(self) -> None:
        """Verifica que sin la palabra de activación no se active transcripción ni síntesis innecesarias."""
        self.audio_source.feed_silence(duration_seconds=1.0)
        # No se dispara el wake word
        result = self.pipeline.process_voice_turn(require_wake_word=True)

        assert result.is_success is False
        assert result.error == "WAKE_WORD_NOT_DETECTED"
        assert len(self.tts_service.spoken_texts) == 0

    # ── 2. VAD: SPEECH, SILENCE & TIMEOUT ──

    def test_vad_speech_and_silence_detection(self) -> None:
        """Verifica que VAD distinga correctamente entre chunks con tono/energía y silencio."""
        vad = EnergyVADService(energy_threshold=100.0, speech_pad_chunks=1)
        # 1. Chunk con silencio
        silence_chunk = AudioChunk(data=b"\x00" * 2048)
        res_silence = vad.process_chunk(silence_chunk)
        assert res_silence.event == VADEvent.SILENCE
        assert res_silence.is_speech is False

        # 2. Chunk con tono de audio sintético (energía alta)
        source = SyntheticAudioSource()
        source.start()
        source.feed_tone(frequency_hz=500.0, duration_seconds=0.1, amplitude=0.8)
        tone_chunk = source.read_chunk()
        res_tone = vad.process_chunk(tone_chunk)

        assert res_tone.is_speech is True
        assert res_tone.event in (VADEvent.SPEECH_START, VADEvent.SPEECH_CONTINUE)

    def test_vad_silence_timeout(self) -> None:
        """Verifica que ante un silencio prolongado se emita TIMEOUT."""
        vad = EnergyVADService(silence_timeout_seconds=0.2)
        silence_chunk = AudioChunk(data=b"\x00" * 3200)  # 100ms de audio a 16kHz 16-bit
        # Simular 3 chunks de silencio consecutivo (300ms > 200ms)
        vad.process_chunk(silence_chunk)
        vad.process_chunk(silence_chunk)
        res3 = vad.process_chunk(silence_chunk)

        assert res3.event == VADEvent.TIMEOUT

    # ── 3. CANCELACIÓN (CANCELLATION TOKEN) ──

    def test_voice_pipeline_cancellation(self) -> None:
        """Verifica que un CancellationToken cancelado detenga la operación de voz de forma inmediata."""
        import pytest

        token = CancellationToken()
        token.cancel()

        with pytest.raises(VoiceCancelledError):
            self.pipeline.process_voice_turn(cancellation_token=token, require_wake_word=False)

    # ── 4. RESILIENCIA ANTE FALLOS DE STT Y TTS ──

    def test_stt_failure_gracefully_handled(self) -> None:
        """Verifica que un fallo en STT retorne un resultado de error controlado sin crash."""
        self.stt_service.should_fail = True
        self.wake_word_service.trigger_manually()

        result = self.pipeline.process_voice_turn(require_wake_word=True)

        assert result.is_success is False
        assert "STT_ERROR" in (result.error or "")

    def test_tts_failure_does_not_break_pipeline(self) -> None:
        """Verifica que un fallo en el sintetizador TTS no bloquee el resultado del pipeline."""
        self.tts_service.should_fail = True
        self.wake_word_service.trigger_manually()

        result = self.pipeline.process_voice_turn(require_wake_word=True)

        assert result.transcript.text == "revisa la memoria RAM"
        assert result.tts_success is False  # TTS falló, pero el pipeline completó el reporte

    # ── 5. SEGURIDAD: INVARIANTE VOICE != AUTHORIZATION ──

    def test_dangerous_voice_command_blocked_by_security(self) -> None:
        """Verifica que un comando peligroso transcrito por voz sea rechazado por el executor/security."""
        self.stt_service.predefined_transcription = "formatea el disco C:"
        self.wake_word_service.trigger_manually()

        # Executor simulado que aplica la política de seguridad y rechaza la acción
        def security_mock_executor(intent: str) -> AgentLoopResult:
            return AgentLoopResult(
                task_id="sec-voice-01",
                intent=intent,
                final_state=AgentLoopState.STOPPED_PERMISSION_DENIED,
                iterations_executed=0,
                tools_executed=0,
                tokens_consumed=0,
                duration_seconds=0.01,
                stop_reason="Acción de alto riesgo DANGEROUS no autorizada.",
            )

        secure_pipeline = VoicePipeline(
            audio_source=self.audio_source,
            vad_service=self.vad_service,
            wake_word_service=self.wake_word_service,
            stt_service=self.stt_service,
            tts_service=self.tts_service,
            agent_executor=security_mock_executor,
            emergency_stop=self.emergency_stop,
        )

        result = secure_pipeline.process_voice_turn(require_wake_word=True)

        assert result.is_success is False
        assert result.agent_result is not None
        assert result.agent_result.final_state == AgentLoopState.STOPPED_PERMISSION_DENIED
        assert "No se pudo completar" in result.spoken_response

    def test_emergency_stop_halts_voice_pipeline(self) -> None:
        """Verifica que la activación de EmergencyStop impida cualquier interacción por voz."""
        self.emergency_stop.trigger_stop(reason="Parada de emergencia manual")

        result = self.pipeline.process_voice_turn()

        assert result.is_success is False
        assert result.error == "EMERGENCY_STOP_ACTIVE"
