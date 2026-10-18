from unittest.mock import Mock

import pytest

from core.local_agent.conversational_handler import ConversationalDialogueHandler


@pytest.mark.parametrize('question', ['¿Cuál es el saldo de mi cuenta bancaria?', '¿Cuántos correos sin leer tengo?'])
def test_unknown_private_data_never_uses_llm_as_account_source(question):
    provider = Mock()
    handler = ConversationalDialogueHandler(llm_provider=provider)
    answer = handler.generate_response(question)
    assert 'No tengo acceso' in answer
    assert '$' not in answer
    provider.generate.assert_not_called()
    assert ''.join(handler.generate_response_stream(question)) == answer


def test_successful_turn_does_not_inherit_previous_degradation(monkeypatch):
    provider = Mock()
    provider.is_available.return_value = True
    router = Mock()
    router.is_enabled.return_value = False
    handler = ConversationalDialogueHandler(llm_provider=provider, experimental_router=router)
    monkeypatch.setattr(handler, '_generate_with_llm', Mock(side_effect=[RuntimeError('audit outage'), 'Una rama contiene una línea de trabajo del repositorio.']))
    handler.generate_response('¿Qué es una rama en git?')
    assert handler._last_was_degraded
    answer = handler.generate_response('¿Qué contiene una rama en git?')
    assert 'rama' in answer
    assert not handler._last_was_degraded
