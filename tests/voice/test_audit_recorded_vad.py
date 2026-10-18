"""Offline ONNX check against the repository's recorded Spanish WAV."""
from collections import Counter
import json
from pathlib import Path
import time
import wave

import numpy as np

from services.voice.audio_input import AudioChunk
from services.voice.silero_vad_service import SileroVADService
from services.voice.vad_service import VADEvent


def test_recorded_spanish_voice_and_trailing_silence(tmp_path):
    wav_path = Path(__file__).parent / 'fixtures' / 'sample_es_hola_jessica.wav'
    with wave.open(str(wav_path), 'rb') as wav:
        rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    assert width == 2
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    size = int(rate * 0.05)
    vad = SileroVADService()
    results = []
    times = []
    try:
        for offset in range(0, len(samples), size):
            chunk = samples[offset:offset + size]
            chunk = np.pad(chunk, (0, size - len(chunk)))
            start = time.perf_counter()
            results.append(vad.process_chunk(AudioChunk(chunk.tobytes(), rate, 1, 2)))
            times.append((time.perf_counter() - start) * 1000)
        for _ in range(40):
            results.append(vad.process_chunk(AudioChunk(bytes(size * 2), rate, 1, 2)))
        events = Counter(str(result.event) for result in results)
        metrics = {'source': str(wav_path), 'sample_rate': rate,
                   'duration_seconds': len(samples) / rate,
                   'events': dict(events), 'mean_chunk_ms_including_load': sum(times) / len(times),
                   'max_reported_confidence': max(result.confidence for result in results)}
        print(json.dumps(metrics))
        assert any(result.event == VADEvent.SPEECH_START for result in results)
        assert any(result.event == VADEvent.SPEECH_END for result in results)
    finally:
        vad.close()
