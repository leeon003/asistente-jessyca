"""Suite de Pruebas Exhaustiva para Voice Assistant 2.0 (Fase 30).

Valida con mocks deterministas:
1. Wake word detection & falsos positivos
2. STT transcription
3. TTS synthesis & stop
4. Barge-in e interrupción durante TTS
5. Detección de silencio y timeout VAD
6. Cancelación y parada por voz
7. Parada de emergencia por voz
8. Protocolo de confirmación por voz (afirmación, rechazo, descarte de ambigüedad/ruido)
9. Respuestas progresivas
"""

from core.cancellation import CancellationToken
from core.emergency_stop import EmergencyStopManager
from services.voice import (
    AudioChunk,
    BargeInController,
    EnergyVADService,
    KeywordWakeWordService,
    MockSTTService,
    MockTTSService,
    SyntheticAudioSource,
    TranscriptResult,
    VADEvent,
    VoiceConfirmationEvaluator,
    VoicePipeline,
)


class TestVoiceAssistantV2:
    """Suite de validación para el Asistente de Voz 2.0."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_voice_setup")

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

    # ── 1. WAKE WORD & FALSE POSITIVES ──

    def test_wake_word_detection_and_rejection(self) -> None:
        """Verifica activación con wake word y descarte ante silencio/ruido."""
        # Activación positiva
        self.audio_source.feed_tone(duration_seconds=0.2)
        self.wake_word_service.trigger_manually()
        r_ok = self.pipeline.process_voice_turn(require_wake_word=True)
        assert r_ok.is_success is True

        # Falso positivo / silencio descartado
        self.audio_source.feed_silence(duration_seconds=0.5)
        r_fail = self.pipeline.process_voice_turn(require_wake_word=True)
        assert r_fail.is_success is False
        assert r_fail.error == "WAKE_WORD_NOT_DETECTED"

    # ── 2. STT & TTS BASICS ──

    def test_stt_and_tts_execution(self) -> None:
        """Verifica transcripción y síntesis básica."""
        self.stt_service.predefined_transcription = "busca noticias de tecnología"
        self.wake_word_service.trigger_manually()

        result = self.pipeline.process_voice_turn(require_wake_word=True)

        assert result.is_success is True
        assert result.transcript.text == "busca noticias de tecnología"
        assert result.tts_success is True
        assert len(self.tts_service.spoken_texts) > 0

    # ── 3. BARGE-IN & INTERRUPTION ──

    def test_barge_in_controller_stops_active_tts(self) -> None:
        """Verifica que el BargeInController detenga la reproducción de TTS activa."""
        controller = BargeInController(tts_service=self.tts_service)
        token = CancellationToken()

        # Simular que TTS comienza a hablar
        controller.notify_tts_started(token)
        assert controller.is_tts_active is True
        assert token.is_cancelled is False

        # Usuario interrumpe hablando
        interrupted = controller.trigger_barge_in(reason="User barge-in test")

        assert interrupted is True
        assert controller.is_tts_active is False
        assert token.is_cancelled is True
        assert controller.interrupted_count == 1

        # Segundo intento sin voz activa no interrumpe
        assert controller.trigger_barge_in() is False

    # ── 4. SILENCE DETECTION & VAD TIMEOUT ──

    def test_vad_silence_detection(self) -> None:
        """Verifica detección de silencio y timeout en VAD."""
        vad = EnergyVADService(silence_timeout_seconds=0.1)
        silence = AudioChunk(data=b"\x00" * 3200)

        # 3 chunks consecutivos de silencio
        vad.process_chunk(silence)
        vad.process_chunk(silence)
        res = vad.process_chunk(silence)

        assert res.event == VADEvent.TIMEOUT
        assert res.is_speech is False

    # ── 5. VOICE CANCELLATION COMMANDS ──

    def test_voice_stop_command_cancels_turn(self) -> None:
        """Verifica que comandos como 'cancela' o 'detente' interrumpan la ejecución."""
        self.stt_service.predefined_transcription = "cancela"
        self.wake_word_service.trigger_manually()

        result = self.pipeline.process_voice_turn(require_wake_word=True)

        assert result.is_success is True
        assert result.error == "VOICE_CANCELLED_BY_USER"
        assert "Operación cancelada" in result.spoken_response

    # ── 6. VOICE EMERGENCY STOP ──

    def test_voice_emergency_stop_triggers_system_halt(self) -> None:
        """Verifica que la frase 'parada de emergencia' active EmergencyStopManager."""
        assert self.emergency_stop.is_stopped() is False

        self.stt_service.predefined_transcription = "parada de emergencia"
        self.wake_word_service.trigger_manually()

        result = self.pipeline.process_voice_turn(require_wake_word=True)

        assert result.is_success is False
        assert result.error == "EMERGENCY_STOP_TRIGGERED_BY_VOICE"
        assert self.emergency_stop.is_stopped() is True
        assert "Parada de emergencia ejecutada" in result.spoken_response

    # ── 7. VOICE CONFIRMATION PROTOCOL ──

    def test_voice_confirmation_affirmative_cases(self) -> None:
        """Verifica que afirmaciones explícitas autoricen la confirmación."""
        valid_affirmations = ["sí", "si", "confirmo", "adelante", "proceder", "autorizo", "sí confirmo"]
        for phrase in valid_affirmations:
            decision = VoiceConfirmationEvaluator.evaluate(
                TranscriptResult(text=phrase, confidence=0.95, language="es", duration_ms=10.0)
            )
            assert decision.is_confirmed is True, f"Fallo en afirmación: '{phrase}'"
            assert decision.is_rejected is False
            assert decision.is_ambiguous is False

    def test_voice_confirmation_negative_cases(self) -> None:
        """Verifica que rechazos explícitos cancelen la operación."""
        valid_rejections = ["no", "cancela", "rechazar", "no lo hagas", "para", "detente"]
        for phrase in valid_rejections:
            decision = VoiceConfirmationEvaluator.evaluate(
                TranscriptResult(text=phrase, confidence=0.95, language="es", duration_ms=10.0)
            )
            assert decision.is_confirmed is False
            assert decision.is_rejected is True, f"Fallo en rechazo: '{phrase}'"
            assert decision.is_ambiguous is False

    def test_voice_confirmation_rejects_ambiguity_and_noise(self) -> None:
        """Verifica que sonidos ambiguos, muletillas o baja confianza se rechacen como ambiguos."""
        ambiguous_cases = [
            "mmm",
            "eh",
            "quizás",
            "tal vez",
            "hola",
            "a ver",
            "no sé",
            "buenas tardes cómo estás",
        ]
        for phrase in ambiguous_cases:
            decision = VoiceConfirmationEvaluator.evaluate(
                TranscriptResult(text=phrase, confidence=0.85, language="es", duration_ms=10.0)
            )
            assert decision.is_confirmed is False, f"Se aprobó erróneamente frase ambigua: '{phrase}'"
            assert decision.is_ambiguous is True

        # Prueba con baja confianza (< 0.70)
        low_confidence_decision = VoiceConfirmationEvaluator.evaluate(
            TranscriptResult(text="sí", confidence=0.45, language="es", duration_ms=10.0)
        )
        assert low_confidence_decision.is_confirmed is False
        assert low_confidence_decision.is_ambiguous is True
        assert "insuficiente" in low_confidence_decision.reason

    # ── 8. PROGRESSIVE RESPONSES & REQUEST CONFIRMATION ──

    def test_pipeline_request_voice_confirmation(self) -> None:
        """Verifica el flujo request_voice_confirmation del pipeline."""
        self.stt_service.predefined_transcription = "sí, confirmo"
        decision = self.pipeline.request_voice_confirmation(
            confirmation_prompt="¿Deseas formatear el archivo temporal?",
        )
        assert decision.is_confirmed is True
        assert len(self.tts_service.spoken_texts) > 0
        assert "¿Deseas formatear" in self.tts_service.spoken_texts[0]

    def test_pipeline_progressive_feedback(self) -> None:
        """Verifica la emisión de feedback progresivo."""
        self.stt_service.predefined_transcription = "analiza el rendimiento"
        self.wake_word_service.trigger_manually()

        result = self.pipeline.process_voice_turn(require_wake_word=True, progressive_feedback=True)

        assert result.is_success is True
        assert any("Entendido" in t for t in self.tts_service.spoken_texts)
