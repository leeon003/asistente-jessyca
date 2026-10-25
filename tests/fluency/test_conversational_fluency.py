"""Deterministic regressions; no microphone, model download or external API."""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.cancellation import CancellationToken
from core.local_agent.conversational_handler import ConversationalDialogueHandler
from core.local_agent.voice_interface import LocalVoiceInterface
from interfaces.webui_bridge.adapter import generate_live_sse_stream
from services.voice.audio_input import SyntheticAudioSource
from services.voice.stt_service import MockSTTService
from services.voice.streaming import speak_stream
from services.voice.turn_manager import TurnManager, VoiceTurnState


def test_first_phrase_is_spoken_before_generation_finishes():
    spoken = []
    def source():
        yield "Hola. "
        assert spoken == ["Hola."]
        yield "¿Cómo estás?"
    metrics = speak_stream(source(), lambda s: spoken.append(s) or True, CancellationToken())
    assert spoken == ["Hola.", "¿Cómo estás?"]
    assert metrics.phrases_spoken == 2
    assert metrics.first_text_ms <= metrics.first_tts_request_ms <= metrics.total_ms


def test_cancellation_never_drains_or_speaks_buffered_text():
    token = CancellationToken()
    closed = []
    def source():
        try:
            yield "Primero. Segundo. "
            pytest.fail("generator drained after cancellation")
        finally:
            closed.append(True)
    def speak(_):
        token.cancel()
        return True
    metrics = speak_stream(source(), speak, token)
    assert metrics.interrupted
    assert metrics.phrases_spoken == 1
    assert closed == [True]


def test_unpunctuated_text_is_bounded_without_losing_words():
    phrases = []
    text = "palabra " * 100
    speak_stream(iter([text]), lambda s: phrases.append(s) or True, CancellationToken(), max_chars=32)
    assert all(len(s) <= 32 for s in phrases)
    assert " ".join(phrases).split() == text.split()


def test_tts_failure_stops_generation():
    metrics = speak_stream(iter(["Uno. Dos."]), lambda _: False, CancellationToken())
    assert metrics.interrupted and metrics.phrases_spoken == 0


@pytest.mark.parametrize("text", ["", " ", "!!!", "por favor", "comparar", "prepara un informe"])
def test_non_commands_are_not_pure_interruptions(text):
    assert not TurnManager().is_pure_interruption(text)


@pytest.mark.parametrize("text", ["Comparar dos modelos", "Prepara una nota", "Para qué sirve Python"])
def test_stop_detection_does_not_match_substrings(text):
    stt = MockSTTService()
    stt.set_transcription(text)
    source = SyntheticAudioSource()
    source.feed_audio(b"test")
    interface = LocalVoiceInterface(stt_service=stt, audio_source=source)
    req, _, error = interface.capture_voice_request(require_wake_word=False)
    assert error is None and req.user_input == text


def test_voice_barge_in_shares_controller_and_cancels_inflight_synthesis():
    entered, released = threading.Event(), threading.Event()
    received = []
    tts = Mock()
    def speak(text, cancellation_token):
        received.append(cancellation_token)
        entered.set()
        assert released.wait(2)
        return not cancellation_token.is_cancelled
    tts.speak.side_effect = speak
    interface = LocalVoiceInterface(tts_service=tts)
    session = interface.get_or_create_continuous_session("my-session")
    token = CancellationToken()
    result = []
    worker = threading.Thread(target=lambda: result.append(interface.synthesize_response("Hola", token, "my-session")))
    worker.start()
    try:
        assert entered.wait(2)
        assert session.turn_manager.barge_in is interface.barge_in
        assert session.turn_manager.handle_barge_in()
        assert token.is_cancelled
    finally:
        released.set()
        worker.join(2)
    assert not worker.is_alive()
    assert received == [token]
    assert result[0][0] is False
    assert session.turn_manager.current_state == VoiceTurnState.INTERRUPTED


def test_partial_llm_failure_does_not_append_fabricated_fallback():
    provider = Mock()
    provider.is_available.return_value = True
    def generate(_):
        yield "Respuesta parcial"
        raise RuntimeError("provider lost")
    provider.generate_stream.side_effect = generate
    handler = ConversationalDialogueHandler(llm_provider=provider, model_router=Mock(), experimental_router=Mock())
    iterator = handler.generate_response_stream("Hola")
    assert next(iterator) == "Respuesta parcial"
    with pytest.raises(RuntimeError, match="provider lost"):
        next(iterator)


def test_sse_worker_failure_is_not_reported_as_success():
    def broken():
        yield "Hola"
        raise RuntimeError("secret provider detail")
    async def collect():
        return [frame async for frame in generate_live_sse_stream(broken())]
    frames = asyncio.run(collect())
    output = "".join(frames)
    assert '"type":"stream_error"' in output
    assert '"finish_reason": "stop"' not in output
    assert "secret provider detail" not in output
    assert frames[-1] == "data: [DONE]\n\n"


def test_sse_disconnect_cancels_token_and_closes_producer():
    token = CancellationToken()
    closed = threading.Event()
    def source():
        try:
            while not token.is_cancelled:
                yield "hola"
        finally:
            closed.set()
    async def disconnect():
        stream = generate_live_sse_stream(source(), cancellation_token=token)
        await anext(stream)
        await anext(stream)
        await stream.aclose()
    asyncio.run(disconnect())
    assert token.is_cancelled
    assert closed.wait(2)


def minimal_agent():
    from core.local_agent.local_agent import JessycaLocalAgent
    agent = JessycaLocalAgent.__new__(JessycaLocalAgent)
    agent._lock = threading.RLock()
    agent._active_tokens = {}
    agent._latest_metrics = None
    agent.emergency_stop_mgr = Mock()
    agent.emergency_stop_mgr.is_stopped.return_value = False
    agent.context_manager = Mock()
    agent._resolve_intent_and_slots = Mock(return_value=('general_query', {}, False))
    agent.dialogue_manager = Mock()
    from core.dialogue import DialogueActionType
    agent.dialogue_manager.evaluate_dialogue.return_value = SimpleNamespace(action_type=DialogueActionType.CONVERSATIONAL)
    agent._select_model_for_intent = Mock(return_value='test')
    agent.conversational_handler = Mock()
    return agent


def test_cancelled_stream_does_not_resolve_intent_or_touch_memory():
    agent = minimal_agent()
    token = CancellationToken()
    token.cancel()
    assert list(agent.interact_stream('Hola', token)) == []
    agent._resolve_intent_and_slots.assert_not_called()
    agent.context_manager.record_turn.assert_not_called()
    assert agent._latest_metrics.first_text_latency_ms is None
    assert agent._active_tokens == {}


def test_cancel_after_first_chunk_discards_remaining_text_and_memory():
    agent = minimal_agent()
    agent.conversational_handler.generate_response_stream.return_value = iter(['Hola', ' mundo'])
    token = CancellationToken()
    stream = agent.interact_stream('Hola', token)
    assert next(stream) == 'Hola'
    assert token in agent._active_tokens.values()
    token.cancel()
    assert list(stream) == []
    agent.context_manager.record_turn.assert_not_called()
    assert agent._latest_metrics.interruption_handled
    assert agent._active_tokens == {}


def test_emergency_stop_blocks_streaming_fast_path():
    agent = minimal_agent()
    agent.emergency_stop_mgr.is_stopped.return_value = True
    assert list(agent.interact_stream('Hola')) == []
    agent._resolve_intent_and_slots.assert_not_called()


def test_first_tts_latency_uses_observed_clock_not_audio_estimate():
    current = [0.0]
    def source():
        for text in ['Uno. ', 'Dos. ', 'Tres.']:
            current[0] += 0.1
            yield text
    metrics = speak_stream(source(), lambda _: True, CancellationToken(), clock=lambda: current[0])
    assert metrics.first_text_ms == pytest.approx(100)
    assert metrics.first_tts_request_ms == pytest.approx(100)
    assert metrics.total_ms == pytest.approx(300)


def test_ollama_stream_response_is_closed_on_early_consumer_exit():
    from core.llm.inference import OllamaProvider, InferenceRequest
    response = Mock()
    response.iter_lines.return_value = iter([b'{"response":"hola"}', b'{"response":" mundo"}'])
    provider = OllamaProvider(post_fn=Mock(return_value=response))
    stream = provider.generate_stream(InferenceRequest(prompt='hola', model_name='llama3.1'))
    assert next(stream) == 'hola'
    stream.close()
    response.close.assert_called_once()


def test_console_cancellation_never_replays_response_via_fallback():
    from interfaces.modo_voz import VoiceSpeaker
    speaker = VoiceSpeaker.__new__(VoiceSpeaker)
    speaker._lock = threading.Lock()
    speaker.voice_name = 'es-PE-CamilaNeural'
    speaker.barge_in_controller = None
    speaker._tts_manager = Mock()
    speaker._get_sapi_speaker = Mock()
    token = CancellationToken()
    def cancel(*args, **kwargs):
        assert kwargs['cancellation_token'] is token
        token.cancel()
        return False, Mock()
    speaker._tts_manager.speak.side_effect = cancel
    metrics = speaker.speak('Respuesta', cancellation_token=token)
    assert not metrics.success
    speaker._get_sapi_speaker.assert_not_called()


@pytest.mark.parametrize('mode', ['PROCESSING', 'SPEAKING'])
def test_active_work_is_not_expired_as_idle_silence(mode):
    import time
    from services.voice.continuous_voice_session import ContinuousVoiceSession, VoiceSessionMode
    session = ContinuousVoiceSession(mode=VoiceSessionMode(mode), last_activity=time.time() - 60)
    assert not session.check_timeout()
    assert session.mode.value == mode


def test_followup_uses_configured_followup_deadline():
    import time
    from services.voice.continuous_voice_session import ContinuousVoiceSession, VoiceSessionMode
    session = ContinuousVoiceSession(
        mode=VoiceSessionMode.WAITING_FOR_FOLLOWUP, conversation_idle_timeout=10,
        followup_timeout=1, last_activity=time.time() - 2,
    )
    assert session.check_timeout()
    assert session.should_require_wake_word()
