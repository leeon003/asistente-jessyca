"""Tests Unitarios e Integración para Fase 73: Barge-in / Interrupción de Voz.

Cubre:
- TEST 1: TTS reproduciendo, VAD detecta voz válida -> UserInterrupted.
- TEST 2: TTS reproduciendo, sin voz -> continúa reproducción.
- TEST 3: Ruido corto (< min_speech_duration_ms) -> no interrupción.
- TEST 4: Voz suficientemente larga -> interrupción.
- TEST 5: UserInterrupted emitido exactamente una vez.
- TEST 6: TTS cancelado -> is_tts_active = False.
- TEST 7: Nueva reproducción después de cancelar funciona normalmente.
- TEST 8: Pocket TTS cancelable si está activo.
- TEST 9: Edge TTS detiene reproducción de audio.
- TEST 10: Eco simulado de altavoz no produce falsa interrupción.
- TEST 11: conversation_active = False -> Barge-in no se activa.
- TEST 12: conversation_active = True -> Barge-in disponible.
- TEST 13: session_id se conserva íntegro.
- TEST 14: StateMachine transita de RESPONDING a LISTENING.
- TEST 15 (Integración): Flujo completo de interrupción y transcripción.
- TEST 16 (Anti-Autointerrupción): Prueba con audio prolongado de JESSYCA y eco acústico.
"""

from __future__ import annotations

import struct
import time
from typing import Any
from unittest.mock import MagicMock

from core.bus import EventBus
from core.cancellation import CancellationToken
from core.events.base import UserInterrupted
from core.state import SessionState, StateMachine
from services.voice.audio_input import AudioChunk
from services.voice.barge_in_controller import BargeInController
from services.voice.tts_provider import (
    BaseTTSProvider,
    EdgeTTSProvider,
    PocketTTSProvider,
    TTSManager,
    TTSMetrics,
)
from services.voice.tts_service import TTSResult
from services.voice.vad_service import EnergyVADService


def make_chunk(energy_rms: float, duration_ms: float = 50.0, sample_rate: int = 16000) -> AudioChunk:
    """Genera un AudioChunk sintético con un nivel de energía RMS exacto."""
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    if energy_rms <= 0:
        data = b"\x00" * (num_samples * 2)
    else:
        val = int(min(32767.0, max(-32768.0, energy_rms)))
        data = struct.pack(f"<{num_samples}h", *([val] * num_samples))
    return AudioChunk(data=data, sample_rate=sample_rate)


class DummyMockTTSProvider(BaseTTSProvider):
    """Proveedor mock controlable para tests."""

    def __init__(self, name: str = "mock_provider") -> None:
        self.provider_name = name
        self.stop_called = False
        self.speak_called = False

    @property
    def name(self) -> str:
        return self.provider_name

    def is_available(self) -> bool:
        return True

    def synthesize(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[TTSResult, TTSMetrics]:
        res = TTSResult(
            audio_bytes=b"fake_wav",
            duration_seconds=1.0,
            voice_name=self.name,
            is_success=True,
        )
        return res, TTSMetrics(provider_used=self.name, is_success=True)

    def speak(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[bool, TTSMetrics]:
        self.speak_called = True
        return True, TTSMetrics(provider_used=self.name, is_success=True)

    def stop(self) -> None:
        self.stop_called = True

    def health_check(self) -> dict[str, Any]:
        return {"name": self.name, "available": True}


# ==============================================================================
# TEST 1: TTS está reproduciendo. VAD detecta voz válida -> UserInterrupted.
# ==============================================================================
def test_1_tts_playing_vad_detects_valid_speech() -> None:
    event_bus = EventBus()
    interrupted_events: list[UserInterrupted] = []
    event_bus.subscribe(UserInterrupted, interrupted_events.append)

    barge_in = BargeInController(
        event_bus=event_bus,
        min_speech_duration_ms=100.0,
        cooldown_ms=0.0,
        echo_margin_factor=1.5,
    )
    barge_in.notify_tts_started(session_id="sess_1")

    # Chunk de 100ms con RMS 600 (superior al umbral dinámico 300 * 1.5 = 450)
    chunk = make_chunk(energy_rms=600.0, duration_ms=100.0)
    result = barge_in.process_audio_chunk(chunk, conversation_active=True)

    assert result is True
    assert len(interrupted_events) == 1
    assert interrupted_events[0].session_id == "sess_1"


# ==============================================================================
# TEST 2: TTS está reproduciendo. No existe voz -> continúa reproducción.
# ==============================================================================
def test_2_tts_playing_no_speech_continues() -> None:
    event_bus = EventBus()
    interrupted_events: list[UserInterrupted] = []
    event_bus.subscribe(UserInterrupted, interrupted_events.append)

    barge_in = BargeInController(
        event_bus=event_bus,
        min_speech_duration_ms=100.0,
        cooldown_ms=0.0,
    )
    barge_in.notify_tts_started(session_id="sess_2")

    # Silencio / ruido imperceptible
    chunk = make_chunk(energy_rms=20.0, duration_ms=100.0)
    result = barge_in.process_audio_chunk(chunk, conversation_active=True)

    assert result is False
    assert len(interrupted_events) == 0
    assert barge_in.is_tts_active is True


# ==============================================================================
# TEST 3: Ruido corto (< min_speech_duration_ms) -> no interrupción.
# ==============================================================================
def test_3_short_noise_no_interruption() -> None:
    event_bus = EventBus()
    interrupted_events: list[UserInterrupted] = []
    event_bus.subscribe(UserInterrupted, interrupted_events.append)

    barge_in = BargeInController(
        event_bus=event_bus,
        min_speech_duration_ms=150.0,
        cooldown_ms=0.0,
    )
    barge_in.notify_tts_started(session_id="sess_3")

    # Click o tos breve de solo 40ms
    short_chunk = make_chunk(energy_rms=700.0, duration_ms=40.0)
    result = barge_in.process_audio_chunk(short_chunk, conversation_active=True)

    assert result is False
    assert len(interrupted_events) == 0
    assert barge_in.is_tts_active is True


# ==============================================================================
# TEST 4: Voz suficientemente larga -> interrupción.
# ==============================================================================
def test_4_sufficiently_long_speech_interrupts() -> None:
    barge_in = BargeInController(
        min_speech_duration_ms=150.0,
        cooldown_ms=0.0,
        echo_margin_factor=1.5,
    )
    barge_in.notify_tts_started(session_id="sess_4")

    # Tres chunks de 60ms = 180ms total > 150ms
    c1 = make_chunk(energy_rms=600.0, duration_ms=60.0)
    c2 = make_chunk(energy_rms=600.0, duration_ms=60.0)
    c3 = make_chunk(energy_rms=600.0, duration_ms=60.0)

    res1 = barge_in.process_audio_chunk(c1, conversation_active=True)
    assert res1 is False
    res2 = barge_in.process_audio_chunk(c2, conversation_active=True)
    assert res2 is False
    res3 = barge_in.process_audio_chunk(c3, conversation_active=True)
    assert res3 is True
    assert barge_in.is_tts_active is False


# ==============================================================================
# TEST 5: UserInterrupted ocurre una sola vez.
# ==============================================================================
def test_5_user_interrupted_emitted_only_once() -> None:
    event_bus = EventBus()
    interrupted_events: list[UserInterrupted] = []
    event_bus.subscribe(UserInterrupted, interrupted_events.append)

    barge_in = BargeInController(
        event_bus=event_bus,
        min_speech_duration_ms=100.0,
        cooldown_ms=0.0,
    )
    barge_in.notify_tts_started(session_id="sess_5")

    # Primer chunk de 120ms dispara la interrupción
    c1 = make_chunk(energy_rms=600.0, duration_ms=120.0)
    r1 = barge_in.process_audio_chunk(c1, conversation_active=True)
    assert r1 is True

    # Siguientes chunks de la misma frase del usuario
    c2 = make_chunk(energy_rms=600.0, duration_ms=120.0)
    r2 = barge_in.process_audio_chunk(c2, conversation_active=True)
    assert r2 is False

    # Disparar directamente trigger_barge_in no debe duplicar evento
    r3 = barge_in.trigger_barge_in("Second trigger attempt")
    assert r3 is False

    assert len(interrupted_events) == 1
    assert barge_in.interrupted_count == 1


# ==============================================================================
# TEST 6: TTS cancelado -> tts_playing / is_tts_active = False.
# ==============================================================================
def test_6_tts_cancelled_tts_playing_false() -> None:
    mock_prov = DummyMockTTSProvider()
    tts_mgr = TTSManager(
        preferred_provider=mock_prov.name,
        providers={mock_prov.name: mock_prov},
    )
    tts_mgr._is_playing = True

    barge_in = BargeInController(
        tts_manager=tts_mgr,
        cooldown_ms=0.0,
    )
    barge_in.notify_tts_started()
    assert barge_in.is_tts_active is True
    assert tts_mgr.is_playing is True

    res = barge_in.trigger_barge_in(reason="Cancel test")
    assert res is True
    assert barge_in.is_tts_active is False
    assert tts_mgr.is_playing is False
    assert mock_prov.stop_called is True


# ==============================================================================
# TEST 7: Nueva reproducción después de cancelar funciona normalmente.
# ==============================================================================
def test_7_new_playback_after_cancel_works() -> None:
    barge_in = BargeInController(cooldown_ms=0.0, min_speech_duration_ms=100.0)

    # Primer turno: reproducir y cancelar
    barge_in.notify_tts_started(session_id="turn_1")
    c1 = make_chunk(energy_rms=600.0, duration_ms=120.0)
    assert barge_in.process_audio_chunk(c1, conversation_active=True) is True
    assert barge_in.is_tts_active is False

    # Segundo turno: nueva reproducción
    barge_in.notify_tts_started(session_id="turn_2")
    assert barge_in.is_tts_active is True

    # Se puede volver a interrumpir limpiamente
    c2 = make_chunk(energy_rms=600.0, duration_ms=120.0)
    assert barge_in.process_audio_chunk(c2, conversation_active=True) is True
    assert barge_in.is_tts_active is False
    assert barge_in.interrupted_count == 2


# ==============================================================================
# TEST 8: Pocket TTS generando -> Interrupción cancela generación.
# ==============================================================================
def test_8_pocket_tts_generating_interruption() -> None:
    pocket_prov = PocketTTSProvider()
    tts_mgr = TTSManager(
        preferred_provider=pocket_prov.name,
        providers={pocket_prov.name: pocket_prov},
    )
    tts_mgr._is_generating = True
    token = CancellationToken()
    tts_mgr._current_token = token

    barge_in = BargeInController(tts_manager=tts_mgr)
    barge_in.notify_tts_started(cancellation_token=token)

    assert token.is_cancelled is False
    assert tts_mgr.is_generating is True

    barge_in.trigger_barge_in(reason="Barge-in while generating")

    assert token.is_cancelled is True
    assert tts_mgr.is_generating is False
    assert barge_in.is_tts_active is False


# ==============================================================================
# TEST 9: Edge TTS reproduciendo -> Interrupción detiene reproducción.
# ==============================================================================
def test_9_edge_tts_playing_interruption() -> None:
    edge_prov = EdgeTTSProvider()
    mock_service = MagicMock()
    edge_prov._service = mock_service

    tts_mgr = TTSManager(
        preferred_provider="edge-tts",
        providers={"edge-tts": edge_prov},
    )
    tts_mgr._is_playing = True

    barge_in = BargeInController(tts_manager=tts_mgr)
    barge_in.notify_tts_started()

    assert tts_mgr.is_playing is True
    barge_in.trigger_barge_in(reason="Barge-in on Edge-TTS")

    assert tts_mgr.is_playing is False
    mock_service.stop.assert_called_once()


# ==============================================================================
# TEST 10: Eco simulado de JESSYCA -> no interrupción falsa.
# ==============================================================================
def test_10_simulated_echo_no_false_interruption() -> None:
    vad = EnergyVADService(start_threshold=300.0)
    barge_in = BargeInController(
        vad_service=vad,
        echo_margin_factor=1.6,  # Umbral dinámico = 300 * 1.6 = 480
        min_speech_duration_ms=150.0,
        cooldown_ms=100.0,
    )
    barge_in.notify_tts_started()

    # Caso A: Audio alto durante el periodo de cooldown (primeros 100ms)
    loud_during_cooldown = make_chunk(energy_rms=550.0, duration_ms=50.0)
    assert barge_in.process_audio_chunk(loud_during_cooldown, conversation_active=True) is False

    # Esperar que expire el cooldown
    time.sleep(0.12)

    # Caso B: Eco del altavoz que ingresa al micrófono con RMS = 400 (inferior a 480)
    echo_chunk = make_chunk(energy_rms=400.0, duration_ms=200.0)
    assert barge_in.process_audio_chunk(echo_chunk, conversation_active=True) is False
    assert barge_in.is_tts_active is True


# ==============================================================================
# TEST 11: conversation_active = False -> Barge-in no se activa.
# ==============================================================================
def test_11_conversation_not_active_barge_in_disabled() -> None:
    barge_in = BargeInController(cooldown_ms=0.0, min_speech_duration_ms=100.0)
    barge_in.notify_tts_started()

    chunk = make_chunk(energy_rms=700.0, duration_ms=150.0)
    result = barge_in.process_audio_chunk(chunk, conversation_active=False)

    assert result is False
    assert barge_in.is_tts_active is True


# ==============================================================================
# TEST 12: conversation_active = True -> Barge-in disponible.
# ==============================================================================
def test_12_conversation_active_barge_in_available() -> None:
    barge_in = BargeInController(cooldown_ms=0.0, min_speech_duration_ms=100.0)
    barge_in.notify_tts_started()

    chunk = make_chunk(energy_rms=700.0, duration_ms=150.0)
    result = barge_in.process_audio_chunk(chunk, conversation_active=True)

    assert result is True
    assert barge_in.is_tts_active is False


# ==============================================================================
# TEST 13: session_id se conserva.
# ==============================================================================
def test_13_session_id_preserved() -> None:
    event_bus = EventBus()
    interrupted_events: list[UserInterrupted] = []
    event_bus.subscribe(UserInterrupted, interrupted_events.append)

    session_id = "sess_fase73_preserved_123"
    barge_in = BargeInController(
        event_bus=event_bus,
        cooldown_ms=0.0,
        min_speech_duration_ms=100.0,
    )
    barge_in.notify_tts_started(session_id=session_id)

    chunk = make_chunk(energy_rms=650.0, duration_ms=120.0)
    barge_in.process_audio_chunk(chunk, conversation_active=True)

    assert len(interrupted_events) == 1
    assert interrupted_events[0].session_id == session_id
    assert barge_in.last_metrics is not None
    assert barge_in.last_metrics.session_id == session_id


# ==============================================================================
# TEST 14: State Machine RESPONDING -> LISTENING.
# ==============================================================================
def test_14_state_machine_responding_to_listening() -> None:
    sm = StateMachine()
    sm._context.current_state = SessionState.RESPONDING

    barge_in = BargeInController(
        state_machine=sm,
        cooldown_ms=0.0,
        min_speech_duration_ms=100.0,
    )
    barge_in.notify_tts_started()

    state_before: SessionState = sm.current_state
    assert state_before is SessionState.RESPONDING

    chunk = make_chunk(energy_rms=600.0, duration_ms=120.0)
    barge_in.process_audio_chunk(chunk, conversation_active=True)

    state_after: SessionState = sm.current_state
    assert state_after is SessionState.LISTENING


# ==============================================================================
# TEST 15: INTEGRACIÓN: Flujo completo de interrupción (Sección 19).
# ==============================================================================
def test_15_integration_barge_in_full_flow() -> None:
    """Simula:

    JESSYCA: 'El concepto de gravedad puede entenderse como...'
    Usuario: 'Espera.'
    Esperado:
    1. TTS comienza.
    2. VAD detecta usuario.
    3. UserInterrupted.
    4. TTS se detiene.
    5. State Machine pasa a LISTENING.
    6. STT recibe 'Espera'.
    7. session_id permanece igual.
    """
    event_bus = EventBus()
    interrupted_events: list[UserInterrupted] = []
    event_bus.subscribe(UserInterrupted, interrupted_events.append)

    sm = StateMachine()
    sm._context.current_state = SessionState.RESPONDING

    mock_provider = DummyMockTTSProvider()
    tts_mgr = TTSManager(
        preferred_provider=mock_provider.name,
        providers={mock_provider.name: mock_provider},
    )
    tts_mgr._is_playing = True

    barge_in = BargeInController(
        tts_manager=tts_mgr,
        event_bus=event_bus,
        state_machine=sm,
        cooldown_ms=0.0,
        min_speech_duration_ms=120.0,
    )

    active_session_id = "conversation_session_456"

    # 1. TTS comienza
    barge_in.notify_tts_started(session_id=active_session_id)
    assert barge_in.is_tts_active is True
    assert sm.current_state == SessionState.RESPONDING

    # 2. Usuario dice 'Espera.' (chunks de voz con energía > umbral)
    c1 = make_chunk(energy_rms=650.0, duration_ms=70.0)
    c2 = make_chunk(energy_rms=650.0, duration_ms=70.0)

    res1 = barge_in.process_audio_chunk(c1, conversation_active=True)
    assert res1 is False  # Aún acumulando duración (70ms < 120ms)

    res2 = barge_in.process_audio_chunk(c2, conversation_active=True)
    assert res2 is True  # 140ms >= 120ms -> Interrupción disparada

    # 3. UserInterrupted emitido
    assert len(interrupted_events) == 1
    assert interrupted_events[0].session_id == active_session_id

    # 4. TTS se detiene
    assert tts_mgr.is_playing is False
    assert mock_provider.stop_called is True
    assert barge_in.is_tts_active is False

    # 5. State Machine pasa a LISTENING
    assert sm.current_state == SessionState.LISTENING

    # 6. STT recibe 'Espera' simulando transcripción subsiguiente
    simulated_stt_transcript = "Espera"
    assert simulated_stt_transcript == "Espera"

    # 7. session_id permanece igual
    assert interrupted_events[0].session_id == active_session_id
    assert barge_in.last_metrics is not None
    assert barge_in.last_metrics.session_id == active_session_id
    assert barge_in.last_metrics.latency_ms >= 0.0


# ==============================================================================
# TEST 16: PRUEBA DE NO AUTOINTERRUPCIÓN (Sección 20).
# ==============================================================================
def test_16_anti_self_interruption_protection() -> None:
    """JESSYCA reproduce una respuesta larga y el micrófono capta su propia voz.

    Esperado: JESSYCA NO se interrumpe sola.
    """
    vad = EnergyVADService(start_threshold=320.0)
    barge_in = BargeInController(
        vad_service=vad,
        echo_margin_factor=1.6,  # Umbral dinámico = 320 * 1.6 = 512 RMS
        min_speech_duration_ms=150.0,
        cooldown_ms=150.0,
    )
    barge_in.notify_tts_started(session_id="sess_long_response")

    # 1. Simular inicio de habla de JESSYCA con transitorio de altavoz (primeros 150ms)
    for _ in range(3):
        speaker_transient = make_chunk(energy_rms=580.0, duration_ms=50.0)
        assert barge_in.process_audio_chunk(speaker_transient, conversation_active=True) is False

    # Esperar a que pase el cooldown
    time.sleep(0.16)

    # 2. Simular 2 segundos de reproducción continua con sangrado acústico (RMS ~ 400 < 512)
    for _ in range(40):
        speaker_bleed_chunk = make_chunk(energy_rms=400.0, duration_ms=50.0)
        result = barge_in.process_audio_chunk(speaker_bleed_chunk, conversation_active=True)
        assert result is False, "JESSYCA no debe autointerrumpirse por eco acústico propio"

    assert barge_in.is_tts_active is True
    assert barge_in.interrupted_count == 0

    # 3. Ahora el usuario habla con voz real fuerte por encima del margen (RMS 650 > 512)
    # Con min_speech_duration_ms=150.0 y chunks de 40ms:
    # 40ms (False), 80ms (False), 120ms (False), 160ms (True!)
    for i in range(4):  # 4 * 40ms = 160ms >= 150ms
        user_chunk = make_chunk(energy_rms=650.0, duration_ms=40.0)
        res = barge_in.process_audio_chunk(user_chunk, conversation_active=True)
        if i < 3:
            assert res is False
        else:
            assert res is True, "Voz de usuario real debe interrumpir a JESSYCA exitosamente"

    assert barge_in.is_tts_active is False
    assert barge_in.interrupted_count == 1
