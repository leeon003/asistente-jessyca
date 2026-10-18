import asyncio
import threading

import pytest

from core.cancellation import CancellationToken
from interfaces.webui_bridge.adapter import generate_live_sse_stream


@pytest.mark.asyncio
async def test_generator_error_is_not_a_successful_completion():
    token = CancellationToken()
    def broken():
        yield 'inicio'
        raise RuntimeError('audit simulated failure')
    chunks = [chunk async for chunk in generate_live_sse_stream(broken(), cancellation_token=token)]
    assert any('core_stream_error' in chunk for chunk in chunks)
    assert not any('[DONE]' in chunk or '"finish_reason": "stop"' in chunk for chunk in chunks)
    assert token.is_cancelled


@pytest.mark.asyncio
async def test_disconnecting_stops_bounded_producer_and_closes_generator():
    token = CancellationToken()
    finished = threading.Event()
    count = []
    def fast():
        try:
            while True:
                count.append(1)
                yield 'token'
        finally:
            finished.set()
    stream = generate_live_sse_stream(fast(), cancellation_token=token)
    await anext(stream)
    await anext(stream)
    await stream.aclose()
    assert await asyncio.to_thread(finished.wait, 1)
    assert len(count) < 64
    assert token.is_cancelled


@pytest.mark.asyncio
async def test_successful_stream_has_done_without_cancelling():
    token = CancellationToken()
    chunks = [chunk async for chunk in generate_live_sse_stream(iter(['hola']), cancellation_token=token)]
    assert any('[DONE]' in chunk for chunk in chunks)
    assert not token.is_cancelled


def test_internal_type_error_does_not_retry_an_action(monkeypatch):
    from starlette.testclient import TestClient
    from interfaces.webui_bridge.app import create_webui_bridge_app, JessycaLocalAgent
    class BrokenAgent:
        calls = 0
        def interact(self, request, cancellation_token=None):
            self.calls += 1
            raise TypeError('audit error after possible side effect')
    agent = BrokenAgent()
    monkeypatch.setattr(JessycaLocalAgent, 'get_instance', lambda: agent)
    token = 'audit-secure-stream-test-token-71825'
    app = create_webui_bridge_app(auth_token=token)
    with TestClient(app) as client:
        result = client.post('/v1/chat/completions', headers={'Authorization': 'Bearer ' + token},
                             json={'model': 'jessyca', 'messages': [{'role': 'user', 'content': 'audit'}]})
    assert result.status_code == 500
    assert agent.calls == 1
