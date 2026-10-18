from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.intent.explicit_youtube import resolve_explicit_youtube
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import JessycaRequest


@pytest.mark.parametrize('text',[
    'No, te pedí que habrás YouTube y reproduzcas Play Your Face.',
    'Quiero que abras YouTube y reproduzcas Play Your Face',
    'Jessyca, abre YouTube y reproduce Play Your Face',
    'Reproduce Play Your Face en YouTube',
])
def test_spoken_correction_routes_to_tool_not_conversation(text):
    agent=object.__new__(JessycaLocalAgent)
    agent.sai_intent_engine=SimpleNamespace(interpret=Mock(side_effect=AssertionError('No debe pedir permiso imaginario al modelo')))
    intent,params,ambiguous=agent._resolve_intent(text,'youtube-correction')
    assert intent=='youtube_play'
    assert params['query']=='Play Your Face'
    assert not ambiguous


@pytest.mark.parametrize('text',[
    'No abras YouTube y reproduce Play Your Face',
    'No quiero que abras YouTube y reproduzcas Play Your Face',
    'No te pedí que abras YouTube y reproduzcas Play Your Face',
    '¿Por qué dijiste que no puedes reproducir Play Your Face en YouTube?',
    r'Reproduce D:\bailes de ia\jessyca1.mp4',
])
def test_negation_question_or_local_file_does_not_become_youtube_action(text):
    assert resolve_explicit_youtube(text) is None


def test_streaming_uses_verified_action_result_and_preserves_error():
    agent=object.__new__(JessycaLocalAgent)
    agent.dialogue_manager=SimpleNamespace(evaluate_dialogue=Mock(return_value=SimpleNamespace(action_type=None)))
    agent._execute_unified_pipeline=Mock(return_value=SimpleNamespace(spoken_text='No pude verificar la reproducción en YouTube.',response_text=''))
    result=''.join(agent.interact_stream(JessycaRequest(user_input='No, te pedí que habrás YouTube y reproduzcas Play Your Face.')))
    assert result=='No pude verificar la reproducción en YouTube.'
    params=agent._execute_unified_pipeline.call_args.kwargs['resolved_intent']
    assert params[0]=='youtube_play'
    assert params[1]['query']=='Play Your Face'
