import io
import wave
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from interfaces.webui_bridge.app import create_webui_bridge_app

TOKEN = 'audit-studio-private-token-82913'


@pytest.fixture
def client():
    with TestClient(create_webui_bridge_app(auth_token=TOKEN)) as client:
        yield client


@pytest.mark.parametrize('path,method', [('/studio/api/status','get'),('/studio/api/files','get'),('/studio/api/transcribe','post'),('/studio/api/speech','post')])
def test_voice_and_personal_data_require_auth(client,path,method):
    kwargs = {'json': {'text':'hola'}} if path.endswith('speech') else {}
    assert getattr(client,method)(path,**kwargs).status_code == 401


def test_public_shell_never_contains_auth_token(client):
    response = client.get('/studio')
    assert response.status_code == 200
    assert TOKEN not in response.text
    assert 'Conversación' in response.text


def test_invalid_or_oversized_audio_is_rejected_before_stt(client):
    headers={'Authorization':'Bearer '+TOKEN}
    assert client.post('/studio/api/transcribe',headers=headers,content=b'not a wave').status_code == 422
    assert client.post('/studio/api/transcribe',headers=headers,content=b'x'*(4*1024*1024+1)).status_code == 413


def test_browser_wav_uses_real_stt_contract(client,monkeypatch):
    from services.voice import stt_service
    class Service:
        def transcribe(self,data,timeout_seconds):
            assert data.startswith(b'RIFF')
            assert timeout_seconds == 15
            return SimpleNamespace(text='Jessyca, báilame',confidence=.9,is_empty=False)
    monkeypatch.setattr(stt_service,'get_stt_service',lambda:Service())
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as wav:
        wav.setparams((1,2,16000,0,'NONE','not compressed'))
        wav.writeframes(b'\0\0'*1600)
    response=client.post('/studio/api/transcribe',headers={'Authorization':'Bearer '+TOKEN},content=buffer.getvalue())
    assert response.json()['text'] == 'Jessyca, báilame'


def test_speech_failure_cannot_return_fake_audio(client,monkeypatch):
    from services.voice import tts_provider
    manager=SimpleNamespace(synthesize=lambda *args,**kwargs:(SimpleNamespace(is_success=False,audio_bytes=b''),None))
    monkeypatch.setattr(tts_provider,'get_tts_manager',lambda:manager)
    response=client.post('/studio/api/speech',headers={'Authorization':'Bearer '+TOKEN},json={'text':'hola'})
    assert response.status_code == 503


def test_desktop_pairing_is_one_use_and_never_returns_primary_key(client):
    from interfaces.webui_bridge.studio_auth import make_launch_ticket
    ticket=make_launch_ticket(TOKEN)
    result=client.post('/studio/api/pair',json={'ticket':ticket})
    assert result.status_code == 200
    session_token=result.json()['token']
    assert session_token != TOKEN
    assert TOKEN not in result.text
    assert client.post('/studio/api/pair',json={'ticket':ticket}).status_code == 401
    assert client.get('/studio/api/status',headers={'Authorization':'Bearer '+session_token}).status_code == 200


def test_modified_and_expired_pairing_tickets_are_rejected(client,monkeypatch):
    from interfaces.webui_bridge import studio_auth
    ticket=studio_auth.make_launch_ticket(TOKEN)
    assert client.post('/studio/api/pair',json={'ticket':ticket+'x'}).status_code == 401
    now=studio_auth.time.time()
    monkeypatch.setattr(studio_auth.time,'time',lambda:now+90)
    assert client.post('/studio/api/pair',json={'ticket':ticket}).status_code == 401
