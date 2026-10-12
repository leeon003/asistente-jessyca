"""Tests para la recuperación funcional de STT faster-whisper, fallback GPU->CPU y pipeline de voz.

Valida:
1. Transcripción real en español con CPU/int8 sobre archivo de audio físico.
2. Transcripciones consecutivas sin recargar el modelo.
3. Simulación de fallo CUDA (cublas64_12.dll ausente) y recuperación automática a CPU/int8.
4. Auto-selección en entorno real (detección de ausencia de cuBLAS 12 y transición limpia a CPU).
5. Silencio, descarte y no enmascaramiento de errores no-CUDA.
6. Pipeline extremo a extremo (Audio -> STT -> Core -> Respuesta).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import InputModality, JessycaRequest
from services.voice.stt_service import (
    FasterWhisperSTTService,
    TranscriptResult,
    get_stt_service,
    reset_stt_services,
)
from services.voice.voice_errors import STTAudioFormatError, STTError

FIXTURE_WAV = Path(__file__).parent / "fixtures" / "sample_es_hola_jessica.wav"


@pytest.fixture(autouse=True)
def cleanup_stt():
    """Limpia instancias cacheadas antes y después de cada test."""
    reset_stt_services()
    yield
    reset_stt_services()


class TestSTTCUDAFallbackAndRecovery:
    """Suite de validación de robustez para faster-whisper en Windows."""

    def test_01_real_spanish_audio_transcription_cpu(self) -> None:
        """1. Verifica transcripción real en español ejecutada nativamente en CPU con int8."""
        assert FIXTURE_WAV.exists(), f"El archivo de audio de prueba no existe: {FIXTURE_WAV}"
        audio_bytes = FIXTURE_WAV.read_bytes()

        service = FasterWhisperSTTService(
            model_size="base",
            device="cpu",
            compute_type="int8",
            default_language="es",
        )
        service.warmup()
        assert service.is_ready is True
        assert service.effective_device == "cpu"
        assert service.effective_compute_type == "int8"

        result = service.transcribe(audio_bytes)
        assert isinstance(result, TranscriptResult)
        assert not result.is_empty
        text_lower = result.text.lower()
        # La grabación dice "¿Hola, Jessica? ¿Cuál es el estado del sistema?"
        assert any(k in text_lower for k in ("jessica", "sistema", "estado", "hola"))
        assert result.confidence >= 0.50
        assert result.duration_ms > 0.0
        assert result.metadata["device"] == "cpu"
        assert result.metadata["compute_type"] == "int8"

    def test_02_consecutive_transcriptions_reuse_loaded_model_no_reload(self) -> None:
        """2. Comprueba que varias transcripciones consecutivas reutilizan el modelo sin recargarlo."""
        audio_bytes = FIXTURE_WAV.read_bytes()

        service = FasterWhisperSTTService(
            model_size="base",
            device="cpu",
            compute_type="int8",
            default_language="es",
        )
        service.load_model()
        model_id = id(service._model)

        r1 = service.transcribe(audio_bytes)
        assert id(service._model) == model_id
        assert not r1.is_empty

        r2 = service.transcribe(audio_bytes)
        assert id(service._model) == model_id
        assert not r2.is_empty

        r3 = service.transcribe(audio_bytes)
        assert id(service._model) == model_id
        assert not r3.is_empty

        # El modelo físico no cambió de identidad en memoria
        assert id(service._model) == model_id

    def test_03_simulated_cuda_failure_recovers_to_cpu_int8_and_retranscribes(self) -> None:
        """3. Añade prueba específica del fallo CUDA (cublas64_12.dll) y recuperación CPU."""
        audio_bytes = FIXTURE_WAV.read_bytes()

        service = FasterWhisperSTTService(
            model_size="base",
            device="auto",
            compute_type="default",
            default_language="es",
        )
        service.load_model()

        # Simular que durante el consumo de segmentos en GPU se dispara la ausencia de cublas64_12.dll
        cuda_error = RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
        original_execute = service._execute_transcribe

        calls = 0

        def failing_first_execute(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                # Simular generador que falla al consumir segmentos
                def failing_gen():
                    raise cuda_error
                    yield None  # unreachable
                return failing_gen(), MagicMock(language="es")
            return original_execute(*args, **kwargs)

        with patch.object(service, "_execute_transcribe", side_effect=failing_first_execute):
            result = service.transcribe(audio_bytes)

        # Verificaciones de recuperación
        assert calls == 2  # 1 intento GPU fallido + 1 reintento CPU exitoso
        assert service.effective_device == "cpu"
        assert service.effective_compute_type == "int8"
        assert service.is_fallback_cpu_used is True
        assert not result.is_empty
        assert any(k in result.text.lower() for k in ("jessica", "sistema", "estado", "hola"))

        # Las siguientes llamadas deben mantenerse en CPU sin intentar GPU
        r_next = service.transcribe(audio_bytes)
        assert not r_next.is_empty
        assert service.effective_device == "cpu"

    def test_04_real_environment_auto_selection_handles_missing_cublas(self) -> None:
        """4. Valida selección 'auto' en el entorno real donde falta cublas64_12.dll."""
        audio_bytes = FIXTURE_WAV.read_bytes()

        service = FasterWhisperSTTService(
            model_size="base",
            device="auto",
            compute_type="default",
            default_language="es",
        )
        # warmup() detectará que CUDA falla con cublas64_12.dll y cambiará a CPU/int8
        service.warmup()
        assert service.is_ready is True
        assert service.effective_device == "cpu"
        assert service.effective_compute_type == "int8"
        assert service.is_fallback_cpu_used is True

        res = service.transcribe(audio_bytes)
        assert not res.is_empty
        assert res.metadata["device"] == "cpu"
        assert res.metadata["compute_type"] == "int8"

    def test_05_silence_and_non_cuda_errors_not_masked(self) -> None:
        """5. Comprueba silencio y asegura que fallos no-CUDA no se oculten ni alucinen."""
        service = FasterWhisperSTTService(
            model_size="base",
            device="cpu",
            compute_type="int8",
        )

        # 5.1 Silencio con buffer vacío
        res_empty = service.transcribe(b"")
        assert res_empty.is_empty
        assert res_empty.metadata.get("silence") is True

        # 5.2 Silencio con ceros PCM (16000 muestras = 1 segundo de silencio absoluto)
        silent_pcm = b"\x00\x00" * 16000
        res_silent = service.transcribe(silent_pcm)
        assert res_silent.is_empty
        assert res_silent.metadata.get("silence") is True

        # 5.3 Error de formato de audio corrupto (no debe ocultarse ni follar a CPU falso)
        with pytest.raises(STTAudioFormatError):
            service.transcribe(b"CORRUPT_NOT_A_WAV_AND_ODD_LEN_BYTES_123")

    def test_06_e2e_audio_to_core_pipeline_without_microphone(self) -> None:
        """6. Valida flujo completo extremo a extremo: Audio físico -> STT -> Core -> Respuesta."""
        audio_bytes = FIXTURE_WAV.read_bytes()
        service = FasterWhisperSTTService(
            model_size="base",
            device="cpu",
            compute_type="int8",
            default_language="es",
        )
        transcript = service.transcribe(audio_bytes)
        assert not transcript.is_empty

        agent = JessycaLocalAgent.get_instance()
        request = JessycaRequest(
            session_id="test_voice_session_e2e",
            user_input=transcript.text,
            modality=InputModality.VOICE,
        )
        response = agent.interact(request)

        # El core debe recibir la entrada de voz transcrita y responder coherentemente
        assert response is not None
        assert response.status is not None
        response_text = response.spoken_text or response.response_text or ""
        assert len(response_text) > 0
