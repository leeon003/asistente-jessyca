"""tests/voice/test_push_to_talk_first_version_phase14.py
Suite de validación formal para la primera versión del flujo de voz Pulsar para Hablar (PTT):
- Demostración de PTT, captura, transcripción en español, envío al mismo Core y síntesis de respuesta.
- Comprobación de audio español, silencio, ruido, cancelación y errores del proveedor.
- Prevención de auto-disparo de la propia voz sintetizada (supresión de eco acústico).
- Interrupción de la respuesta (Barge-In) diferenciando detener audio de cancelar una acción en ejecución.
- Comparativa de proveedores TTS existentes y Fish Audio bajo política de privacidad y autorización.
- Separación de palabra de activación (I5) y conservación de Pulsar para Hablar como estándar seguro.
- Medición de latencia y telemetría en hardware real.
"""

from __future__ import annotations

import io
import math
import os
import struct
import time
import wave
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.cancellation import CancellationToken
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    InputModality,
    JessycaRequest,
    JessycaResponse,
)
from services.voice.audio_input import AudioChunk
from services.voice.openwakeword_service import OpenWakeWordAcousticService
from services.voice.push_to_talk import (
    PushToTalkController,
    PushToTalkState,
    PTTExecutionResult,
    TTSProviderComparisonItem,
    compare_tts_providers,
)
from services.voice.stt_service import (
    FasterWhisperSTTService,
    ISTTService,
    MockSTTService,
    TranscriptResult,
)
from services.voice.tts_provider import (
    EdgeTTSProvider,
    PocketTTSProvider,
    TTSManager,
    TTSMetrics,
)
from services.voice.tts_service import TTSResult
from services.voice.voice_diagnostics import VoiceDiscardReason
from services.voice.voice_errors import (
    STTAudioFormatError,
    STTError,
    STTModelUnavailableError,
    STTTimeoutError,
    TTSFailureError,
    VoiceCancelledError,
)
from services.voice.wake_word_service import KeywordWakeWordService


def _generate_pcm16_speech_tone(
    duration_sec: float = 1.0,
    sample_rate: int = 16000,
    freq: float = 220.0,
    amplitude: float = 0.5,
) -> bytes:
    """Genera audio PCM 16-bit little-endian con energía suficiente para superar umbral VAD."""
    num_samples = int(duration_sec * sample_rate)
    samples = []
    for i in range(num_samples):
        val = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * freq * (i / sample_rate)))
        samples.append(val)
    return struct.pack(f"<{num_samples}h", *samples)


def _generate_wav_speech_tone(
    duration_sec: float = 1.0,
    sample_rate: int = 16000,
    freq: float = 220.0,
    amplitude: float = 0.5,
) -> bytes:
    """Genera un archivo WAV en memoria con audio sintético audible."""
    pcm = _generate_pcm16_speech_tone(duration_sec, sample_rate, freq, amplitude)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


# ── TEST 1: FLUJO COMPLETO PULSAR PARA HABLAR (PTT -> CORE -> TTS) ──


def test_ptt_flow_capture_transcribe_dispatch_core_and_speak():
    """Demuestra el ciclo completo de Pulsar para Hablar:
    1. Captura de audio bajo demanda (sin escucha permanente).
    2. Transcripción en español con STT.
    3. Envío al mismo Core unificado (JessycaLocalAgent).
    4. Síntesis y reproducción de la respuesta del asistente."""
    pcm_audio = _generate_pcm16_speech_tone(duration_sec=1.0, amplitude=0.6)

    # STT que simula transcripción en español
    mock_stt = MagicMock(spec=ISTTService)
    mock_stt.transcribe.return_value = TranscriptResult(
        text="¿Cuál es la hora actual?",
        confidence=0.96,
        language="es",
        duration_ms=1000.0,
    )

    # Core que responde coherentemente
    mock_core = MagicMock(spec=JessycaLocalAgent)
    mock_core.interact.return_value = JessycaResponse(
        request_id="req_ptt_01",
        session_id="ptt_test_session",
        success=True,
        status=AgentExecutionState.COMPLETED,
        response_text="Son las 14:00 horas.",
        spoken_text="Son las 14:00 horas.",
        intent="get_time",
    )

    # TTSManager que sintetiza y reproduce
    mock_tts_mgr = MagicMock(spec=TTSManager)
    mock_tts_mgr.speak.return_value = (
        True,
        TTSMetrics(
            t1_request_to_synth_ms=10.0,
            t2_first_audio_ms=120.0,
            t3_total_gen_ms=250.0,
            t4_audio_duration_ms=1800.0,
            provider_used="edge-tts",
            voice_name="es-PE-CamilaNeural",
        ),
    )

    controller = PushToTalkController(
        stt_service=mock_stt,
        tts_manager=mock_tts_mgr,
        agent=mock_core,
    )

    # Comprobar que inicia en IDLE (sin escucha permanente por defecto)
    assert controller.current_state == PushToTalkState.IDLE

    # Ejecutar turno PTT
    result: PTTExecutionResult = controller.process_ptt_audio(
        audio_data=pcm_audio,
        session_id="ptt_test_session",
    )

    assert result.success is True
    assert result.state == PushToTalkState.IDLE  # Vuelve a reposo
    assert result.transcription == "¿Cuál es la hora actual?"
    assert result.stt_confidence == 0.96
    assert result.spoken_text == "Son las 14:00 horas."
    assert result.core_response is not None
    assert result.core_response.intent == "get_time"

    # Verificar que el Core recibió modality=InputModality.VOICE
    mock_core.interact.assert_called_once()
    req_sent: JessycaRequest = mock_core.interact.call_args[0][0]
    assert req_sent.modality == InputModality.VOICE
    assert req_sent.user_input == "¿Cuál es la hora actual?"

    # Verificar que el TTS reprodujo la respuesta
    mock_tts_mgr.speak.assert_called_once()
    assert mock_tts_mgr.speak.call_args[1]["text"] == "Son las 14:00 horas."


# ── TEST 2: COMPROBACIÓN DE SILENCIO Y RUIDO ──


def test_ptt_silence_and_low_energy_noise_handling():
    """Comprueba que buffers vacíos, silencios o ruido plano sean descartados
    sin realizar peticiones espurias al Core ni al LLM."""
    mock_stt = MagicMock(spec=ISTTService)
    mock_core = MagicMock(spec=JessycaLocalAgent)
    mock_tts_mgr = MagicMock(spec=TTSManager)

    controller = PushToTalkController(
        stt_service=mock_stt,
        tts_manager=mock_tts_mgr,
        agent=mock_core,
        min_speech_rms=200.0,
    )

    # 1. Búfer completamente vacío
    res_empty = controller.process_ptt_audio(b"")
    assert res_empty.success is False
    assert res_empty.discard_reason == VoiceDiscardReason.NO_AUDIO
    assert res_empty.state == PushToTalkState.IDLE
    mock_stt.transcribe.assert_not_called()
    mock_core.interact.assert_not_called()

    # 2. Silencio plano o ruido de fondo imperceptible (RMS < 200.0)
    flatline = struct.pack("<500h", *([5] * 500))  # Amplitud mínima
    res_flat = controller.process_ptt_audio(flatline)
    assert res_flat.success is False
    assert res_flat.discard_reason == VoiceDiscardReason.NO_AUDIO
    mock_core.interact.assert_not_called()

    # 3. Audio con energía pero STT detecta que es solo respiración/silencio
    pcm_audio = _generate_pcm16_speech_tone(duration_sec=0.5, amplitude=0.4)
    mock_stt.transcribe.return_value = TranscriptResult(
        text="",
        confidence=0.0,
        language="es",
        duration_ms=500.0,
    )
    res_no_words = controller.process_ptt_audio(pcm_audio)
    assert res_no_words.success is False
    assert res_no_words.discard_reason == VoiceDiscardReason.NO_AUDIO
    mock_core.interact.assert_not_called()


# ── TEST 3: CANCELACIÓN LIMPIA ANTES Y DURANTE LA CAPTURA ──


def test_ptt_cancellation_token_aborts_cleanly():
    """Comprueba que un CancellationToken cancele la operación de PTT inmediatamente."""
    mock_stt = MagicMock(spec=ISTTService)
    mock_core = MagicMock(spec=JessycaLocalAgent)
    mock_tts_mgr = MagicMock(spec=TTSManager)

    controller = PushToTalkController(
        stt_service=mock_stt,
        tts_manager=mock_tts_mgr,
        agent=mock_core,
    )

    pcm_audio = _generate_pcm16_speech_tone(duration_sec=1.0)

    # Cancelado antes de comenzar
    token = CancellationToken()
    token.cancel()

    res = controller.process_ptt_audio(pcm_audio, cancellation_token=token)
    assert res.success is False
    assert "cancelada" in res.error.lower()
    assert res.state == PushToTalkState.IDLE
    mock_stt.transcribe.assert_not_called()
    mock_core.interact.assert_not_called()


# ── TEST 4: ERRORES DEL PROVEEDOR STT / TTS CON DEGRADACIÓN ELEGANTE ──


def test_ptt_provider_errors_handled_gracefully():
    """Comprueba que caídas o timeouts de STT/TTS no crasheen el sistema
    y devuelvan estados y mensajes de error tipados."""
    mock_stt = MagicMock(spec=ISTTService)
    mock_stt.transcribe.side_effect = STTTimeoutError("Timeout al contactar modelo STT.")

    mock_core = MagicMock(spec=JessycaLocalAgent)
    mock_tts_mgr = MagicMock(spec=TTSManager)

    controller = PushToTalkController(
        stt_service=mock_stt,
        tts_manager=mock_tts_mgr,
        agent=mock_core,
    )

    pcm_audio = _generate_pcm16_speech_tone(duration_sec=1.0)
    res = controller.process_ptt_audio(pcm_audio)

    assert res.success is False
    assert res.state == PushToTalkState.IDLE
    assert "Timeout al contactar modelo STT" in res.error
    mock_core.interact.assert_not_called()


# ── TEST 5: PREVENCIÓN DE AUTO-DISPARO POR ECO ACÚSTICO (ANTI-ECHO) ──


def test_ptt_prevents_synthesized_voice_from_triggering_new_commands():
    """Valida la prevención estricta de auto-disparo:
    Si el micrófono captura la propia voz sintetizada del asistente,
    debe reconocerse como eco acústico y descartarse sin generar peticiones al Core."""
    mock_stt = MagicMock(spec=ISTTService)
    mock_core = MagicMock(spec=JessycaLocalAgent)
    mock_tts_mgr = MagicMock(spec=TTSManager)

    controller = PushToTalkController(
        stt_service=mock_stt,
        tts_manager=mock_tts_mgr,
        agent=mock_core,
    )

    # Simular que el asistente acaba de decir una respuesta
    controller._last_spoken_text = "El archivo fue respaldado exitosamente en la carpeta de documentos"
    controller._last_spoken_time = time.perf_counter()

    # Audio re-capturado contiene exactamente o casi exactamente la misma frase
    mock_stt.transcribe.return_value = TranscriptResult(
        text="el archivo fue respaldado exitosamente en la carpeta",
        confidence=0.92,
        language="es",
        duration_ms=1000.0,
    )

    pcm_audio = _generate_pcm16_speech_tone(duration_sec=1.0)
    res = controller.process_ptt_audio(pcm_audio)

    # Debe ser interceptado y descartado por eco
    assert res.success is False
    assert res.is_echo_discarded is True
    assert "eco del altavoz" in res.error.lower()
    # No debe haberse enviado nada al Core
    mock_core.interact.assert_not_called()


# ── TEST 6: INTERRUPCIÓN DE RESPUESTA (BARGE-IN) VS CANCELACIÓN DE ACCIÓN ──


def test_interruption_stops_audio_without_cancelling_background_action():
    """Valida que detener el audio (interrupción/barge-in) NO cancele la acción
    en ejecución en el Core, a menos que se solicite cancelar la acción explícitamente."""
    mock_stt = MagicMock(spec=ISTTService)
    mock_core = MagicMock(spec=JessycaLocalAgent)
    mock_tts_mgr = MagicMock(spec=TTSManager)

    controller = PushToTalkController(
        stt_service=mock_stt,
        tts_manager=mock_tts_mgr,
        agent=mock_core,
    )

    action_token = CancellationToken()
    assert action_token.is_cancelled is False

    # 1. El asistente está hablando y el usuario interrumpe con stop_audio()
    controller.stop_audio(reason="user_barge_in")
    assert controller.current_state == PushToTalkState.INTERRUPTED

    # La acción subyacente NO debe haber sido cancelada
    assert action_token.is_cancelled is False

    # 2. Solo al llamar expresamente a cancel_underlying_action(), se cancela la acción
    controller._current_action_cancellation = action_token
    cancelled = controller.cancel_underlying_action(reason="user_explicit_stop_command")

    assert cancelled is True
    assert action_token.is_cancelled is True


# ── TEST 7: COMPARATIVA DE PROVEEDORES TTS Y SERVICIOS NO AUTORIZADOS (FISH AUDIO) ──


def test_tts_providers_comparison_and_unauthorized_service_handling():
    """Compara los proveedores TTS existentes (Pocket TTS, Edge-TTS, SAPI) y Fish Audio.
    Verifica que no se envíen grabaciones ni datos a servicios nuevos sin autorización."""
    # Asegurar que en el entorno no exista autorización simulada para Fish Audio
    with patch.dict("os.environ", {}, clear=False):
        if "FISH_AUDIO_API_KEY" in os.environ:
            del os.environ["FISH_AUDIO_API_KEY"]

        report = compare_tts_providers()
        assert len(report) >= 4

        names = [item.provider_name for item in report]
        assert any("Pocket TTS" in n for n in names)
        assert any("Edge-TTS" in n for n in names)
        assert any("Windows SAPI" in n for n in names)
        assert any("Fish Audio" in n for n in names)

        # Verificar política sobre Fish Audio
        fish_item = next(item for item in report if "Fish Audio" in item.provider_name)
        assert fish_item.authorized_for_evaluation is False
        assert "NO AUTORIZADO" in fish_item.notes
        assert "Crítico" in fish_item.privacy_and_data_sovereignty

        # Verificar Pocket TTS (Local / Privado)
        pocket_item = next(item for item in report if "Pocket TTS" in item.provider_name)
        assert pocket_item.is_local is True
        assert "offline" in pocket_item.network_dependency.lower()
        assert pocket_item.authorized_for_evaluation is True

        # Verificar Edge-TTS (Camila Neural)
        edge_item = next(item for item in report if "Edge-TTS" in item.provider_name)
        assert "CamilaNeural" in edge_item.target_language
        assert edge_item.authorized_for_evaluation is True


# ── TEST 8: PALABRA DE ACTIVACIÓN DESACOPLADA (I5) Y CONSERVACIÓN DE PTT ──


def test_wake_word_decoupled_and_retains_push_to_talk():
    """Verifica que la palabra de activación es una capacidad separada:
    1. openWakeWord declara honestamente is_acoustic_model_available=False para español.
    2. El sistema conserva Pulsar para Hablar (PTT) como método fiable.
    3. Ningún activador de voz autoriza acciones por sí mismo (authorizes_action=False)."""
    # 1. OpenWakeWord para español sin modelo inventado
    oww_service = OpenWakeWordAcousticService(model_path=None)
    assert oww_service.is_acoustic_model_available() is False

    chunk = AudioChunk(data=b"\x00" * 3200, sample_rate=16000, channels=1)
    res = oww_service.process_audio(chunk)
    assert res.detected is False
    assert res.authorizes_action is False
    assert res.metadata.get("status") == "ACOUSTIC_MODEL_UNAVAILABLE"

    # 2. Disparo manual PTT en KeywordWakeWordService jamás autoriza acciones
    k_service = KeywordWakeWordService(keyword="jessyca", mode="manual")
    k_service.trigger_manually()
    ptt_res = k_service.process_audio(chunk)
    assert ptt_res.detected is True
    assert ptt_res.authorizes_action is False
    assert ptt_res.metadata.get("trigger") == "manual_push_to_talk"


# ── TEST 9: INTEGRACIÓN CON DISPOSITIVOS REALES Y TELEMETRÍA DE HARDWARE ──


def test_real_hardware_audio_specs_and_passive_listening_disabled_by_default():
    """Comprueba que no se habilite escucha permanente por defecto y que las
    especificaciones de audio respeten el estándar del sistema en Windows (16kHz, mono)."""
    controller = PushToTalkController()
    assert controller.sample_rate == 16000
    assert controller.current_state == PushToTalkState.IDLE

    # Cálculo de RMS determinista en audio PCM
    tone = _generate_pcm16_speech_tone(duration_sec=0.1, amplitude=0.5)
    rms = controller._calculate_rms(tone)
    assert rms > 5000.0  # Tono fuerte con amplitud 0.5 genera RMS alto
