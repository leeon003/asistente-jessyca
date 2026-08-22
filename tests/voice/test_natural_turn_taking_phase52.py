"""Suite de Pruebas de Certificación para Toma de Turnos Natural y Barge-In (Fase 52).

Valida:
1. test_barge_in_interrupts_tts: Interrupción inmediata de TTS activo ante actividad vocal del usuario.
2. test_tts_cancel: Detención limpia de TTS sin audio residual ni buffers bloqueados.
3. test_interruption_state: Transición de estados (USER_TURN -> ASSISTANT_TURN -> INTERRUPTED -> USER_TURN).
4. test_no_duplicate_execution_after_interrupt: No ejecución accidental de comandos ante frases de pura interrupción ("Déjame hablar", "Espera").
5. test_new_user_turn_after_interrupt: Inicio inmediato de nueva orden tras interrupción sin reiniciar la sesión.
6. test_concurrent_voice_state: Robustez concurrente multi-hilo sin condiciones de carrera.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from core.cancellation import CancellationToken
from core.local_agent import (
    AgentExecutionState,
    InputModality,
    JessycaLocalAgent,
    JessycaRequest,
)
from services.voice.barge_in_controller import BargeInController
from services.voice.continuous_voice_session import (
    ContinuousVoiceSession,
)
from services.voice.tts_service import MockTTSService
from services.voice.turn_manager import (
    TurnManager,
    VoiceTurnState,
)


@pytest.fixture(autouse=True)
def reset_voice_state():
    agent = JessycaLocalAgent.get_instance()
    agent.reset()
    yield
    agent.reset()


# ── 1. CORTE INMEDIATO DE TTS (BARGE-IN) ──


def test_barge_in_interrupts_tts():
    """Valida que la detección de voz del usuario detiene inmediatamente el TTS y activa el token de cancelación."""
    tts_mock = MockTTSService()
    barge_in = BargeInController(tts_service=tts_mock)
    token = CancellationToken()

    barge_in.notify_tts_started(cancellation_token=token)
    assert barge_in.is_tts_active is True
    assert token.is_cancelled is False

    # Simular interrupción del usuario
    interrupted = barge_in.trigger_barge_in(reason="User voice detected")
    assert interrupted is True
    assert barge_in.is_tts_active is False
    assert token.is_cancelled is True
    assert barge_in.interrupted_count == 1


# ── 2. CANCELACIÓN LIMPIA DE TTS ──


def test_tts_cancel():
    """Valida que el servicio TTS se detiene limpiamente mediante stop() y cancellation_token."""
    tts = MockTTSService()
    token = CancellationToken()

    # Cancelar antes de hablar
    token.cancel()
    with pytest.raises(Exception) as exc_info:
        tts.synthesize("Texto largo de prueba", cancellation_token=token)
    assert "cancelada" in str(exc_info.value).lower()

    # Verificar que stop() restablece el estado de habla
    tts.is_speaking = True
    tts.stop()
    assert tts.is_speaking is False


# ── 3. MÁQUINA DE ESTADOS DE INTERRUPCIÓN (VOICETURNSTATE) ──


def test_interruption_state():
    """Valida la transición completa de turnos conversacionales ante interrupciones."""
    turn_mgr = TurnManager()
    assert turn_mgr.current_state == VoiceTurnState.USER_TURN

    # Iniciar turno del asistente
    token = CancellationToken()
    turn_mgr.start_assistant_turn(cancellation_token=token)
    assert turn_mgr.current_state == VoiceTurnState.ASSISTANT_TURN
    assert turn_mgr.barge_in.is_tts_active is True

    # Interrumpir
    success = turn_mgr.handle_barge_in(reason="User barge-in")
    assert success is True
    assert turn_mgr.current_state == VoiceTurnState.INTERRUPTED
    assert token.is_cancelled is True

    # Iniciar nuevo turno del usuario
    turn_mgr.start_user_turn()
    assert turn_mgr.current_state == VoiceTurnState.USER_TURN
    assert turn_mgr.turn_id == 1


# ── 4. DISCRIMINACIÓN: NO EJECUCIÓN ACCIDENTAL ANTE INTERRUPCIÓN PURA ──


def test_no_duplicate_execution_after_interrupt():
    """Valida que frases de pura interrupción ('Déjame hablar', 'Espera') no ejecuten herramientas del SO."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "interruption_pure_test"

    for phrase in ("Déjame hablar", "Espera", "Un momento", "Silencio"):
        req = JessycaRequest(
            session_id=session_id,
            user_input=phrase,
            modality=InputModality.VOICE,
        )
        res = agent.interact(req)

        assert res.success is True
        assert res.status == AgentExecutionState.COMPLETED
        assert res.intent in ("interrupt_assistant", "cancel_task")
        # Verificar que no intentó abrir ni cerrar ninguna aplicación
        assert res.tools_executed == () or len(res.tools_executed) == 0
        assert any(word in res.response_text.lower() for word in ("te escucho", "cancelada", "dime"))


# ── 5. NUEVA ORDEN TRAS INTERRUPCIÓN SIN REINICIAR SESIÓN ──


def test_new_user_turn_after_interrupt():
    """Valida que tras interrumpir a JESSYCA, el usuario puede dar una nueva orden inmediatamente."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "new_turn_after_interrupt_session"

    fake_notepad = MagicMock()
    fake_notepad.info = {"pid": 1111, "name": "notepad.exe"}
    fake_calc = MagicMock()
    fake_calc.info = {"pid": 2222, "name": "calc.exe"}

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_notepad, fake_calc]):
        # Turno 1: Usuario abre bloc de notas
        r1 = agent.interact(JessycaRequest(
            session_id=session_id,
            user_input="Jessica, abre el bloc de notas",
            modality=InputModality.VOICE,
        ))
        assert r1.success is True
        assert "Bloc de notas" in r1.response_text

        # Turno 2: Usuario interrumpe ("Déjame hablar")
        r2 = agent.interact(JessycaRequest(
            session_id=session_id,
            user_input="Déjame hablar",
            modality=InputModality.VOICE,
        ))
        assert r2.success is True
        assert r2.intent == "interrupt_assistant"

        # Turno 3: Usuario entrega nueva orden en la misma sesión activa ("Ahora abre la calculadora")
        r3 = agent.interact(JessycaRequest(
            session_id=session_id,
            user_input="Ahora abre la calculadora",
            modality=InputModality.VOICE,
        ))
        assert r3.success is True
        assert r3.intent == "open_application"
        assert "Calculadora" in r3.response_text


# ── 6. ROBUSTEZ CONCURRENTE MULTI-HILO (RACE CONDITIONS IMMUNITY) ──


def test_concurrent_voice_state():
    """Stress test multi-hilo para validar que no existan bloqueos ni condiciones de carrera."""
    session = ContinuousVoiceSession(session_id="concurrent_test_session")
    errors: list[Exception] = []

    def _tts_thread():
        try:
            for _ in range(50):
                session.on_speaking_started()
                time.sleep(0.001)
                session.on_speaking_finished()
        except Exception as e:
            errors.append(e)

    def _barge_in_thread():
        try:
            for _ in range(50):
                session.on_interrupted(reason="Concurrent barge in test")
                time.sleep(0.001)
                session.on_listening_started()
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=_tts_thread)
    t2 = threading.Thread(target=_barge_in_thread)

    t1.start()
    t2.start()

    t1.join(timeout=3.0)
    t2.join(timeout=3.0)

    assert len(errors) == 0
    assert session.is_active() is True
