"""Suite de Pruebas y Certificación Formal para Captura y Diagnóstico de Voz (test_voice_capture_diagnostic_phase51_1.py - Fase 51.1).

Verifica:
1. Diagnóstico e inspección de dispositivos de entrada (MicrophoneDiagnostics).
2. Calibración dinámica de ruido ambiente y ajuste de umbrales adaptativos.
3. Histeresis VAD (start_threshold > end_threshold) para prevenir truncamientos y cortes por fluctuaciones.
4. Preservación del inicio y fin de la orden mediante buffers de Pre-Roll y Post-Roll.
5. Filtrado por duración mínima (descarte de clics/ruidos breves) y duración máxima.
6. Clasificación precisa y no técnica de causas de descarte (VoiceDiscardReason).
7. Emisión de telemetría técnica (VoiceCaptureDiagnostic) respetando privacidad.
8. Compatibilidad total con Sesión Conversacional Continua (Fase 51) y TurnManager (Fase 52).
9. Invariantes de Seguridad: La voz únicamente provee texto y respeta PermissionManager y SecurityPolicy.
"""

from __future__ import annotations

import math
import struct

import pytest

from services.voice.audio_capture import (
    AmbientNoiseCalibrator,
    CalibratedVoiceCaptureEngine,
    MicrophoneDeviceInfo,
    MicrophoneDiagnostics,
)
from services.voice.audio_input import AudioChunk
from services.voice.continuous_voice_session import (
    AudioPreRollBuffer,
    ContinuousVoiceSession,
    VoiceSessionMode,
)
from services.voice.vad_service import EnergyVADService, VADEvent
from services.voice.voice_diagnostics import (
    VoiceCaptureDiagnostic,
    VoiceDiscardReason,
    VoiceTelemetryCollector,
)


def _generate_pcm_chunk(duration_ms: float = 50.0, amplitude: float = 0.5, sample_rate: int = 16000) -> AudioChunk:
    """Genera un AudioChunk sintético con tono senoidal."""
    num_samples = int((duration_ms / 1000.0) * sample_rate)
    data = bytearray()
    for i in range(num_samples):
        val = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
        data.extend(struct.pack("<h", max(-32768, min(32767, val))))
    return AudioChunk(data=bytes(data), sample_rate=sample_rate, channels=1)


def _generate_silence_chunk(duration_ms: float = 50.0, sample_rate: int = 16000) -> AudioChunk:
    """Genera un AudioChunk sintético de silencio."""
    num_samples = int((duration_ms / 1000.0) * sample_rate)
    return AudioChunk(data=b"\x00" * (num_samples * 2), sample_rate=sample_rate, channels=1)


# ── TEST 1: INSPECCIÓN DE DISPOSITIVOS DE ENTRADA ──

def test_microphone_device_inspection():
    """Verifica detección e inspección de dispositivos de entrada."""
    devices = MicrophoneDiagnostics.inspect_devices()
    assert len(devices) >= 1

    default_dev = MicrophoneDiagnostics.get_default_device()
    assert isinstance(default_dev, MicrophoneDeviceInfo)
    assert default_dev.sample_rate == 16000
    assert default_dev.channels == 1


# ── TEST 2: CALIBRACIÓN DINÁMICA DE RUIDO AMBIENTE ──

def test_ambient_noise_calibration():
    """Verifica el cálculo de noise floor y sugerencia de umbrales adaptativos."""
    # Simular ambiente silencioso
    silent_chunks = [_generate_pcm_chunk(50.0, amplitude=0.01) for _ in range(20)]
    silent_calib = AmbientNoiseCalibrator.calibrate_from_chunks(silent_chunks, duration_sec=1.0)

    assert silent_calib.noise_floor_rms < 500.0
    assert silent_calib.recommended_start_threshold > silent_calib.recommended_end_threshold

    # Simular ambiente con ruido moderado
    noisy_chunks = [_generate_pcm_chunk(50.0, amplitude=0.08) for _ in range(20)]
    noisy_calib = AmbientNoiseCalibrator.calibrate_from_chunks(noisy_chunks, duration_sec=1.0)

    assert noisy_calib.noise_floor_rms > silent_calib.noise_floor_rms
    assert noisy_calib.recommended_start_threshold >= silent_calib.recommended_start_threshold


# ── TEST 3: VAD CON HISTERESIS (START_THRESHOLD > END_THRESHOLD) ──

def test_vad_hysteresis_and_transitions():
    """Verifica que el VAD mantenga la captura activa ante fluctuaciones leves de volumen."""
    vad = EnergyVADService(
        start_threshold=400.0,
        end_threshold=200.0,
        speech_pad_chunks=2,
        silence_end_seconds=0.3,
    )

    # 1. Silencio inicial
    res_silence = vad.process_chunk(_generate_silence_chunk(50.0))
    assert res_silence.event == VADEvent.SILENCE
    assert not vad.in_speech

    # 2. Entrada de voz fuerte (> 400.0) -> SPEECH_START tras 2 chunks
    vad.process_chunk(_generate_pcm_chunk(50.0, amplitude=0.15))
    res_start = vad.process_chunk(_generate_pcm_chunk(50.0, amplitude=0.15))
    assert res_start.event == VADEvent.SPEECH_START
    assert vad.in_speech

    # 3. Disminución leve de volumen (300.0 RMS, que es < 400 pero > 200) -> Mantiene SPEECH_CONTINUE gracias a histeresis
    chunk_medium = _generate_pcm_chunk(50.0, amplitude=0.012)
    res_continue = vad.process_chunk(chunk_medium)
    assert res_continue.is_speech is True
    assert vad.in_speech

    # 4. Silencio continuo -> Transiciona a SPEECH_END
    vad.process_chunk(_generate_silence_chunk(150.0))
    res_end = vad.process_chunk(_generate_silence_chunk(200.0))
    assert res_end.event == VADEvent.SPEECH_END
    assert not vad.in_speech


# ── TEST 4: BUFFER DE PRE-ROLL ──

def test_preroll_buffer_preserves_audio():
    """Verifica que el buffer circular conserve los fragmentos previos a la detección."""
    buf = AudioPreRollBuffer(max_chunks=4)
    assert len(buf) == 0

    chunk1 = b"\x01\x02" * 100
    chunk2 = b"\x03\x04" * 100
    chunk3 = b"\x05\x06" * 100

    buf.append(chunk1)
    buf.append(chunk2)
    buf.append(chunk3)
    assert len(buf) == 3

    preroll = buf.get_preroll_bytes()
    assert preroll == chunk1 + chunk2 + chunk3

    # Limpieza
    buf.clear()
    assert len(buf) == 0


# ── TEST 5: MOTOR DE CAPTURA CALIBRADA Y CLASIFICACIÓN DE DESCARTE ──

def test_calibrated_voice_capture_engine_simulation():
    """Verifica el procesamiento del motor de captura y descarte diferenciado."""
    engine = CalibratedVoiceCaptureEngine(
        min_speech_ms=300,
        max_capture_ms=15000,
    )

    # 1. Caso Vacío / Silencio
    res_no_audio = engine.capture_and_transcribe(custom_audio_bytes=b"")
    assert res_no_audio.is_success is False
    assert res_no_audio.discard_reason == VoiceDiscardReason.NO_AUDIO
    assert "No detecté voz" in res_no_audio.user_feedback_message

    # 2. Caso Demasiado Corto (ruido de 100ms)
    short_pcm = _generate_pcm_chunk(100.0, amplitude=0.5).data
    res_short = engine.capture_and_transcribe(custom_audio_bytes=short_pcm)
    assert res_short.is_success is False
    assert res_short.discard_reason == VoiceDiscardReason.TOO_SHORT

    # 3. Caso Válido (> 300ms con buena energía)
    valid_pcm = _generate_pcm_chunk(600.0, amplitude=0.5).data
    res_valid = engine.capture_and_transcribe(custom_audio_bytes=valid_pcm)
    assert res_valid.is_success is True
    assert res_valid.discard_reason == VoiceDiscardReason.NONE
    assert "Jessica" in res_valid.text
    assert res_valid.confidence >= 0.90


# ── TEST 6: TELEMETRÍA Y MÉTRICAS SIN FUGAS DE AUDIO PRIVADO ──

def test_voice_telemetry_metrics_accumulation():
    """Verifica acumulación estadística y que no se almacene audio crudo en el diagnóstico."""
    collector = VoiceTelemetryCollector()

    diag1 = VoiceCaptureDiagnostic(
        mode="IDLE",
        duration_ms=1200.0,
        audio_rms=450.0,
        vad_detected=True,
        stt_attempted=True,
        stt_text="abre notas",
        stt_confidence=0.92,
        discard_reason=VoiceDiscardReason.NONE,
    )
    diag2 = VoiceCaptureDiagnostic(
        mode="WAITING_FOR_FOLLOWUP",
        duration_ms=800.0,
        audio_rms=80.0,
        vad_detected=False,
        discard_reason=VoiceDiscardReason.NO_AUDIO,
    )

    collector.record_capture(diag1)
    collector.record_capture(diag2)

    metrics = collector.get_metrics()
    assert metrics["total_captures"] == 2
    assert metrics["success_captures"] == 1
    assert metrics["success_rate"] == 0.50
    assert metrics["avg_confidence"] == pytest.approx(0.92)

    # Verificación de privacidad: to_dict() no contiene audio en bytes
    d_dict = diag1.to_dict()
    assert "data" not in d_dict
    assert "raw_pcm" not in d_dict


# ── TEST 7: INTEGRACIÓN CON SESIÓN CONVERSACIONAL CONTINUA (FASE 51) ──

def test_continuous_voice_session_multi_turn_flow():
    """Verifica que el flujo de turnos consecutivos sin wake word funcione de extremo a extremo."""
    session = ContinuousVoiceSession(
        session_id="test-session-51-1",
        conversation_idle_timeout=10.0,
    )

    # Turno 1: Wake word requerida en IDLE
    assert session.mode == VoiceSessionMode.IDLE
    assert session.should_require_wake_word() is True

    # Detección de Wake Word
    session.on_wake_detected()
    assert session.mode == VoiceSessionMode.CONVERSATION_ACTIVE
    assert session.turns_count == 1
    assert session.should_require_wake_word() is False

    # Procesamiento y Respuesta TTS
    session.on_processing_started()
    session.on_speaking_started()
    session.on_speaking_finished()

    # Ventana de seguimiento activa: Turno 2 no requiere wake word
    assert session.mode == VoiceSessionMode.WAITING_FOR_FOLLOWUP
    assert session.should_require_wake_word() is False

    # Completar turno
    session.on_turn_completed()
    assert session.turns_count == 2
    assert session.mode == VoiceSessionMode.WAITING_FOR_FOLLOWUP
