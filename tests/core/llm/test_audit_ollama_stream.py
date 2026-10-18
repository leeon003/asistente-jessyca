"""Offline transport regressions; these do not certify installed Ollama models."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.llm.exceptions import InferenceError
from core.llm.inference import InferenceRequest, OllamaProvider


def provider_for(frames):
    response = Mock()
    response.iter_lines.return_value = iter(frames)
    post = Mock(return_value=response)
    manager = Mock()
    manager.get_model.side_effect = lambda model: SimpleNamespace(name=model, default_parameters={})
    return OllamaProvider(model_manager=manager, post_fn=post), response, post


@pytest.mark.parametrize('model', ['qwen3.5:9b', 'gemma4:e4b'])
def test_stream_contract_and_thinking_are_separated(model):
    frames = [json.dumps({'thinking': 'private reasoning'}).encode(),
              json.dumps({'response': 'Hola', 'done': False}).encode(),
              json.dumps({'response': '.', 'done': True}).encode()]
    provider, response, post = provider_for(frames)
    assert list(provider.generate_stream(InferenceRequest(prompt='hola', model_name=model))) == ['Hola', '.']
    assert post.call_args.kwargs['json']['model'] == model
    assert post.call_args.kwargs['json']['think'] is False
    response.close.assert_called_once()


@pytest.mark.parametrize('frames', [[b'{"error":"model missing"}'], [b'invalid-json'], [b'{"response":"partial"}']])
def test_error_or_truncated_stream_is_not_silent_success(frames):
    provider, response, post = provider_for(frames)
    with pytest.raises(InferenceError):
        list(provider.generate_stream(InferenceRequest(prompt='hola')))
    response.close.assert_called_once()


def test_cancelling_stream_releases_connection():
    provider, response, post = provider_for([b'{"response":"one"}', b'{"response":"two","done":true}'])
    stream = provider.generate_stream(InferenceRequest(prompt='hola'))
    assert next(stream) == 'one'
    stream.close()
    response.close.assert_called_once()
