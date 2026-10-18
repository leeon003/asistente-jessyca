import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from services.voice.stt_service import FasterWhisperSTTService
from services.voice.voice_errors import STTError, STTTimeoutError
from skills.base_skill import BaseSkill
from skills.skill_runtime import SkillRuntime


def test_whisper_lazy_segments_are_inside_timeout_and_not_queued():
    release = threading.Event()
    def transcribe(*args, **kwargs):
        def segments():
            release.wait(1)
            yield SimpleNamespace(text='hola', avg_logprob=-.1)
        return segments(), SimpleNamespace(language='es')
    service = FasterWhisperSTTService(device='cpu')
    service._model = SimpleNamespace(transcribe=transcribe)
    service._is_loaded = True
    pcm = np.full(1600, 2000, dtype=np.int16).tobytes()
    try:
        start = time.perf_counter()
        with pytest.raises(STTTimeoutError):
            service.transcribe(pcm, timeout_seconds=.03)
        assert time.perf_counter() - start < .25
        with pytest.raises(STTError, match='anterior sigue'):
            service.transcribe(pcm, timeout_seconds=.03)
    finally:
        release.set()
        service._executor.shutdown(wait=True)


def test_skill_timeout_does_not_wait_for_worker_shutdown():
    release = threading.Event()
    class SlowSkill(BaseSkill):
        def ejecutar(self, parametros):
            release.wait(1)
            return {'exito': True}
    skill = SlowSkill(nombre='audit.slow')
    runtime = SkillRuntime()
    context = runtime.create_context(skill.skill_id, timeout_seconds=.03)
    try:
        start = time.perf_counter()
        result = runtime.execute_skill(skill, context)
        assert time.perf_counter() - start < .25
        assert not result.success
        assert result.security_decision == 'TIMEOUT'
        assert result.metadata['cancellation_requested']
    finally:
        release.set()
        runtime.close()
