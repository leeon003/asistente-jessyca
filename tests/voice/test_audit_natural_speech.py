import threading
from types import SimpleNamespace

import pytest

from services.voice.spoken_text import prepare_spoken_text
from services.voice.stt_service import FasterWhisperSTTService
from services.voice.voice_errors import STTError


def test_spoken_answer_keeps_prose_and_sources_on_screen():
    original = '## Resultado\n**Son 3 archivos.** [Fuente](https://example.org/a) [1]\n- Listos.'
    assert prepare_spoken_text(original) == 'Resultado Son 3 archivos. Fuente Listos.'
    assert 'https://' in original


@pytest.mark.parametrize('text', ['<think>razonamiento privado', '<THINK>privado</THINK>'])
def test_hidden_reasoning_never_reaches_speaker(text):
    assert prepare_spoken_text(text) == ''


def test_code_is_not_read_as_programming_symbols():
    spoken = prepare_spoken_text('Aquí tienes:\n```python\nprint("hola")\n```\nPuedes ejecutarlo.')
    assert 'print' not in spoken
    assert 'código está disponible' in spoken
    assert spoken.endswith('Puedes ejecutarlo.')


def test_warmup_timeout_covers_lazy_native_inference_and_prevents_overlap():
    release = threading.Event()
    started = threading.Event()
    service = FasterWhisperSTTService(device='cpu', compute_type='int8')
    service._is_loaded = True

    def segments():
        started.set()
        release.wait(2)
        yield SimpleNamespace(text='')

    service._model = SimpleNamespace(transcribe=lambda *args, **kwargs: (segments(), None))
    try:
        with pytest.raises(STTError):
            service.warmup(timeout_seconds=0.05)
        assert started.is_set()
        assert not service.is_ready
        with pytest.raises(STTError, match='anterior sigue'):
            service.warmup(timeout_seconds=0.05)
    finally:
        release.set()
        service._executor.shutdown(wait=True)


def test_explicit_cpu_request_does_not_reuse_other_configuration():
    from services.voice.stt_service import get_stt_service, reset_stt_services

    reset_stt_services()
    try:
        auto = get_stt_service('faster-whisper', device='auto')
        cpu = get_stt_service('faster-whisper', device='cpu', compute_type='int8')
        assert cpu is not auto
        assert cpu.device == 'cpu'
        assert cpu is get_stt_service('faster-whisper', compute_type='int8', device='cpu')
    finally:
        reset_stt_services()


def test_interruption_reaches_token_before_waiting_for_playback_lock():
    from interfaces.modo_voz import VoiceSpeaker
    from core.cancellation import CancellationToken
    cancelled = threading.Event()
    speaker = object.__new__(VoiceSpeaker)
    speaker._lock = threading.Lock()
    speaker._current_token = CancellationToken()
    token = speaker._current_token
    speaker._tts_manager = SimpleNamespace(cancel=lambda **kwargs: cancelled.set())
    speaker._sapi_speaker = None
    speaker.aurora_bridge = None
    speaker._lock.acquire()
    worker = threading.Thread(target=speaker.stop)
    try:
        worker.start()
        assert cancelled.wait(1)
        assert token.is_cancelled
    finally:
        speaker._lock.release()
        worker.join(2)
    assert not worker.is_alive()
