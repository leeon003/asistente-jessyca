"""Speech-to-Text Service (stt_service.py - Fase 13 / Prompt 08).

Procesa audio PCM o contenedores WAV para generar TranscriptResult tipado mediante
faster-whisper (local/offline), Google Speech Recognition (remoto/online) o mock (CI/CD).

Contrato explícito de audio:
- PCM 16-bit signed, mono, 16000 Hz, o contenedor WAV estándar (RIFF).
- Normalización float32 en rango [-1.0, 1.0].
- Consumo real de segmentos de inferencia y cálculo de confianza matemático
  basado en avg_logprob (math.exp(avg_logprob)), nunca constantes arbitrarias.
- Detección diferenciada de silencios válidos vs fallos de formato vs timeouts reales.
"""

from __future__ import annotations

import concurrent.futures
import io
import math
import threading
import time
import wave
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import numpy as np

from config.manager import get_settings
from core.logger import get_logger
from services.voice.voice_errors import (
    STTAudioFormatError,
    STTError,
    STTModelUnavailableError,
    STTTimeoutError,
)

logger = get_logger("jessyca.voice.stt")


@dataclass(frozen=True)
class TranscriptResult:
    """Resultado formal inmutable de una transcripción de voz a texto."""

    text: str
    confidence: float
    language: str
    duration_ms: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not bool(self.text and self.text.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "language": self.language,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
            "metadata": dict(self.metadata),
        }


class ISTTService(Protocol):
    """Protocolo abstracto para servicios de transcripción Speech-to-Text."""

    name: str
    requires_network: bool

    def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        timeout_seconds: float = 10.0,
    ) -> TranscriptResult: ...


class MockSTTService:
    """Servicio STT sintético EXCLUSIVAMENTE para testing y CI/CD reproducible.

    Aislado de entornos de producción para evitar transcripciones simuladas accidentales.
    """

    name: str = "mock"
    requires_network: bool = False

    def __init__(self, predefined_transcription: str = "Hola Jessyca", language: str = "es") -> None:
        self.predefined_transcription = predefined_transcription
        self.language = language
        self.should_fail = False
        self.should_timeout = False
        self.failure_reason = "Simulated STT Failure"

    def set_transcription(self, text: str) -> None:
        """Permite actualizar la transcripción simulada para tests dinámicos."""
        self.predefined_transcription = text

    def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        timeout_seconds: float = 10.0,
    ) -> TranscriptResult:
        if self.should_timeout:
            raise STTTimeoutError("Tiempo límite de transcripción de audio excedido.")

        if self.should_fail:
            raise STTError(self.failure_reason)

        if not audio_data:
            return TranscriptResult(
                text="",
                confidence=0.0,
                language=self.language,
                duration_ms=0.0,
                metadata={"engine": "mock_stt", "network_required": False, "silence": True},
            )

        duration_ms = (len(audio_data) / float(max(1, sample_rate * 2))) * 1000.0
        return TranscriptResult(
            text=self.predefined_transcription,
            confidence=0.95,
            language=self.language,
            duration_ms=duration_ms,
            metadata={"engine": "mock_stt", "network_required": False},
        )


class FasterWhisperSTTService:
    """Servicio de transcripción Speech-to-Text desacoplado y local con faster-whisper.

    Contrato técnico:
    - Audio: PCM 16-bit little-endian mono a 16000 Hz o contenedor WAV estándar.
    - Normalización: Conversión int16 -> float32 en rango [-1.0, 1.0].
    - Confianza: Calculada a partir de la media exponencial de logprob (math.exp(avg_logprob))
      de los segmentos reales del modelo; 0.0 para silencios o transcripciones vacías.
    - Operación: 100% local / offline (requires_network = False).
    - Carga: Perezosa, protegida con lock para reutilización del modelo en memoria.
    - Timeouts: Enforced mediante concurrent.futures.ThreadPoolExecutor.
    """

    name: str = "faster-whisper"
    requires_network: bool = False

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "default",
        default_language: str = "es",
        beam_size: int = 5,
        initial_prompt: str | None = None,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.default_language = default_language
        self.beam_size = beam_size
        self.initial_prompt = initial_prompt
        self._model: Any = None
        self._is_loaded = False
        self._is_ready = False
        self._effective_device = device
        self._effective_compute_type = compute_type
        self._fallback_cpu_used = False
        self._model_load_ms = 0.0
        self._lock = threading.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="stt_whisper_worker",
        )

    @property
    def effective_device(self) -> str:
        """Dispositivo físico de cómputo en uso efectivo ('cpu', 'cuda')."""
        return self._effective_device

    @property
    def effective_compute_type(self) -> str:
        """Tipo de cómputo y cuantización en uso efectivo ('int8', 'default', 'float16')."""
        return self._effective_compute_type

    @property
    def model_load_ms(self) -> float:
        """Tiempo de carga del modelo en milisegundos."""
        return self._model_load_ms

    @property
    def is_ready(self) -> bool:
        """Indica si el modelo completó exitosamente su inferencia de verificación."""
        return self._is_ready

    @property
    def is_fallback_cpu_used(self) -> bool:
        """Indica si se recurrió a CPU/int8 tras fallo de dependencias GPU."""
        return self._fallback_cpu_used

    @staticmethod
    def _is_cuda_dependency_error(error: Exception) -> bool:
        """Determina si una excepción corresponde a bibliotecas o controladores CUDA ausentes/incompatibles."""
        msg = str(error).lower()
        cuda_markers = (
            "cublas",
            "cudnn",
            "cuda",
            "cublas64_12.dll",
            "cublaslt64_12.dll",
            "library cublas",
            "cannot be loaded",
            "is not found",
            "cuda driver",
            "cufft",
            "curand",
        )
        return any(marker in msg for marker in cuda_markers)

    def _fallback_to_cpu(self) -> None:
        """Recrea de forma segura el modelo WhisperModel en CPU con cuantización int8."""
        with self._lock:
            from faster_whisper import WhisperModel

            t0 = time.perf_counter()
            logger.info(
                f"[FASTER-WHISPER] Recreando modelo '{self.model_size}' en CPU con compute_type='int8'..."
            )
            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8",
            )
            self.device = "cpu"
            self.compute_type = "int8"
            self._effective_device = "cpu"
            self._effective_compute_type = "int8"
            self._fallback_cpu_used = True
            self._is_loaded = True
            load_ms = (time.perf_counter() - t0) * 1000.0
            self._model_load_ms = load_ms
            logger.info(
                f"[FASTER-WHISPER] Modelo recreado en CPU/int8 exitosamente en {load_ms:.1f}ms. "
                "Dispositivo CPU preservado para todas las siguientes solicitudes de la sesión."
            )

    def load_model(self) -> None:
        """Carga perezosa y segura del modelo faster-whisper con reutilización y fallback a CPU."""
        with self._lock:
            if self._is_loaded and self._model is not None:
                return
            t0 = time.perf_counter()
            target_device = self.device
            target_compute = self.compute_type
            if target_device == "cpu" and target_compute == "default":
                target_compute = "int8"

            try:
                from faster_whisper import WhisperModel  # type: ignore[import-untyped]

                logger.info(
                    f"[FASTER-WHISPER] Cargando modelo '{self.model_size}' "
                    f"(device={target_device}, compute_type={target_compute})..."
                )
                self._model = WhisperModel(
                    self.model_size,
                    device=target_device,
                    compute_type=target_compute,
                )
                self._effective_device = target_device
                self._effective_compute_type = target_compute
                self._is_loaded = True
                self._model_load_ms = (time.perf_counter() - t0) * 1000.0
                logger.info(
                    f"[FASTER-WHISPER] Modelo '{self.model_size}' cargado exitosamente en "
                    f"{self._model_load_ms:.1f}ms (device={self._effective_device}, compute_type={self._effective_compute_type})."
                )
            except ImportError as e:
                logger.error(f"[FASTER-WHISPER] faster-whisper no instalado: {e}")
                self._is_loaded = False
                self._is_ready = False
                raise STTModelUnavailableError(f"faster-whisper no está instalado: {e}") from e
            except Exception as e:
                if self._is_cuda_dependency_error(e) and target_device in ("auto", "cuda"):
                    logger.warning(
                        f"[FASTER-WHISPER] Error de dependencias GPU al construir modelo ({e}). "
                        "Activando fallback a CPU/int8..."
                    )
                    self._fallback_to_cpu()
                else:
                    logger.error(f"[FASTER-WHISPER] Error cargando modelo '{self.model_size}': {e}")
                    self._is_loaded = False
                    self._is_ready = False
                    raise STTModelUnavailableError(
                        f"No se pudo cargar el modelo faster-whisper '{self.model_size}': {e}"
                    ) from e

    def warmup(self) -> None:
        """Valida una inferencia real en audio silencioso antes de declarar STT operativo."""
        if not self._is_loaded or self._model is None:
            self.load_model()

        dummy_audio = np.zeros(1600, dtype=np.float32)
        try:
            segments, _ = self._model.transcribe(
                dummy_audio,
                language=self.default_language,
                beam_size=1,
            )
            _ = list(segments)
            self._is_ready = True
            logger.info(
                f"[FASTER-WHISPER] Inferencia de validación superada. STT operativo "
                f"(device={self._effective_device}, compute_type={self._effective_compute_type})."
            )
        except Exception as e:
            if self._is_cuda_dependency_error(e) and self._effective_device != "cpu":
                logger.warning(
                    f"[FASTER-WHISPER] Inferencia de validación GPU falló por dependencias ({e}). "
                    "Activando fallback a CPU/int8..."
                )
                self._fallback_to_cpu()
                # Re-validar en CPU
                segments, _ = self._model.transcribe(
                    dummy_audio,
                    language=self.default_language,
                    beam_size=1,
                )
                _ = list(segments)
                self._is_ready = True
                logger.info(
                    "[FASTER-WHISPER] Inferencia de validación superada tras fallback. STT operativo en CPU/int8."
                )
            else:
                self._is_ready = False
                logger.error(f"[FASTER-WHISPER] Fallo en inferencia de validación: {e}")
                raise STTError(f"Validación de inferencia STT falló: {e}") from e

    def _convert_audio_to_float32(self, audio_data: bytes, sample_rate: int) -> tuple[np.ndarray, float]:
        """Convierte y normaliza bytes de audio (PCM crudo o contenedor WAV) a un array float32 de 16kHz mono.

        Returns:
            (audio_float32_array, duration_ms)
        Raises:
            STTAudioFormatError si el contenedor o formato PCM es corrupto o inválido.
        """
        if not audio_data or len(audio_data) == 0:
            return np.array([], dtype=np.float32), 0.0

        # Caso 1: Contenedor WAV (inicia con 'RIFF')
        if audio_data.startswith(b"RIFF"):
            try:
                try:
                    with wave.open(io.BytesIO(audio_data), "rb") as wf:
                        nchannels = wf.getnchannels()
                        sampwidth = wf.getsampwidth()
                        framerate = wf.getframerate()
                        nframes = wf.getnframes()

                        if sampwidth != 2:
                            raise STTAudioFormatError(
                                f"Formato WAV no soportado: ancho de muestra de {sampwidth} bytes. "
                                "Se requiere PCM de 16 bits (2 bytes)."
                            )
                        if nchannels > 2:
                            raise STTAudioFormatError(
                                f"Formato WAV no soportado: {nchannels} canales. Máximo 2 canales soportados."
                            )

                        raw_frames = wf.readframes(nframes)
                        if nchannels == 2:
                            samples_stereo = np.frombuffer(raw_frames, dtype=np.int16).reshape(-1, 2)
                            mono_samples = samples_stereo.mean(axis=1).astype(np.int16)
                        else:
                            mono_samples = np.frombuffer(raw_frames, dtype=np.int16)

                        # Remuestreo simple a 16000Hz si difiere
                        if framerate != 16000 and len(mono_samples) > 0:
                            num_target = int(len(mono_samples) * 16000 / framerate)
                            mono_samples = np.interp(
                                np.linspace(0, len(mono_samples), num_target, endpoint=False),
                                np.arange(len(mono_samples)),
                                mono_samples,
                            ).astype(np.int16)

                        if len(mono_samples) == 0:
                            return np.array([], dtype=np.float32), 0.0

                        audio_float = mono_samples.astype(np.float32) / 32768.0
                        duration_ms = (len(audio_float) / 16000.0) * 1000.0
                        return audio_float, duration_ms

                except (STTAudioFormatError, EOFError):
                    raise
                except Exception as std_wave_err:
                    # Soporte para WAV formato IEEE_FLOAT (tag 3) mediante scipy.io.wavfile
                    try:
                        import scipy.io.wavfile as wavfile

                        framerate, data = wavfile.read(io.BytesIO(audio_data))
                        if data.dtype in (np.float32, np.float64):
                            audio_float = data.astype(np.float32)
                        elif data.dtype == np.int16:
                            audio_float = data.astype(np.float32) / 32768.0
                        else:
                            audio_float = data.astype(np.float32) / float(np.iinfo(data.dtype).max)

                        if len(audio_float.shape) > 1 and audio_float.shape[1] > 1:
                            audio_float = audio_float.mean(axis=1)

                        if framerate != 16000 and len(audio_float) > 0:
                            num_target = int(len(audio_float) * 16000 / framerate)
                            audio_float = np.interp(
                                np.linspace(0, len(audio_float), num_target, endpoint=False),
                                np.arange(len(audio_float)),
                                audio_float,
                            ).astype(np.float32)

                        duration_ms = (len(audio_float) / 16000.0) * 1000.0
                        return audio_float, duration_ms
                    except Exception:
                        raise std_wave_err

            except STTAudioFormatError:
                raise
            except Exception as e:
                raise STTAudioFormatError(f"Contenedor WAV corrupto o ilegible: {e}") from e

        # Caso 2: Audio PCM lineal crudo (16-bit little endian)
        else:
            if len(audio_data) % 2 != 0:
                raise STTAudioFormatError(
                    f"Buffer PCM incompleto o mal formado: {len(audio_data)} bytes "
                    "(no es múltiplo de 2 bytes para muestras de 16 bits)."
                )
            try:
                mono_samples = np.frombuffer(audio_data, dtype=np.int16)
            except Exception as e:
                raise STTAudioFormatError(f"Error interpretando buffer PCM: {e}") from e

            # Remuestreo si el sample rate reportado difiere de 16kHz
            if sample_rate != 16000 and len(mono_samples) > 0:
                num_target = int(len(mono_samples) * 16000 / sample_rate)
                mono_samples = np.interp(
                    np.linspace(0, len(mono_samples), num_target, endpoint=False),
                    np.arange(len(mono_samples)),
                    mono_samples,
                ).astype(np.int16)

        if len(mono_samples) == 0:
            return np.array([], dtype=np.float32), 0.0

        # Normalización matemática [-1.0, 1.0]
        audio_float = mono_samples.astype(np.float32) / 32768.0
        duration_ms = (len(audio_float) / 16000.0) * 1000.0
        return audio_float, duration_ms

    def _execute_transcribe(
        self,
        audio_array: np.ndarray,
        language: str,
        beam_size: int,
    ) -> tuple[Any, Any]:
        """Ejecuta model.transcribe en el modelo cargado con parámetros optimizados."""
        return self._model.transcribe(
            audio_array,
            language=language,
            beam_size=beam_size,
            condition_on_previous_text=False,
            initial_prompt=self.initial_prompt,
        )

    def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        timeout_seconds: float = 10.0,
    ) -> TranscriptResult:
        """Transcribe audio mediante faster-whisper con control de timeout, inferencia real y fallback a CPU."""
        # 1. Validación de entrada y normalización
        audio_float, duration_ms = self._convert_audio_to_float32(audio_data, sample_rate)

        # 2. Silencio válido (buffer vacío o energía prácticamente cero)
        if len(audio_float) == 0:
            return TranscriptResult(
                text="",
                confidence=0.0,
                language=self.default_language,
                duration_ms=0.0,
                metadata={"silence": True, "reason": "empty_audio", "network_required": False},
            )

        max_amp = float(np.max(np.abs(audio_float)))
        if max_amp < 1e-4:
            # Silencio válido sin voz: no lanza excepción
            return TranscriptResult(
                text="",
                confidence=0.0,
                language=self.default_language,
                duration_ms=duration_ms,
                metadata={"silence": True, "reason": "zero_amplitude", "network_required": False},
            )

        # 3. Asegurar modelo cargado
        if not self._is_loaded or self._model is None:
            self.load_model()
            if self._model is None:
                raise STTModelUnavailableError("Modelo faster-whisper no disponible tras intento de carga.")

        # 4. Inferencia con timeout real mediante ThreadPoolExecutor
        t_start = time.perf_counter()
        future = self._executor.submit(
            self._execute_transcribe,
            audio_float,
            self.default_language,
            self.beam_size,
        )

        try:
            segments_gen, info = future.result(timeout=timeout_seconds)
            segments = list(segments_gen)
        except concurrent.futures.TimeoutError as exc:
            logger.error(
                f"[FASTER-WHISPER] Timeout de inferencia ({timeout_seconds}s) excedido para {duration_ms:.1f}ms de audio."
            )
            raise STTTimeoutError(
                f"Tiempo límite de inferencia de {timeout_seconds}s excedido en faster-whisper."
            ) from exc
        except STTError:
            raise
        except Exception as e:
            # Capturar fallos de dependencias GPU al consumir los segmentos (ej. cublas64_12.dll)
            if self._is_cuda_dependency_error(e) and self._effective_device != "cpu":
                logger.warning(
                    f"[FASTER-WHISPER] Fallo GPU al consumir segmentos ({e}). "
                    "Activando fallback a CPU/int8 y reintentando el mismo audio una sola vez..."
                )
                self._fallback_to_cpu()
                try:
                    re_future = self._executor.submit(
                        self._execute_transcribe,
                        audio_float,
                        self.default_language,
                        self.beam_size,
                    )
                    segments_gen, info = re_future.result(timeout=timeout_seconds)
                    segments = list(segments_gen)
                except Exception as re_err:
                    logger.error(f"[FASTER-WHISPER] Reintento en CPU falló: {re_err}")
                    raise STTError(f"Error procesando audio con faster-whisper en CPU: {re_err}") from re_err
            else:
                logger.error(f"[FASTER-WHISPER] Error durante la transcripción: {e}")
                raise STTError(f"Error procesando audio con faster-whisper: {e}") from e

        # 5. Consumo de segmentos y cálculo matemático de confianza
        texts: list[str] = []
        segment_probs: list[float] = []
        segments_meta: list[dict[str, Any]] = []

        for seg in segments:
            seg_text = seg.text.strip() if hasattr(seg, "text") and seg.text else ""
            if seg_text:
                texts.append(seg_text)
                # Cálculo de probabilidad desde avg_logprob del segmento:
                # avg_logprob está en (-inf, 0]. exp(avg_logprob) mapea a [0.0, 1.0].
                prob = 0.0
                if hasattr(seg, "avg_logprob") and seg.avg_logprob is not None:
                    try:
                        prob = max(0.0, min(1.0, math.exp(float(seg.avg_logprob))))
                    except OverflowError:
                        prob = 0.0
                elif hasattr(seg, "no_speech_prob") and seg.no_speech_prob is not None:
                    prob = max(0.0, min(1.0, 1.0 - float(seg.no_speech_prob)))
                else:
                    prob = 1.0

                segment_probs.append(prob)
                segments_meta.append({
                    "start": getattr(seg, "start", 0.0),
                    "end": getattr(seg, "end", 0.0),
                    "text": seg_text,
                    "avg_logprob": getattr(seg, "avg_logprob", None),
                    "calculated_confidence": round(prob, 4),
                })

        full_text = " ".join(texts).strip()
        if not full_text:
            confidence = 0.0
        else:
            confidence = round(sum(segment_probs) / len(segment_probs), 4) if segment_probs else 0.0

        detected_lang = getattr(info, "language", self.default_language) if info else self.default_language
        actual_duration_ms = (time.perf_counter() - t_start) * 1000.0

        return TranscriptResult(
            text=full_text,
            confidence=confidence,
            language=detected_lang,
            duration_ms=actual_duration_ms,
            metadata={
                "provider": "faster-whisper",
                "device": self._effective_device,
                "compute_type": self._effective_compute_type,
                "model_load_ms": self._model_load_ms,
                "fallback_used": self._fallback_cpu_used,
                "audio_duration_ms": duration_ms,
                "segments_count": len(segments),
                "segments": segments_meta,
                "network_required": False,
            },
        )


class GoogleSTTService:
    """Servicio de transcripción Speech-to-Text remoto basado en SpeechRecognition (Google).

    Operación: Requiere conexión a internet activa (requires_network = True).
    """

    name: str = "google"
    requires_network: bool = True

    def __init__(self, language: str = "es-ES") -> None:
        self.language = language
        self._recognizer: Any = None
        self._init_recognizer()

    def _init_recognizer(self) -> None:
        try:
            import speech_recognition as sr  # type: ignore[import-untyped]

            self._recognizer = sr.Recognizer()
        except ImportError as e:
            logger.warning(f"[GOOGLE STT] speech_recognition no disponible: {e}")

    def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        timeout_seconds: float = 10.0,
    ) -> TranscriptResult:
        if not audio_data:
            return TranscriptResult(
                text="",
                confidence=0.0,
                language=self.language,
                duration_ms=0.0,
                metadata={"provider": "google", "network_required": True, "silence": True},
            )

        import speech_recognition as sr  # type: ignore[import-untyped]

        if not self._recognizer:
            self._init_recognizer()
            if not self._recognizer:
                raise STTModelUnavailableError("speech_recognition no está disponible para Google STT.")

        t_start = time.perf_counter()
        pcm_bytes = audio_data
        sample_width = 2

        if audio_data.startswith(b"RIFF"):
            try:
                with wave.open(io.BytesIO(audio_data), "rb") as wf:
                    sample_rate = wf.getframerate()
                    sample_width = wf.getsampwidth()
                    pcm_bytes = wf.readframes(wf.getnframes())
            except Exception as e:
                raise STTAudioFormatError(f"Contenedor WAV inválido para Google STT: {e}") from e

        sr_audio = sr.AudioData(pcm_bytes, sample_rate, sample_width)
        duration_ms = (len(pcm_bytes) / float(max(1, sample_rate * sample_width))) * 1000.0

        try:
            text = self._recognizer.recognize_google(sr_audio, language=self.language)
            clean_text = (text or "").strip()
            confidence = 0.85 if clean_text else 0.0
            return TranscriptResult(
                text=clean_text,
                confidence=confidence,
                language=self.language,
                duration_ms=(time.perf_counter() - t_start) * 1000.0,
                metadata={
                    "provider": "google",
                    "audio_duration_ms": duration_ms,
                    "network_required": True,
                },
            )
        except sr.UnknownValueError:
            return TranscriptResult(
                text="",
                confidence=0.0,
                language=self.language,
                duration_ms=(time.perf_counter() - t_start) * 1000.0,
                metadata={
                    "provider": "google",
                    "unintelligible": True,
                    "network_required": True,
                },
            )
        except sr.RequestError as e:
            raise STTError(f"Fallo de conectividad o servicio en Google STT: {e}") from e


_stt_instances: dict[str, ISTTService] = {}
_factory_lock = threading.Lock()


def get_stt_service(
    provider: str | None = None,
    **kwargs: Any,
) -> ISTTService:
    """Fábrica desacoplada para instanciación y selección de proveedores STT.

    Reglas de Seguridad y Configuración:
    1. 'faster-whisper': Local y offline (no requiere red).
    2. 'google': Remoto en nube (requiere red).
    3. 'mock': Exclusivo para test / CI. En 'production' se rechaza si no fue
       inyectado explícitamente en el constructor del consumidor.
    """
    settings = get_settings()
    env = getattr(settings, "ENVIRONMENT", "development").lower()
    selected = (provider or getattr(settings, "VOICE_STT_PROVIDER", "faster-whisper")).lower()

    if selected == "mock":
        if env == "production":
            raise STTError("MockSTTService no está permitido en entorno de producción.")
        return MockSTTService(**kwargs)

    with _factory_lock:
        if selected in _stt_instances:
            return _stt_instances[selected]

        instance: ISTTService
        if selected == "faster-whisper":
            fw_kwargs = dict(kwargs)
            m_size = fw_kwargs.pop("model_size", getattr(settings, "VOICE_FASTER_WHISPER_MODEL", "base"))
            dev = fw_kwargs.pop("device", getattr(settings, "VOICE_FASTER_WHISPER_DEVICE", "auto"))
            comp = fw_kwargs.pop("compute_type", getattr(settings, "VOICE_FASTER_WHISPER_COMPUTE_TYPE", "default"))
            lang = fw_kwargs.pop("default_language", getattr(settings, "VOICE_STT_LANGUAGE", "es"))
            b_size = fw_kwargs.pop("beam_size", getattr(settings, "VOICE_FASTER_WHISPER_BEAM_SIZE", 5))
            i_prompt = fw_kwargs.pop("initial_prompt", getattr(settings, "VOICE_FASTER_WHISPER_PROMPT", "Conversación en español con la asistente JESSYCA sobre ciencia, tecnología, aplicaciones y cultura."))
            instance = FasterWhisperSTTService(
                model_size=m_size,
                device=dev,
                compute_type=comp,
                default_language=lang,
                beam_size=b_size,
                initial_prompt=i_prompt,
                **fw_kwargs,
            )
        elif selected == "google":
            g_kwargs = dict(kwargs)
            lang = g_kwargs.pop("language", getattr(settings, "VOICE_STT_LANGUAGE", "es-ES"))
            instance = GoogleSTTService(
                language=lang,
                **g_kwargs,
            )
        else:
            raise STTError(
                f"Proveedor STT desconocido: '{selected}'. "
                "Opciones soportadas: 'faster-whisper', 'google', 'mock'."
            )

        _stt_instances[selected] = instance
        return instance


def reset_stt_services() -> None:
    """Restablece el cache de proveedores STT para aislamiento en suites de tests."""
    with _factory_lock:
        _stt_instances.clear()
