"""Suite de Pruebas de Integración y Certificación de la Experiencia de Voz Completa (Fase 55).

Valida de extremo a extremo:
1. test_voice_to_conversation: Conversación 1 (Saludo y capacidades naturales).
2. test_voice_to_clarification: Conversación 4 y 5 (Aclaración de app y pronombre sin antecedente).
3. test_voice_to_action: Conversación 2 (Apertura de Bloc de notas y creación de lista interactiva).
4. test_voice_to_security: Evaluación de seguridad, riesgo y confirmación contextual por voz.
5. test_voice_to_execution: Conversación 3 (Calculadora y operación aritmética con elipsis).
6. test_voice_to_verification: Verificación real obligatoria en Windows (execution + verification = success).
7. test_voice_to_response: Respuestas naturales limpias sin verbalizar detalles internos (Intención/Skill/Agente).
8. test_voice_to_next_turn: Progresión continua de turnos en sesión conversacional activa.
9. test_voice_to_interruption: Interrupción limpia durante TTS (Barge-in).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.cancellation import CancellationToken
from core.local_agent import (
    AgentExecutionState,
    InputModality,
    JessycaLocalAgent,
    JessycaRequest,
    LocalVoiceInterface,
)
from services.voice.barge_in_controller import BargeInController
from services.voice.stt_service import MockSTTService
from services.voice.tts_service import MockTTSService


@pytest.fixture(autouse=True)
def reset_local_agent():
    agent = JessycaLocalAgent.get_instance()
    agent.reset()
    yield
    agent.reset()


# ── 1. VOICE -> CONVERSATION (CONVERSACIÓN 1: SALUDO Y CAPACIDADES) ──


def test_voice_to_conversation():
    """Valida:
    Turno 1: 'Jessica, hola.' -> 'Hola, ¿en qué te puedo ayudar?'
    Turno 2: '¿Qué puedes hacer?' -> 'Puedo ayudarte a controlar aplicaciones...'
    """
    agent = JessycaLocalAgent.get_instance()
    session_id = "v2c_conv1_session"

    r1 = agent.interact(JessycaRequest(
        user_input="Jessica, hola",
        session_id=session_id,
        modality=InputModality.VOICE,
    ))
    assert r1.success is True
    assert "Hola, ¿en qué te puedo ayudar?" in r1.response_text

    r2 = agent.interact(JessycaRequest(
        user_input="¿Qué puedes hacer?",
        session_id=session_id,
        modality=InputModality.VOICE,
    ))
    assert r2.success is True
    assert "controlar aplicaciones" in r2.response_text.lower()


# ── 2. VOICE -> CLARIFICATION (CONVERSACIÓN 4 Y 5: ACLARACIÓN Y PRONOMBRES) ──


def test_voice_to_clarification():
    """Valida aclaración para intenciones incompletas y rechazo a alucinar sin antecedentes."""
    agent = JessycaLocalAgent.get_instance()

    # Conversación 4: "Abre una aplicación." -> "¿Cuál?" -> "Calculadora." -> "Listo..."
    s4 = "v2c_conv4_session"
    fake_calc = MagicMock()
    fake_calc.info = {"pid": 2020, "name": "calc.exe"}

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_calc]):
        r1 = agent.interact(JessycaRequest(user_input="Abre una aplicación", session_id=s4, modality=InputModality.VOICE))
        assert r1.status == AgentExecutionState.AWAITING_CLARIFICATION
        assert r1.requires_clarification is True
        assert "Cuál aplicación" in r1.response_text or "Qué aplicación" in r1.response_text

        r2 = agent.interact(JessycaRequest(user_input="Calculadora", session_id=s4, modality=InputModality.VOICE))
        assert r2.success is True
        assert "Calculadora" in r2.response_text

    # Conversación 5: "Haz algo con eso." sin antecedente previo
    s5 = "v2c_conv5_session"
    r3 = agent.interact(JessycaRequest(user_input="Haz algo con eso", session_id=s5, modality=InputModality.VOICE))
    assert r3.status == AgentExecutionState.AWAITING_CLARIFICATION or r3.requires_clarification is True
    assert "no estoy segura de a qué te refieres" in r3.response_text.lower() or "aclarármelo" in r3.response_text.lower()


# ── 3. VOICE -> ACTION (CONVERSACIÓN 2: BLOC DE NOTAS Y LISTA) ──


def test_voice_to_action():
    """Valida apertura de Bloc de notas y posterior creación de lista interactiva multi-turno."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "v2c_conv2_session"

    fake_notepad = MagicMock()
    fake_notepad.info = {"pid": 1010, "name": "notepad.exe"}

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_notepad]):
        # Turno 1: Abre el Bloc de notas
        r1 = agent.interact(JessycaRequest(
            user_input="Jessica, abre el Bloc de notas",
            session_id=session_id,
            modality=InputModality.VOICE,
        ))
        assert r1.success is True
        assert "Bloc de notas" in r1.response_text

        # Turno 2: Ahora escribe una lista
        r2 = agent.interact(JessycaRequest(
            user_input="Ahora escribe una lista",
            session_id=session_id,
            modality=InputModality.VOICE,
        ))
        assert r2.requires_clarification is True
        assert "Qué quieres incluir" in r2.response_text

        # Turno 3: Pan, leche y huevos
        r3 = agent.interact(JessycaRequest(
            user_input="Pan, leche y huevos",
            session_id=session_id,
            modality=InputModality.VOICE,
        ))
        assert r3.success is True
        assert "Listo" in r3.response_text


# ── 4. VOICE -> SECURITY & CONFIRMATION ──


def test_voice_to_security():
    """Valida que una orden destructiva por voz exija confirmación explícita antes de ejecutar."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "v2c_sec_session"

    # Turno 1: Solicitar borrado de archivo sensible
    r1 = agent.interact(JessycaRequest(
        user_input="Jessica, elimina el archivo temporal",
        session_id=session_id,
        modality=InputModality.VOICE,
    ))
    assert r1.requires_confirmation is True
    assert r1.status == AgentExecutionState.AWAITING_CONFIRMATION

    # Turno 2: Confirmar con "Sí"
    with patch("os.remove"), patch("os.path.exists", return_value=True):
        r2 = agent.interact(JessycaRequest(
            user_input="Sí",
            session_id=session_id,
            modality=InputModality.VOICE,
        ))
        assert r2.success is True
        assert r2.status == AgentExecutionState.COMPLETED
        assert r2.intent == "delete_file"


# ── 5. VOICE -> EXECUTION (CONVERSACIÓN 3: CALCULADORA Y SUMA) ──


def test_voice_to_execution():
    """Valida apertura de calculadora y operación matemática de múltiples turnos."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "v2c_conv3_session"

    fake_calc = MagicMock()
    fake_calc.info = {"pid": 3030, "name": "calc.exe"}

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_calc]):
        # Turno 1: Abre la calculadora
        r1 = agent.interact(JessycaRequest(
            user_input="Jessica, abre la calculadora",
            session_id=session_id,
            modality=InputModality.VOICE,
        ))
        assert r1.success is True
        assert "Calculadora" in r1.response_text

        # Turno 2: Haz una suma
        r2 = agent.interact(JessycaRequest(
            user_input="Haz una suma",
            session_id=session_id,
            modality=InputModality.VOICE,
        ))
        assert r2.requires_clarification is True
        assert "¿Qué números quieres sumar?" in r2.response_text or "dime los números" in r2.response_text.lower()

        # Turno 3: 125 y 378
        r3 = agent.interact(JessycaRequest(
            user_input="125 y 378",
            session_id=session_id,
            modality=InputModality.VOICE,
        ))
        assert r3.success is True
        assert "503" in r3.response_text


# ── 6. VOICE -> REAL EXECUTION VERIFICATION ──


def test_voice_to_verification():
    """Valida que si Windows no confirma el proceso, no se declare éxito falaz."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "v2c_verif_session"

    # Simular fallo en la verificación del proceso
    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[]):
        r = agent.interact(JessycaRequest(
            user_input="Jessica, abre la calculadora",
            session_id=session_id,
            modality=InputModality.VOICE,
        ))
        assert r.success is False
        assert "no confirmó" in r.response_text.lower() or "no pudo ser verificada" in r.response_text.lower()


# ── 7. VOICE -> RESPONSE PURITY (NO INTERNAL VERBALIZATION) ──


def test_voice_to_response():
    """Valida que el texto hablado no contenga 'Intención:', 'Agente:' ni 'Skill:' en modo normal."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "v2c_purity_session"

    fake_proc = MagicMock()
    fake_proc.info = {"pid": 4040, "name": "notepad.exe"}

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[fake_proc]):
        r = agent.interact(JessycaRequest(
            user_input="Jessica, abre el Bloc de notas",
            session_id=session_id,
            modality=InputModality.VOICE,
        ))

        spoken = r.spoken_text or r.response_text
        assert "Intención:" not in spoken
        assert "Intent:" not in spoken
        assert "Agente:" not in spoken
        assert "Skill:" not in spoken
        assert "SecurityLevel:" not in spoken
        assert "Listo" in spoken


# ── 8. VOICE -> CONTINUOUS TURN PROGRESSION ──


def test_voice_to_next_turn():
    """Valida la progresión continua de turnos usando LocalVoiceInterface y métricas de latencia."""
    stt_mock = MockSTTService(predefined_transcription="Abre el bloc de notas")
    tts_mock = MockTTSService()
    voice_iface = LocalVoiceInterface(stt_service=stt_mock, tts_service=tts_mock)
    session_id = "v2c_progression_session"

    # Turno 1 (con wake word simulada)
    req, metrics, err = voice_iface.capture_voice_request(require_wake_word=False, session_id=session_id)
    assert req is not None
    assert err is None
    assert req.user_input == "Abre el bloc de notas"
    assert metrics.stt_latency_ms >= 0.0

    # Sintetizar respuesta y pasar a modo de espera de follow-up
    voice_iface.synthesize_response("Listo, abrí el Bloc de notas.", session_id=session_id)
    session = voice_iface.get_or_create_continuous_session(session_id)
    assert session.is_active() is True
    assert session.should_require_wake_word() is False


# ── 9. VOICE -> BARGE-IN INTERRUPTION ──


def test_voice_to_interruption():
    """Valida interrupción instantánea de TTS y captura de la intervención del usuario."""
    tts_mock = MockTTSService()
    barge_in = BargeInController(tts_service=tts_mock)
    token = CancellationToken()

    barge_in.notify_tts_started(cancellation_token=token)
    assert barge_in.is_tts_active is True

    # El usuario comienza a hablar -> Interrupción
    interrupted = barge_in.trigger_barge_in(reason="User voice detected")
    assert interrupted is True
    assert token.is_cancelled is True
    assert barge_in.is_tts_active is False
