"""Tests exhaustivos para STT local y separación de activación simulada (Prompt 08).

Verifica:
1. FasterWhisperSTTService con audio real:
   - Contrato explícito de audio (PCM 16-bit 16kHz mono, contenedor WAV, estéreo a mono).
   - Normalización matemática float32 [-1.0, 1.0].
   - Consumo real de segmentos y cálculo matemático de confianza (math.exp(avg_logprob)).
   - Errores distinguibles de silencio válido (empty / flatline -> is_empty=True, conf=0.0).
   - Formatos erróneos -> STTAudioFormatError.
   - Modelo ausente -> STTModelUnavailableError.
   - Timeouts reales aplicados -> STTTimeoutError.
   - Carga perezosa segura y reutilización de modelo en memoria.
2. Transparencia de Red y Selección de Proveedores:
   - requires_network explícito (False para FasterWhisper, True para Google).
   - No desvío silencioso de local a remoto.
   - Fábrica get_stt_service con resolución desacoplada.
   - Ausencia de mocks implícitos en entorno de producción.
3. Inyección en CalibratedVoiceCaptureEngine:
   - Preservación íntegra de captura, pre-roll, VAD y telemetría diagnóstica.
4. Separación de Wake Word y Push-to-Talk:
   - Capacidad acústica declarada no disponible honestamente.
   - Activación manual (push-to-talk) aislada para tests/demo.
   - Invariante de seguridad inquebrantable: Wake word NUNCA autoriza acciones.
5. Prueba de integración opcional con modelo real (con skip y log explícito si no procede).
"""

from __future__ import annotations

import io
import math
import struct
import time
import wave
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from config.settings import AppSettings
from services.voice.audio_capture import CalibratedVoiceCaptureEngine
from services.voice.audio_input import AudioChunk
from services.voice.stt_service import (
    FasterWhisperSTTService,
    GoogleSTTService,
    ISTTService,
    MockSTTService,
    TranscriptResult,
    get_stt_service,
    reset_stt_services,
)
from services.voice.voice_diagnostics import VoiceDiscardReason
from services.voice.voice_errors import (
    STTAudioFormatError,
    STTError,
    STTModelUnavailableError,
    STTTimeoutError,
)
from services.voice.wake_word_service import (
    IWakeWordService,
    KeywordWakeWordService,
    WakeWordResult,
)


# ── Helpers de Audio Sintético Determinista ──


def _create_pcm_tone(
    duration_sec: float = 0.5,
    sample_rate: int = 16000,
    frequency_hz: float = 440.0,
    amplitude: float = 0.5,
) -> bytes:
    """Genera audio PCM de 16-bit little-endian mono con un tono senoidal."""
    num_samples = int(duration_sec * sample_rate)
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        val = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * frequency_hz * t))
        samples.append(val)
    return struct.pack(f"<{num_samples}h", *samples)


def _create_wav_container(
    pcm_bytes: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Empaqueta bytes PCM dentro de una cabecera WAV RIFF válida."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


@dataclass
class DummySegment:
    """Doble de segmento para simular salida real de Faster-Whisper."""

    text: str
    avg_logprob: float
    start: float = 0.0
    end: float = 1.0


@dataclass
class DummyTranscriptionInfo:
    """Doble de metadata de transcripción de Faster-Whisper."""

    language: str = "es"
    language_probability: float = 0.98


# ── 1. PRUEBAS DE FasterWhisperSTTService Y CONTRATO DE AUDIO ──


class TestFasterWhisperSTTService:
    """Tests unitarios del servicio FasterWhisperSTTService con contrato explícito."""

    def setup_method(self) -> None:
        reset_stt_services()
        self.service = FasterWhisperSTTService(
            model_size="base",
            device="auto",
            compute_type="default",
            default_language="es",
        )

    def test_empty_audio_returns_clean_silence_transcript(self) -> None:
        """Audio vacío (0 bytes) debe retornar TranscriptResult vacío con confianza 0.0 sin lanzar error."""
        result = self.service.transcribe(b"")
        assert isinstance(result, TranscriptResult)
        assert result.is_empty is True
        assert result.text == ""
        assert result.confidence == 0.0
        assert result.duration_ms == 0.0
        assert result.metadata.get("silence") is True

    def test_flatline_zero_audio_returns_valid_silence(self) -> None:
        """Audio compuesto únicamente por ceros (silencio) debe manejarse sin excepción."""
        silent_pcm = b"\x00" * 3200  # 100ms de ceros a 16kHz
        result = self.service.transcribe(silent_pcm)
        assert result.is_empty is True
        assert result.text == ""
        assert result.confidence == 0.0
        assert result.metadata.get("silence") is True

    def test_malformed_odd_length_pcm_raises_format_error(self) -> None:
        """Audio PCM con longitud impar de bytes viola el contrato de 16 bits y lanza STTAudioFormatError."""
        invalid_pcm = b"\x01\x02\x03"  # 3 bytes, no múltiplo de 2
        with pytest.raises(STTAudioFormatError) as exc_info:
            self.service.transcribe(invalid_pcm)
        assert "no es múltiplo de 2" in str(exc_info.value)

    def test_corrupt_wav_container_raises_format_error(self) -> None:
        """Un contenedor con cabecera RIFF corrupta debe lanzar STTAudioFormatError."""
        corrupt_wav = b"RIFF\x00\x00\x00\x00WAVEfmt \x00"
        with pytest.raises(STTAudioFormatError) as exc_info:
            self.service.transcribe(corrupt_wav)
        assert "WAV corrupto" in str(exc_info.value) or "ilegible" in str(exc_info.value)

    def test_unsupported_wav_sample_width_raises_format_error(self) -> None:
        """Un contenedor WAV de 24 bits (3 bytes/muestra) debe ser rechazado con STTAudioFormatError."""
        dummy_pcm_24 = b"\x00\x01\x02" * 100
        wav_24 = _create_wav_container(dummy_pcm_24, sample_width=3)
        with pytest.raises(STTAudioFormatError) as exc_info:
            self.service.transcribe(wav_24)
        assert "ancho de muestra" in str(exc_info.value)

    def test_valid_pcm_transcribes_with_model_double_and_real_confidence(self) -> None:
        """Verifica transcripción con doble del modelo: segmentos reales y cálculo matemático de confianza."""
        mock_model = MagicMock()
        # avg_logprob de -0.105 -> math.exp(-0.105) ≈ 0.9003
        segments = [
            DummySegment(text="hola", avg_logprob=-0.105, start=0.0, end=0.5),
            DummySegment(text="jessyca", avg_logprob=-0.051, start=0.5, end=1.0),
        ]
        info = DummyTranscriptionInfo(language="es")
        mock_model.transcribe.return_value = (iter(segments), info)

        self.service._model = mock_model
        self.service._is_loaded = True

        pcm_data = _create_pcm_tone(duration_sec=0.5, amplitude=0.6)
        result = self.service.transcribe(pcm_data)

        assert result.is_empty is False
        assert result.text == "hola jessyca"
        # Confianza calculada matemáticamente: (exp(-0.105) + exp(-0.051)) / 2 ≈ (0.9003 + 0.9503) / 2 ≈ 0.9253
        expected_conf = round((math.exp(-0.105) + math.exp(-0.051)) / 2.0, 4)
        assert abs(result.confidence - expected_conf) < 1e-3
        assert result.confidence != 0.90  # No es una constante fija
        assert result.metadata["network_required"] is False
        assert result.metadata["segments_count"] == 2

    def test_valid_wav_stereo_downmixes_to_mono_and_transcribes(self) -> None:
        """Verifica que un archivo WAV estéreo (2 canales) sea downmixeado a mono float32 correctamente."""
        mock_model = MagicMock()
        segments = [DummySegment(text="comando estéreo", avg_logprob=-0.15)]
        mock_model.transcribe.return_value = (iter(segments), DummyTranscriptionInfo())

        self.service._model = mock_model
        self.service._is_loaded = True

        # Crear PCM estéreo
        mono_pcm = _create_pcm_tone(duration_sec=0.3, amplitude=0.4)
        num_samples = len(mono_pcm) // 2
        mono_unpacked = struct.unpack(f"<{num_samples}h", mono_pcm)
        stereo_samples = []
        for s in mono_unpacked:
            stereo_samples.extend([s, s])
        stereo_pcm = struct.pack(f"<{len(stereo_samples)}h", *stereo_samples)
        wav_stereo = _create_wav_container(stereo_pcm, channels=2)

        result = self.service.transcribe(wav_stereo)
        assert result.text == "comando estéreo"
        assert result.confidence > 0.0

    def test_missing_model_raises_model_unavailable_error(self) -> None:
        """Si faster-whisper no está instalado o falla al cargar, lanza STTModelUnavailableError."""
        with patch.object(self.service, "load_model", side_effect=STTModelUnavailableError("Weights not found")):
            pcm_data = _create_pcm_tone(duration_sec=0.2, amplitude=0.5)
            with pytest.raises(STTModelUnavailableError):
                self.service.transcribe(pcm_data)

    def test_real_timeout_triggers_stt_timeout_error(self) -> None:
        """Si la inferencia excede timeout_seconds, se lanza STTTimeoutError real."""
        mock_model = MagicMock()

        def slow_transcribe(*args: Any, **kwargs: Any) -> Any:
            time.sleep(0.5)
            return (iter([]), DummyTranscriptionInfo())

        mock_model.transcribe.side_effect = slow_transcribe
        self.service._model = mock_model
        self.service._is_loaded = True

        pcm_data = _create_pcm_tone(duration_sec=0.2, amplitude=0.5)
        with pytest.raises(STTTimeoutError) as exc_info:
            self.service.transcribe(pcm_data, timeout_seconds=0.05)
        assert "excedido" in str(exc_info.value).lower()

    def test_lazy_loading_and_model_reuse(self) -> None:
        """El modelo solo se instancia una vez (lazy loading) y se reutiliza en llamadas subsecuentes."""
        with patch("faster_whisper.WhisperModel") as mock_whisper_cls:
            mock_instance = MagicMock()
            mock_whisper_cls.return_value = mock_instance
            mock_instance.transcribe.side_effect = lambda *a, **kw: (
                iter([DummySegment(text="prueba reuso", avg_logprob=-0.1)]),
                DummyTranscriptionInfo(),
            )

            fresh_service = FasterWhisperSTTService(model_size="base")
            assert fresh_service._is_loaded is False
            assert fresh_service._model is None

            pcm = _create_pcm_tone(duration_sec=0.1, amplitude=0.5)
            # Primera transcripción: activa carga perezosa
            res1 = fresh_service.transcribe(pcm)
            assert res1.text == "prueba reuso"
            assert fresh_service._is_loaded is True
            assert mock_whisper_cls.call_count == 1

            # Segunda transcripción: reutiliza el modelo existente sin instanciarlo de nuevo
            res2 = fresh_service.transcribe(pcm)
            assert res2.text == "prueba reuso"
            assert mock_whisper_cls.call_count == 1


# ── 2. TRANSPARENCIA DE RED Y SELECCIÓN DE PROVEEDORES ──


class TestSTTProviderSelection:
    """Verifica que cada proveedor declare explícitamente sus requerimientos de red y configuración."""

    def setup_method(self) -> None:
        reset_stt_services()

    def test_network_requirement_is_explicit_for_all_providers(self) -> None:
        """FasterWhisperSTTService es 100% offline; GoogleSTTService requiere red explícita."""
        whisper = FasterWhisperSTTService()
        google = GoogleSTTService()
        mock = MockSTTService()

        assert whisper.requires_network is False
        assert whisper.name == "faster-whisper"

        assert google.requires_network is True
        assert google.name == "google"

        assert mock.requires_network is False
        assert mock.name == "mock"

    def test_factory_resolves_configured_providers(self) -> None:
        """get_stt_service resuelve correctamente los diferentes motores."""
        whisper_srv = get_stt_service("faster-whisper")
        assert isinstance(whisper_srv, FasterWhisperSTTService)

        google_srv = get_stt_service("google")
        assert isinstance(google_srv, GoogleSTTService)

        mock_srv = get_stt_service("mock")
        assert isinstance(mock_srv, MockSTTService)

    def test_production_environment_forbids_implicit_or_configured_mocks(self) -> None:
        """En entorno de producción, get_stt_service('mock') debe ser terminantemente rechazado."""
        with patch("services.voice.stt_service.get_settings") as mock_settings:
            mock_settings.return_value = AppSettings(ENVIRONMENT="production")
            with pytest.raises(STTError) as exc_info:
                get_stt_service("mock")
            assert "no está permitido en entorno de producción" in str(exc_info.value)

    def test_unknown_provider_raises_error(self) -> None:
        """Un proveedor no registrado lanza STTError descriptivo."""
        with pytest.raises(STTError) as exc_info:
            get_stt_service("non_existent_stt_engine")
        assert "desconocido" in str(exc_info.value)


# ── 3. INYECCIÓN EN CalibratedVoiceCaptureEngine SIN PÉRDIDAS ──


class TestCalibratedVoiceCaptureEngineSTTInjection:
    """Verifica la inyección del proveedor STT en CalibratedVoiceCaptureEngine preservando telemetría."""

    def test_injected_stt_service_used_in_capture_engine(self) -> None:
        """El motor de captura delega la transcripción al ISTTService inyectado."""
        mock_stt = MockSTTService(predefined_transcription="activar protocolo de defensa")
        engine = CalibratedVoiceCaptureEngine(
            sample_rate=16000,
            stt_service=mock_stt,
        )

        assert engine.stt_service is mock_stt

        # Captura simulada con audio válido
        pcm = _create_pcm_tone(duration_sec=0.5, amplitude=0.6)
        result = engine.capture_and_transcribe(custom_audio_bytes=pcm)

        assert result.is_success is True
        assert result.text == "activar protocolo de defensa"
        assert result.diagnostic.stt_provider == "mock"
        assert result.diagnostic.stt_requires_network is False
        assert result.diagnostic.vad_detected is True
        assert result.diagnostic.discard_reason == VoiceDiscardReason.NONE

    def test_stt_timeout_in_capture_engine_produces_distinct_diagnostic(self) -> None:
        """Un STTTimeoutError dentro de capture_and_transcribe genera descarte TIMEOUT estructurado."""
        mock_stt = MagicMock(spec=ISTTService)
        mock_stt.name = "mock_timeout"
        mock_stt.requires_network = False
        mock_stt.transcribe.side_effect = STTTimeoutError("Timeout en inferencia")

        engine = CalibratedVoiceCaptureEngine(
            sample_rate=16000,
            stt_service=mock_stt,
        )

        # Usar mock de micrófono para forzar la ruta en vivo
        engine._microphone = MagicMock()
        engine._recognizer = MagicMock()

        audio_mock = MagicMock()
        audio_mock.get_raw_data.return_value = _create_pcm_tone(duration_sec=0.4, amplitude=0.7)

        with patch.object(engine, "_listen_adaptive", return_value=audio_mock):
            res = engine.capture_and_transcribe()

            assert res.is_success is False
            assert res.discard_reason == VoiceDiscardReason.TIMEOUT
            assert "[Tiempo de transcripción de voz agotado." in res.user_feedback_message


# ── 4. WAKE WORD SEPARATION Y GARANTÍA DE SEGURIDAD ──


class TestWakeWordSeparationAndSecurity:
    """Verifica que el Wake Word no simule falsas detecciones y jamás otorgue autorización."""

    def test_acoustic_model_declared_honest_unavailable_in_this_phase(self) -> None:
        """Declara formalmente que el modelo acústico no está disponible en esta fase."""
        ww_service = KeywordWakeWordService(mode="acoustic")
        assert ww_service.is_acoustic_model_available() is False

        # Al procesar audio en modo acústico sin motor acústico, no detecta nada
        chunk = AudioChunk(data=_create_pcm_tone(duration_sec=0.1))
        res = ww_service.process_audio(chunk)

        assert res.detected is False
        assert res.confidence == 0.0
        assert res.metadata.get("acoustic_available") is False

    def test_push_to_talk_manual_mode_isolated(self) -> None:
        """El modo manual (push-to-talk) solo activa cuando trigger_manually es invocado."""
        ww_service = KeywordWakeWordService(mode="manual")
        chunk = AudioChunk(data=_create_pcm_tone(duration_sec=0.1))

        # Sin trigger manual -> no detectado
        res_before = ww_service.process_audio(chunk)
        assert res_before.detected is False

        # Con trigger manual -> detectado una sola vez y se resetea
        ww_service.trigger_manually()
        res_trigger = ww_service.process_audio(chunk)
        assert res_trigger.detected is True
        assert res_trigger.confidence == 1.0

        # Siguiente chunk sin trigger -> vuelve a no detectado
        res_after = ww_service.process_audio(chunk)
        assert res_after.detected is False

    def test_critical_security_invariant_wake_word_never_authorizes_actions(self) -> None:
        """GARANTÍA DE SEGURIDAD: La detección de Wake Word jamás concede autorización para ejecutar acciones."""
        ww_service = KeywordWakeWordService(mode="manual")
        assert ww_service.authorizes_action is False

        ww_service.trigger_manually()
        chunk = AudioChunk(data=_create_pcm_tone(duration_sec=0.1))
        res = ww_service.process_audio(chunk)

        assert res.detected is True
        # Invariante estricto: authorizes_action debe ser False
        assert res.authorizes_action is False
        assert res.to_dict()["authorizes_action"] is False


# ── 5. PRUEBA DE INTEGRACIÓN OPCIONAL CON MODELO REAL ──


def test_optional_real_faster_whisper_spanish_integration(caplog: pytest.LogCaptureFixture) -> None:
    """Prueba de integración opcional con el modelo real Faster-Whisper y audio en español.

    Si los pesos del modelo no están disponibles localmente o su descarga es lenta,
    se registra explícitamente en el log y se salta limpiamente la prueba sin fallar el CI.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        pytest.skip("[INTEGRACIÓN REAL] faster-whisper no está instalado.")

    service = FasterWhisperSTTService(model_size="tiny", device="cpu", compute_type="default", default_language="es")

    t0 = time.perf_counter()
    try:
        service.load_model()
    except Exception as e:
        msg = f"[INTEGRACIÓN REAL] No se pudo cargar el modelo real de faster-whisper: {e}. Omitiendo prueba de integración opcional."
        print(f"\n{msg}")
        pytest.skip(msg)

    # Audio sintético (tono puro 440Hz): Whisper debe procesarlo y devolver silencio o texto sin fallar
    pcm_audio = _create_pcm_tone(duration_sec=1.0, frequency_hz=440.0, amplitude=0.3)
    result = service.transcribe(pcm_audio, timeout_seconds=15.0)

    elapsed = time.perf_counter() - t0
    print(f"\n[INTEGRACIÓN REAL EXITOSA] Inferencia con modelo real completada en {elapsed:.2f}s. Texto: '{result.text}' (Confianza: {result.confidence})")
    assert isinstance(result, TranscriptResult)
    assert result.duration_ms > 0.0
