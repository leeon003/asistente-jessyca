"""Exercise the real agent bridge without starting desktop actions or models."""
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.cancellation import CancellationToken
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import JessycaRequest, LocalAgentMetrics


class BridgeCaptured(Exception):
    pass


def test_intent_is_resolved_once_per_turn(monkeypatch):
    agent = JessycaLocalAgent()
    agent.use_jessyca_brain = False
    resolver = Mock(return_value=('interrupt_assistant', {'immediate_response': 'Te escucho.'}, False))
    monkeypatch.setattr(agent, '_resolve_intent', resolver)
    response = agent.interact(JessycaRequest(user_input='Espera', session_id='audit-single-resolution'))
    assert response.success
    assert not response.tools_executed
    assert resolver.call_count == 1


@pytest.mark.parametrize('phrase', ['Jessyca, báilame', r'Reproduce D:\bailes de ia\jessyca1.mp4'])
def test_streaming_local_media_uses_verified_pipeline(phrase):
    agent = object.__new__(JessycaLocalAgent)
    agent._execute_unified_pipeline = Mock(return_value=SimpleNamespace(
        spoken_text='Reproducción verificada.', response_text='Reproducción verificada.',
    ))
    agent._resolve_intent = Mock(side_effect=AssertionError('No debe convertir el archivo local en conversación'))
    chunks = list(agent.interact_stream(JessycaRequest(user_input=phrase)))
    assert ''.join(chunks) == 'Reproducción verificada.'
    assert agent._execute_unified_pipeline.call_count == 1


def execute_bridge(action, tool, params, skill_result=None, binding=None):
    agent = object.__new__(JessycaLocalAgent)
    agent.skill_manager = Mock()
    agent.skill_manager.execute_skill.return_value = skill_result
    agent.jde_runtime_binding = binding
    captured = []

    def process_request(**kwargs):
        captured.append(kwargs['tool_executor'](action, tool, params))
        raise BridgeCaptured

    agent.brain = SimpleNamespace(process_request=process_request)
    with pytest.raises(BridgeCaptured):
        agent._execute_with_jessyca_brain(
            JessycaRequest(user_input='test'), CancellationToken(),
            LocalAgentMetrics(), time.perf_counter(),
        )
    return captured[0], agent.skill_manager


@pytest.mark.parametrize('params', [{}, {'target': 'calc'}])
def test_unknown_tool_never_claims_success_or_opens_app(params):
    result, manager = execute_bridge('unknown_action', 'unknown_tool', params)
    assert result[0] is False
    assert result[2]
    manager.execute_skill.assert_not_called()


@pytest.mark.parametrize('skill_result', [None, 'ok', {}, {'status': 'ok'}])
def test_unstructured_skill_result_is_not_success(skill_result):
    result, _ = execute_bridge('play_random_video', 'windows_media', {}, skill_result)
    assert result[0] is False


def test_dance_bridge_keeps_local_directory():
    result, manager = execute_bridge(
        'play_random_video', 'windows_media', {'target_dir': r'D:\bailes de ia'},
        SimpleNamespace(success=True, output={'exito': True}, error=None),
    )
    assert result[0] is True
    assert manager.execute_skill.call_args.args == ('windows.media',)
    assert manager.execute_skill.call_args.kwargs['parameters']['target_dir'] == r'D:\bailes de ia'


@pytest.mark.parametrize('policy', ['DENY', 'REQUIRE_REVIEW'])
def test_brain_cannot_bypass_injected_jde_policy(policy):
    from core.jde.runtime_binding import JDERuntimeVerdictType
    binding = Mock()
    binding.evaluate.return_value = SimpleNamespace(verdict=JDERuntimeVerdictType(policy), reason='Audit policy')
    result, manager = execute_bridge('play_random_video', 'windows_media', {}, binding=binding)
    assert result[0] is False
    manager.execute_skill.assert_not_called()
    assert result[1]['executed'] is False


def test_browser_unverified_bridge_is_not_success():
    result, _ = execute_bridge('browser_search', 'browser_search', {'query': 'audit'},
                              SimpleNamespace(success=True, output={'exito': True, 'verified': False}, error=None))
    assert result[0] is False
