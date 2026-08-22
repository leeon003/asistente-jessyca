"""Suite de Pruebas para Sesiones de Voz Continua (Fase 51).

Valida:
1. test_wake_starts_session: Activación inicial desde IDLE con palabra clave.
2. test_followup_without_wake_word: Turnos subsecuentes dentro de la ventana de follow-up sin repetir wake word.
3. test_timeout_returns_idle: Expiración por inactividad regresa limpiamente a IDLE.
4. test_wake_after_timeout: Re-activación con wake word tras timeout previo.
5. test_vad_does_not_break_turn: Integración de VAD y pre-roll buffer para evitar truncamiento.
6. test_conversation_session_lifecycle: Máquina de estados completa de la sesión de voz continua.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from core.local_agent import (
    InputModality,
    JessycaLocalAgent,
    JessycaRequest,
    LocalVoiceInterface,
)
from services.voice.audio_input import SyntheticAudioSource
from services.voice.continuous_voice_session import (
    AudioPreRollBuffer,
    ContinuousVoiceSession,
    VoiceSessionMode,
)
from services.voice.stt_service import MockSTTService
from services.voice.wake_word_service import KeywordWakeWordService


@pytest.fixture(autouse=True)
def reset_voice_state():
    agent = JessycaLocalAgent.get_instance()
    agent.reset()
    yield
    agent.reset()


# ── 1. ACTIVACIÓN INICIAL CON WAKE WORD ──


def test_wake_starts_session():
    """Valida que desde IDLE se exige wake word y que al detectarla transiciona a activa."""
    session = ContinuousVoiceSession(session_id="test_wake_sess", conversation_idle_timeout=5.0)
    assert session.mode == VoiceSessionMode.IDLE
    assert session.should_require_wake_word() is True

    # Simular detección de wake word
    session.on_wake_detected()
    assert session.mode == VoiceSessionMode.CONVERSATION_ACTIVE
    assert session.is_active() is True
    assert session.should_require_wake_word() is False
    assert session.turns_count == 1


# ── 2. SEGUIMIENTO (FOLLOW-UP) SIN WAKE WORD ──


def test_followup_without_wake_word():
    """Valida que en ventana de seguimiento se procesan órdenes sin exigir 'Jessica'."""
    stt_mock = MockSTTService()
    voice_iface = LocalVoiceInterface(
        stt_service=stt_mock,
        conversation_idle_timeout=10.0,
    )
    session_id = "test_followup_session"
    session = voice_iface.get_or_create_continuous_session(session_id)

    # Turno 1: Wake word detectado
    session.on_wake_detected()
    session.on_processing_started()
    session.on_speaking_started()
    session.on_speaking_finished()

    # Estado tras Turno 1: WAITING_FOR_FOLLOWUP
    assert session.mode == VoiceSessionMode.WAITING_FOR_FOLLOWUP
    assert session.should_require_wake_word() is False

    # Turno 2: Usuario habla directamente ("Ahora haz una suma")
    stt_mock.set_transcription("Ahora haz una suma")
    fake_source = SyntheticAudioSource()
    fake_source.feed_audio(b"audio data for sum")
    fake_source.start()
    voice_iface.audio_source = fake_source

    req, metrics, err = voice_iface.capture_voice_request(session_id=session_id)

    assert err is None
    assert req is not None
    assert req.user_input == "Ahora haz una suma"
    assert req.require_wake_word is False


# ── 3. TIMEOUT REGRESA A IDLE ──


def test_timeout_returns_idle():
    """Valida que al expirar el tiempo de inactividad, la sesión pasa a IDLE."""
    session = ContinuousVoiceSession(
        session_id="test_timeout_sess",
        conversation_idle_timeout=0.1,  # 100ms para test rápido
    )
    session.on_wake_detected()
    session.on_speaking_finished()
    assert session.mode == VoiceSessionMode.WAITING_FOR_FOLLOWUP

    # Esperar expiración
    time.sleep(0.15)

    expired = session.check_timeout()
    assert expired is True
    assert session.mode == VoiceSessionMode.IDLE
    assert session.is_active() is False
    assert session.should_require_wake_word() is True


# ── 4. RE-ACTIVACIÓN TRAS TIMEOUT ──


def test_wake_after_timeout():
    """Valida que tras timeout, frases sin wake word son rechazadas y con wake word reactivan sesión."""
    voice_iface = LocalVoiceInterface(
        conversation_idle_timeout=0.1,
    )
    session_id = "test_reactivate_sess"
    session = voice_iface.get_or_create_continuous_session(session_id)

    # Activar y dejar expirar
    session.on_wake_detected()
    session.on_speaking_finished()
    time.sleep(0.15)
    assert session.check_timeout() is True
    assert session.mode == VoiceSessionMode.IDLE

    # Intento sin wake word (audio sin palabra clave)
    fake_source = SyntheticAudioSource()
    fake_source.feed_audio(b"random background noise")
    fake_source.start()
    voice_iface.audio_source = fake_source
    voice_iface.wake_word_service = KeywordWakeWordService(keyword="jessica")

    req, metrics, err = voice_iface.capture_voice_request(session_id=session_id)
    assert req is None
    assert "Wake word" in str(err)
    assert session.mode == VoiceSessionMode.IDLE

    # Intento con wake word ("Jessica abre bloc de notas")
    fake_ww_source = SyntheticAudioSource()
    fake_ww_source.feed_audio(b"jessica abre bloc de notas")
    fake_ww_source.feed_audio(b"jessica abre bloc de notas")
    fake_ww_source.start()
    voice_iface.audio_source = fake_ww_source
    voice_iface.wake_word_service.trigger_manually()
    stt_mock = MockSTTService()
    stt_mock.set_transcription("Jessica abre bloc de notas")
    voice_iface.stt_service = stt_mock

    req2, metrics2, err2 = voice_iface.capture_voice_request(session_id=session_id)
    assert err2 is None
    assert req2 is not None
    assert session.mode in (VoiceSessionMode.CONVERSATION_ACTIVE, VoiceSessionMode.PROCESSING)


# ── 5. INTEGRACIÓN DE VAD Y PRE-ROLL BUFFER ──


def test_vad_does_not_break_turn():
    """Valida que el buffer circular de pre-roll acumula chunks de audio y no corta el inicio."""
    buffer = AudioPreRollBuffer(max_chunks=5)
    assert len(buffer) == 0

    chunk1 = b"\x01\x02\x03\x04"
    chunk2 = b"\x05\x06\x07\x08"
    chunk3 = b"\x09\x10\x11\x12"

    buffer.append(chunk1)
    buffer.append(chunk2)
    buffer.append(chunk3)

    assert len(buffer) == 3
    combined = buffer.get_preroll_bytes()
    assert combined == chunk1 + chunk2 + chunk3

    # Limpiar buffer
    buffer.clear()
    assert len(buffer) == 0
    assert buffer.get_preroll_bytes() == b""


# ── 6. CICLO DE VIDA COMPLETO DE SESIÓN DE VOZ ──


def test_conversation_session_lifecycle():
    """Valida la transición a través de todos los estados formales de VoiceSessionMode."""
    session = ContinuousVoiceSession(session_id="lifecycle_sess", conversation_idle_timeout=10.0)

    # 1. IDLE
    assert session.mode == VoiceSessionMode.IDLE

    # 2. WAKE_DETECTED / CONVERSATION_ACTIVE
    session.on_wake_detected()
    assert session.mode == VoiceSessionMode.CONVERSATION_ACTIVE

    # 3. LISTENING
    session.on_listening_started()
    assert session.mode == VoiceSessionMode.LISTENING

    # 4. PROCESSING
    session.on_processing_started()
    assert session.mode == VoiceSessionMode.PROCESSING

    # 5. SPEAKING
    session.on_speaking_started()
    assert session.mode == VoiceSessionMode.SPEAKING

    # 6. WAITING_FOR_FOLLOWUP
    session.on_speaking_finished()
    assert session.mode == VoiceSessionMode.WAITING_FOR_FOLLOWUP

    # 7. END_SESSION -> IDLE
    session.end_session()
    assert session.mode == VoiceSessionMode.IDLE
    assert session.is_active() is False


# ── 7. INTEGRACIÓN E2E DE AGENTE LOCAL EN SESIÓN CONTINUA ──


def test_e2e_continuous_voice_interaction():
    """Valida la interacción conversacional multi-turno de extremo a extremo."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "e2e_voice_session_continuous"

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 7777, "name": "notepad.exe"}

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_proc]):
        # Turno 1 (con wake word)
        r1 = agent.interact(JessycaRequest(
            session_id=session_id,
            user_input="Jessica, abre el bloc de notas",
            modality=InputModality.VOICE,
        ))
        assert r1.success is True
        assert "Bloc de notas" in r1.response_text

        # Turno 2 (follow-up directo sin nombre)
        r2 = agent.interact(JessycaRequest(
            session_id=session_id,
            user_input="Ahora haz una suma",
            modality=InputModality.VOICE,
        ))
        assert r2.requires_clarification is True
        assert "¿Qué números quieres sumar?" in r2.response_text

        # Turno 3 (respuesta con parámetros)
        r3 = agent.interact(JessycaRequest(
            session_id=session_id,
            user_input="50 y 25",
            modality=InputModality.VOICE,
        ))
        assert r3.success is True
        assert "75" in r3.response_text
