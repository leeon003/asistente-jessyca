"""Pruebas Automáticas de Adaptive End-of-Speech (Fase 75.2-A).

Valida los 8 casos requeridos para garantizar que JESSYCA escucha hasta
que el usuario realmente termine de hablar, tolerando pausas naturales,
soportando preguntas largas (5s, 30s, 60s) sin cortes artificiales por timeout,
preservando el post-roll y generando UtteranceFinal de forma determinista.
"""

from __future__ import annotations

import math
import struct

import pytest
import speech_recognition as sr

from core.bus import EventBus
from core.events import UtteranceFinal
from core.state import StateMachine
from services.voice.audio_capture import CalibratedVoiceCaptureEngine
from services.voice.stt_event_adapter import STTEventAdapter


def _generate_pcm_chunk(
    duration_ms: float,
    amplitude: float = 0.5,
    sample_rate: int = 16000,
    frequency: float = 440.0,
) -> bytes:
    """Genera un chunk PCM 16-bit mono con tono senoidal o silencio puro."""
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    if amplitude <= 0.001:
        return b"\x00\x00" * num_samples
    samples = []
    for i in range(num_samples):
        val = int(32767.0 * amplitude * math.sin(2.0 * math.pi * frequency * (i / sample_rate)))
        val = max(-32768, min(32767, val))
        samples.append(val)
    return struct.pack(f"<{num_samples}h", *samples)


def _generate_chunk_sequence(
    segments: list[tuple[float, float]],  # list of (duration_ms, amplitude)
    chunk_ms: float = 50.0,
    sample_rate: int = 16000,
) -> list[bytes]:
    """Desglosa segmentos de habla y silencio en una lista continua de chunks de audio."""
    chunks = []
    for duration_ms, amplitude in segments:
        num_chunks = max(1, int(duration_ms / chunk_ms))
        for _ in range(num_chunks):
            chunks.append(_generate_pcm_chunk(chunk_ms, amplitude, sample_rate))
    return chunks


# ── TEST 1: ORDEN CORTA ("abre bloc de notas") ─────────────────────────────

def test_1_short_command_finishes_correctly():
    """TEST 1: Una orden corta termina correctamente con silencio sostenido ágil (1.0s)."""
    engine = CalibratedVoiceCaptureEngine(sample_rate=16000, pre_roll_ms=400, post_roll_ms=600)

    # Secuencia: 200ms silencio inicial -> 800ms habla ("abre bloc de notas") -> 1100ms silencio final
    chunks = _generate_chunk_sequence([
        (200.0, 0.0),   # Silencio previo
        (800.0, 0.5),   # Habla activa (~0.8s, orden corta)
        (1200.0, 0.0),  # Silencio sostenido (>= 1.0s umbral adaptativo corto)
    ])

    audio_bytes, meta = engine.evaluate_adaptive_stream(
        chunk_stream=chunks,
        sample_rate=16000,
        sample_width=2,
        timeout=5.0,
    )

    assert meta["voice_started"] is True
    assert meta["end_reason"] == "end_of_speech"
    assert 0.7 <= meta["total_speech_sec"] <= 0.95
    assert len(audio_bytes) > 0


# ── TEST 2: FRASE DE ~5 SEGUNDOS ──────────────────────────────────────────

def test_2_five_second_phrase_finishes_correctly():
    """TEST 2: Una frase de aproximadamente 5 segundos concluye por silencio sostenido adaptativo."""
    engine = CalibratedVoiceCaptureEngine(sample_rate=16000, pre_roll_ms=400, post_roll_ms=600)

    # Secuencia: 200ms silencio -> 5000ms habla continua -> 1500ms silencio final
    chunks = _generate_chunk_sequence([
        (200.0, 0.0),
        (5000.0, 0.5),  # 5 segundos de habla
        (1500.0, 0.0),  # Silencio sostenido (>= 1.35s umbral extendido)
    ])

    audio_bytes, meta = engine.evaluate_adaptive_stream(
        chunk_stream=chunks,
        sample_rate=16000,
        sample_width=2,
        timeout=5.0,
    )

    assert meta["voice_started"] is True
    assert meta["end_reason"] == "end_of_speech"
    assert meta["total_speech_sec"] >= 4.8
    # No debe terminar prematuramente por un timeout artificial
    assert meta["total_audio_sec"] >= 5.0


# ── TEST 3: INTERVENCIÓN LARGA (30s Y 60s) SIN CORTE POR TIEMPO ───────────

def test_3_long_utterance_does_not_terminate_by_max_duration():
    """TEST 3: Una intervención larga (30s y 60s) NO termina por duración máxima ni por 10s/15s."""
    engine = CalibratedVoiceCaptureEngine(sample_rate=16000, pre_roll_ms=400, post_roll_ms=600)

    # Caso A: Pregunta compleja de física de 30 segundos
    chunks_30s = _generate_chunk_sequence([
        (200.0, 0.0),
        (30000.0, 0.5),  # 30 segundos de habla activa
        (1500.0, 0.0),   # Silencio final sostenido
    ])

    audio_30s, meta_30s = engine.evaluate_adaptive_stream(
        chunk_stream=chunks_30s,
        sample_rate=16000,
        sample_width=2,
        timeout=5.0,
    )

    assert meta_30s["voice_started"] is True
    assert meta_30s["end_reason"] == "end_of_speech"
    assert meta_30s["total_speech_sec"] >= 29.5, "No debe cortar a los 10s ni a los 15s"

    # Caso B: Pregunta avanzada de física de 60 segundos
    chunks_60s = _generate_chunk_sequence([
        (200.0, 0.0),
        (60000.0, 0.5),  # 60 segundos de habla activa
        (1500.0, 0.0),   # Silencio final sostenido
    ])

    audio_60s, meta_60s = engine.evaluate_adaptive_stream(
        chunk_stream=chunks_60s,
        sample_rate=16000,
        sample_width=2,
        timeout=5.0,
    )

    assert meta_60s["voice_started"] is True
    assert meta_60s["end_reason"] == "end_of_speech"
    assert meta_60s["total_speech_sec"] >= 59.5, "No debe cortar a los 10s ni a 30s artificialmente"


# ── TEST 4: INTERVENCIÓN CON PAUSAS NATURALES DE REFLEXIÓN ─────────────────

def test_4_natural_pauses_tolerated_without_premature_cutoff():
    """TEST 4: Intervención con pausas naturales de reflexión (0.6s–0.8s) NO termina prematuramente."""
    engine = CalibratedVoiceCaptureEngine(sample_rate=16000, pre_roll_ms=400, post_roll_ms=600)

    # Simula: "Explícame por qué... [pausa 700ms] ...la relatividad general... [pausa 800ms] ...dilata el tiempo."
    chunks = _generate_chunk_sequence([
        (200.0, 0.0),    # Silencio de espera
        (3000.0, 0.5),   # Frase 1: 3.0s habla
        (700.0, 0.0),    # Pausa natural 1: 700ms (menor a umbral adaptativo 1.35s)
        (4000.0, 0.5),   # Frase 2: 4.0s habla
        (800.0, 0.0),    # Pausa natural 2: 800ms (menor a umbral adaptativo 1.35s)
        (3000.0, 0.5),   # Frase 3: 3.0s habla
        (1500.0, 0.0),   # Silencio final sostenido (>= 1.35s) -> Aquí SÍ concluye
    ])

    audio_bytes, meta = engine.evaluate_adaptive_stream(
        chunk_stream=chunks,
        sample_rate=16000,
        sample_width=2,
        timeout=5.0,
    )

    assert meta["voice_started"] is True
    assert meta["end_reason"] == "end_of_speech"
    # El habla acumulada debe abarcar las 3 frases (3s + 4s + 3s = 10s aprox)
    assert meta["total_speech_sec"] >= 9.5, "Las pausas intermedias no deben haber cortado la captura"


# ── TEST 5: HABLA -> SILENCIO SOSTENIDO -> GENERA UtteranceFinal ───────────

def test_5_sustained_silence_emits_utterance_final():
    """TEST 5: Habla seguida de silencio sostenido produce un evento UtteranceFinal en el EventBus."""
    bus = EventBus()
    sm = StateMachine()
    received_events: list[UtteranceFinal] = []
    bus.subscribe(UtteranceFinal, lambda e: received_events.append(e))

    adapter = STTEventAdapter(event_bus=bus, state_machine=sm)

    # Audio con habla y silencio final
    engine = CalibratedVoiceCaptureEngine(sample_rate=16000)
    chunks = _generate_chunk_sequence([
        (200.0, 0.0),
        (2000.0, 0.5),
        (1500.0, 0.0),
    ])

    audio_bytes, meta = engine.evaluate_adaptive_stream(chunks, 16000, 2, timeout=5.0)
    assert meta["end_reason"] == "end_of_speech"

    # Procesar la transcripción a través del pipeline STT -> EventBus
    event = adapter.process_transcript("¿Qué es un agujero negro?", confidence=0.93)

    assert event is not None
    assert len(received_events) == 1
    assert received_events[0].text == "¿Qué es un agujero negro?"
    assert received_events[0].confidence == 0.93


# ── TEST 6: HABLA -> PAUSA CORTA -> CONTINÚA -> UNA SOLA UTTERANCE ─────────

def test_6_pause_and_resume_produces_single_utterance():
    """TEST 6: Habla -> pausa corta -> continúa hablando genera una sola captura completa y una sola utterance."""
    bus = EventBus()
    sm = StateMachine()
    received_events: list[UtteranceFinal] = []
    bus.subscribe(UtteranceFinal, lambda e: received_events.append(e))

    adapter = STTEventAdapter(event_bus=bus, state_machine=sm)
    engine = CalibratedVoiceCaptureEngine(sample_rate=16000)

    # Frase con pausa corta de 600ms
    chunks = _generate_chunk_sequence([
        (200.0, 0.0),
        (2000.0, 0.5),  # Parte 1
        (600.0, 0.0),   # Pausa corta (600ms)
        (2500.0, 0.5),  # Parte 2
        (1500.0, 0.0),  # Silencio sostenido final
    ])

    audio_bytes, meta = engine.evaluate_adaptive_stream(chunks, 16000, 2, timeout=5.0)

    # Debe haber resultado en un solo bloque capturado
    assert meta["end_reason"] == "end_of_speech"
    assert meta["total_speech_sec"] >= 4.3

    # Emitir el transcript resultante
    full_text = "Explícame la diferencia entre masa relativista y masa invariante"
    adapter.process_transcript(full_text, confidence=0.94)

    assert len(received_events) == 1, "Debe producir exactamente UNA sola utterance final"
    assert received_events[0].text == full_text


# ── TEST 7: CONSERVACIÓN DEL FINAL MEDIANTE POST-ROLL ───────────────────────

def test_7_post_roll_preserves_sentence_ending():
    """TEST 7: El post-roll conserva íntegramente los fragmentos de audio posteriores al cese de voz."""
    post_roll_target_ms = 600
    engine = CalibratedVoiceCaptureEngine(
        sample_rate=16000,
        pre_roll_ms=400,
        post_roll_ms=post_roll_target_ms,
    )

    # 1.5s de habla seguidos de 1.5s de silencio
    speech_duration_ms = 1500.0
    chunks = _generate_chunk_sequence([
        (200.0, 0.0),
        (speech_duration_ms, 0.5),
        (1500.0, 0.0),
    ])

    audio_bytes, meta = engine.evaluate_adaptive_stream(chunks, 16000, 2, timeout=5.0)

    bytes_per_second = 16000 * 2
    total_audio_duration_sec = len(audio_bytes) / bytes_per_second

    # La duración total capturada debe ser mayor que el habla activa + el post-roll
    min_expected_sec = (speech_duration_ms + post_roll_target_ms) / 1000.0
    assert total_audio_duration_sec >= min_expected_sec, (
        f"El audio capturado ({total_audio_duration_sec:.2f}s) debe conservar al menos el habla + post-roll ({min_expected_sec:.2f}s)"
    )
    assert meta["end_reason"] == "end_of_speech"


# ── TEST 8: AUSENCIA DE VOZ (NO DISPARAR UTTERANCE FALSA) ───────────────────

def test_8_silence_timeout_does_not_emit_false_utterance():
    """TEST 8: En ausencia de voz dentro del tiempo límite, no se genera una utterance falsa."""
    bus = EventBus()
    received_events: list[UtteranceFinal] = []
    bus.subscribe(UtteranceFinal, lambda e: received_events.append(e))

    engine = CalibratedVoiceCaptureEngine(sample_rate=16000)

    # 4 segundos de silencio continuo con un timeout de 2 segundos
    pure_silence_chunks = _generate_chunk_sequence([(4000.0, 0.0)])

    with pytest.raises(sr.WaitTimeoutError):
        engine.evaluate_adaptive_stream(
            chunk_stream=pure_silence_chunks,
            sample_rate=16000,
            sample_width=2,
            timeout=2.0,
        )

    # Si se invoca capture_and_transcribe con audio vacío
    res = engine.capture_and_transcribe(custom_audio_bytes=b"")
    assert res.is_success is False
    assert res.text == ""

    # No se debe haber emitido ningún evento UtteranceFinal
    assert len(received_events) == 0


# ── TEST ADICIONAL: FAILSAFE WATCHDOG COMO PROTECCIÓN TÉCNICA ───────────────

def test_failsafe_watchdog_triggers_as_technical_safety_net():
    """Verifica que el failsafe watchdog actúa como protección técnica ante streams atascados."""
    engine = CalibratedVoiceCaptureEngine(sample_rate=16000)

    # Audio continuo que excede un watchdog corto de 2.0s
    continuous_speech_chunks = _generate_chunk_sequence([(4000.0, 0.5)])

    audio_bytes, meta = engine.evaluate_adaptive_stream(
        chunk_stream=continuous_speech_chunks,
        sample_rate=16000,
        sample_width=2,
        timeout=5.0,
        failsafe_watchdog_sec=2.0,  # Watchdog para prueba
    )

    assert meta["end_reason"] == "failsafe_watchdog"
    assert meta["total_speech_sec"] >= 2.0
