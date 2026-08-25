"""Suite de Pruebas de Certificación para el Hotfix de Integración TTS de Respuestas de Aclaración por Voz.

Valida:
1. Petición de aclaración ("Abre YouTube", "Abre una aplicación") activa AWAITING_CLARIFICATION y requires_clarification=True.
2. TurnManager inicia formalmente el turno del asistente (ASSISTANT_TURN) durante la locución de aclaración.
3. El motor TTS recibe y sintetiza fielmente el texto de aclaración.
4. TurnManager completa el turno y ContinuousVoiceSession transiciona a WAITING_FOR_FOLLOWUP.
5. El siguiente turno del usuario NO requiere wake word y completa la orden contextualmente.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.local_agent import (
    AgentExecutionState,
    InputModality,
    JessycaLocalAgent,
    JessycaRequest,
)
from services.voice.continuous_voice_session import (
    ContinuousVoiceSession,
    VoiceSessionMode,
)
from services.voice.tts_service import MockTTSService
from services.voice.turn_manager import (
    TurnManager,
    VoiceTurnState,
)


@pytest.fixture(autouse=True)
def reset_agent_state():
    agent = JessycaLocalAgent.get_instance()
    agent.reset()
    yield
    agent.reset()


def test_clarification_triggers_tts_and_turn_manager():
    """Valida el pipeline completo: CLARIFICATION -> TurnManager -> TTS -> WAITING_FOR_FOLLOWUP."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "test_voice_clarif_tts_session"
    turn_mgr = TurnManager()
    voice_session = ContinuousVoiceSession(
        session_id=session_id,
        turn_manager=turn_mgr,
        conversation_idle_timeout=10.0,
    )
    mock_tts = MockTTSService()

    # 1. Usuario emite orden ambigua ("Abre YouTube")
    voice_session.on_wake_detected()
    assert voice_session.mode == VoiceSessionMode.CONVERSATION_ACTIVE
    assert turn_mgr.current_state == VoiceTurnState.USER_TURN

    voice_session.on_processing_started()
    assert voice_session.mode == VoiceSessionMode.PROCESSING

    req = JessycaRequest(
        session_id=session_id,
        user_input="Abre YouTube",
        modality=InputModality.VOICE,
    )
    res = agent.interact(req)

    # 2. Verificar que se requiere aclaración
    assert res.requires_clarification is True
    assert res.status == AgentExecutionState.AWAITING_CLARIFICATION
    expected_question = res.clarification_question or res.response_text
    assert "YouTube" in expected_question
    assert "busque o reproduzca" in expected_question or "¿Quieres que solo" in expected_question

    # 3. Transición a habla (ASSISTANT_TURN) y envío a TTS
    voice_session.on_speaking_started()
    assert voice_session.mode == VoiceSessionMode.SPEAKING
    assert turn_mgr.current_state == VoiceTurnState.ASSISTANT_TURN

    tts_success = mock_tts.speak(expected_question)
    assert tts_success is True
    assert mock_tts.spoken_texts[-1] == expected_question

    # 4. Finalización de habla y apertura de Follow-up (WAITING_FOR_FOLLOWUP)
    voice_session.on_speaking_finished()
    assert voice_session.mode == VoiceSessionMode.WAITING_FOR_FOLLOWUP
    assert turn_mgr.current_state == VoiceTurnState.COMPLETED
    assert voice_session.should_require_wake_word() is False

    # 5. Turno 2: Usuario responde a la aclaración sin wake word ("Solo ábrelo")
    voice_session.on_listening_started()
    assert voice_session.mode == VoiceSessionMode.LISTENING
    assert turn_mgr.current_state == VoiceTurnState.USER_TURN

    voice_session.on_processing_started()
    req2 = JessycaRequest(
        session_id=session_id,
        user_input="Solo ábrelo",
        modality=InputModality.VOICE,
    )
    with patch("webbrowser.open", return_value=True):
        res2 = agent.interact(req2)

    assert res2.success is True
    assert res2.status == AgentExecutionState.COMPLETED

    # 6. Locución final de éxito
    voice_session.on_speaking_started()
    assert turn_mgr.current_state == VoiceTurnState.ASSISTANT_TURN
    mock_tts.speak(res2.spoken_text or res2.response_text)
    voice_session.on_speaking_finished()
    assert voice_session.mode == VoiceSessionMode.WAITING_FOR_FOLLOWUP


def test_voice_speaker_dispatch_fallback():
    """Valida que VoiceSpeaker en interfaces/modo_voz utiliza SAPI como fallback sin excepción."""
    from interfaces.modo_voz import VoiceSpeaker

    speaker = VoiceSpeaker()

    with patch("edge_tts.Communicate", side_effect=RuntimeError("EdgeTTS Network Offline")), \
         patch("pythoncom.CoInitialize"), \
         patch("win32com.client.Dispatch") as mock_dispatch:
        mock_sapi_instance = MagicMock()
        mock_dispatch.return_value = mock_sapi_instance

        test_msg = "Claro. ¿Quieres que solo abra YouTube o quieres que busque o reproduzca algo?"
        speaker.speak(test_msg)

        mock_sapi_instance.Speak.assert_called_once_with(test_msg)
