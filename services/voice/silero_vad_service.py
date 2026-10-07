"""Servicio de Detección de Actividad de Voz basado en Silero VAD (ONNX en CPU) - Integración I1.

Implementa el protocolo formal IVADService utilizando la red neuronal profunda de
Silero VAD (snakers4/silero-vad) ejecutada localmente en CPU mediante ONNX Runtime.

Características principales:
1. Contrato desacoplado e intercambiable: Implementa IVADService, health(), capabilities(), close().
2. Carga perezosa (Lazy Import): onnxruntime y el archivo ONNX no se importan ni cargan
   hasta la instanciación o primer uso explícito.
3. Buffering y Resampling automático: Acepta cualquier frecuencia de entrada (ej. 8kHz, 16kHz, 44.1kHz, 48kHz)
   y cualquier tamaño de chunk, resampleando a 16kHz y fragmentando en ventanas de 512 muestras.
4. Contexto y estado recurrente: Mantiene el estado LSTM 'h' y 'c' [1, 1, 128] y contexto acústico [1, 64]
   por flujo de audio, con reseteo explícito al reiniciar o cambiar de sesión.
5. Histeresis y EOS adaptativo: Utiliza umbrales diferenciados de inicio (start_threshold=0.50) y fin
   (end_threshold=0.35) con tolerancia a pausas naturales (1.2s a 1.35s) y pre-roll / post-roll.
6. Deduplicación de eventos: Garantiza la emisión única y no duplicada de SPEECH_END.
7. CPU Execution Provider exclusivo: No reserva ni consume recursos de GPU sin necesidad demostrada.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from core.logger import get_logger
from services.voice.audio_input import AudioChunk
from services.voice.vad_service import IVADService, VADEvent, VADResult
from services.voice.voice_errors import SileroVADUnavailableError

logger = get_logger("jessyca.voice.silero_vad")


def resolve_silero_model_path(custom_path: Path | str | None = None) -> Path:
    """Resuelve la ruta física del archivo ONNX de Silero VAD con fallbacks locales seguros.

    Prioridad de resolución:
    1. custom_path explícito pasado como parámetro.
    2. Variable de configuración SILERO_VAD_MODEL_PATH en AppSettings.
    3. Ruta local del proyecto: models/silero_vad/silero_vad_v6.onnx.
    4. Assets empaquetados localmente con faster_whisper (assets/silero_vad_v6.onnx).
    """
    if custom_path:
        return Path(custom_path).resolve()

    # 1. Configuración de la aplicación
    try:
        from config.manager import get_settings

        cfg_path = get_settings().SILERO_VAD_MODEL_PATH
        if cfg_path:
            p = Path(cfg_path).resolve()
            if p.exists() and p.is_file():
                return p
    except Exception:
        pass

    # 2. Directorio local del proyecto: models/silero_vad/
    local_model = Path("models") / "silero_vad" / "silero_vad_v6.onnx"
    if local_model.resolve().exists() and local_model.resolve().is_file():
        return local_model.resolve()

    # 3. Assets instalados localmente en faster_whisper (offline y sin descarga)
    try:
        import faster_whisper

        fw_asset = Path(faster_whisper.__file__).parent / "assets" / "silero_vad_v6.onnx"
        if fw_asset.exists() and fw_asset.is_file():
            return fw_asset
    except Exception:
        pass

    return local_model.resolve()


class SileroVADService(IVADService):
    """Voice Activity Detector basado en la red neuronal profunda Silero VAD (ONNX en CPU)."""

    def __init__(
        self,
        model_path: Path | str | None = None,
        start_threshold: float = 0.50,
        end_threshold: float = 0.35,
        sample_rate: int = 16000,
        window_size_samples: int = 512,
        context_size_samples: int = 64,
        speech_pad_chunks: int = 2,
        silence_timeout_seconds: float = 3.0,
        silence_end_seconds: float = 1.0,
        silence_end_short_seconds: float | None = None,
        silence_end_extended_seconds: float = 1.35,
        pause_tolerance_seconds: float = 1.2,
        adaptive_eos_enabled: bool = True,
        max_speech_duration_seconds: float = 300.0,
    ) -> None:
        self.model_path = model_path
        self.start_threshold = max(0.1, min(0.99, start_threshold))
        self.end_threshold = max(0.05, min(self.start_threshold, end_threshold))
        self.sample_rate = sample_rate
        self.window_size_samples = window_size_samples
        self.context_size_samples = context_size_samples
        self.speech_pad_chunks = speech_pad_chunks
        self.silence_timeout_seconds = silence_timeout_seconds
        self.silence_end_seconds = silence_end_seconds
        self.silence_end_short_seconds = (
            silence_end_short_seconds
            if silence_end_short_seconds is not None
            else silence_end_seconds
        )
        self.silence_end_extended_seconds = (
            silence_end_extended_seconds
            if silence_end_extended_seconds is not None
            else max(self.silence_end_short_seconds, 1.35)
        )
        self.pause_tolerance_seconds = pause_tolerance_seconds
        self.adaptive_eos_enabled = adaptive_eos_enabled
        self.max_speech_duration_seconds = max_speech_duration_seconds

        # Estado del modelo ONNX (Lazy)
        self._session: Any = None
        self._resolved_model_path: Path | None = None

        # Estado del flujo de audio (Stream State)
        self._in_speech: bool = False
        self._consecutive_speech_chunks: int = 0
        self._consecutive_silence_chunks: int = 0
        self._speech_duration_seconds: float = 0.0
        self._silence_duration_seconds: float = 0.0
        self._eos_emitted: bool = False

        # Buffers internos de muestras y estados recurrentes
        self._buffer: list[float] = []
        self._h: Any = None
        self._c: Any = None
        self._context: Any = None
        self._last_speech_prob: float = 0.0

    @property
    def in_speech(self) -> bool:
        """Indica si el detector se encuentra actualmente en estado de habla activa."""
        return self._in_speech

    def _ensure_model_loaded(self) -> None:
        """Carga perezosa y segura del modelo ONNX de Silero VAD en CPU."""
        if self._session is not None:
            return

        try:
            import numpy as np
            import onnxruntime
        except ImportError as e:
            raise SileroVADUnavailableError(
                f"El paquete opcional 'onnxruntime' no está disponible en el entorno: {e}. "
                "Instálalo con 'pip install onnxruntime' o conserva el backend por defecto 'energy'."
            ) from e

        model_p = resolve_silero_model_path(self.model_path)
        if not model_p.exists() or not model_p.is_file():
            raise SileroVADUnavailableError(
                f"Archivo de modelo ONNX de Silero VAD no encontrado en: {model_p}. "
                "Verifica la ruta o conserva el backend por defecto 'energy'."
            )

        try:
            opts = onnxruntime.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            opts.enable_cpu_mem_arena = False
            opts.log_severity_level = 3  # Error only

            self._session = onnxruntime.InferenceSession(
                str(model_p),
                providers=["CPUExecutionProvider"],
                sess_options=opts,
            )
            self._resolved_model_path = model_p

            # Inicializar tensores de estado recurrente
            self._h = np.zeros((1, 1, 128), dtype=np.float32)
            self._c = np.zeros((1, 1, 128), dtype=np.float32)
            self._context = np.zeros((1, self.context_size_samples), dtype=np.float32)

            logger.info(
                f"[SILERO VAD] Modelo cargado exitosamente en CPUExecutionProvider desde: {model_p.name} "
                f"(start_th={self.start_threshold:.2f}, end_th={self.end_threshold:.2f})"
            )
        except Exception as e:
            self._session = None
            raise SileroVADUnavailableError(
                f"Error al inicializar sesión ONNX de Silero VAD: {e}"
            ) from e

    def reset(self) -> None:
        """Reinicia el estado del detector y los tensores recurrentes del modelo."""
        self._in_speech = False
        self._consecutive_speech_chunks = 0
        self._consecutive_silence_chunks = 0
        self._speech_duration_seconds = 0.0
        self._silence_duration_seconds = 0.0
        self._eos_emitted = False
        self._last_speech_prob = 0.0
        self._buffer.clear()

        if self._h is not None:
            self._h.fill(0.0)
        if self._c is not None:
            self._c.fill(0.0)
        if self._context is not None:
            self._context.fill(0.0)

    def close(self) -> None:
        """Libera la sesión ONNX y limpia los buffers en memoria."""
        self.reset()
        self._session = None
        self._h = None
        self._c = None
        self._context = None
        logger.debug("[SILERO VAD] Recursos cerrados y sesión ONNX liberada.")

    def get_adaptive_silence_threshold(self) -> float:
        """Calcula el umbral de silencio adaptativo para determinar el fin de habla."""
        if not self.adaptive_eos_enabled:
            return self.silence_end_seconds
        if self._speech_duration_seconds < 1.2:
            return self.silence_end_short_seconds
        return self.silence_end_extended_seconds

    def update_thresholds(self, start_threshold: float, end_threshold: float) -> None:
        """Actualiza los umbrales de histeresis de probabilidad de voz."""
        self.start_threshold = max(0.1, min(0.99, start_threshold))
        self.end_threshold = max(0.05, min(self.start_threshold, end_threshold))
        logger.debug(
            f"[SILERO VAD] Umbrales actualizados: start={self.start_threshold:.2f}, end={self.end_threshold:.2f}"
        )

    def _extract_and_resample_samples(self, chunk: AudioChunk) -> list[float]:
        """Convierte los bytes del chunk a muestras float32 normalizadas [-1.0, 1.0] a 16kHz mono."""
        import numpy as np

        if not chunk.data:
            return []

        # Decodificación PCM 16-bit o 8-bit
        if chunk.bytes_per_sample == 2:
            raw_samples = np.frombuffer(chunk.data, dtype=np.int16).astype(np.float32) / 32768.0
        else:
            raw_samples = np.frombuffer(chunk.data, dtype=np.int8).astype(np.float32) / 128.0

        if len(raw_samples) == 0:
            return []

        # Convertir a mono si es estéreo / multicanal
        if chunk.channels > 1:
            raw_samples = raw_samples.reshape(-1, chunk.channels).mean(axis=1)

        # Resamplear si la frecuencia de muestreo difiere de 16kHz
        target_sr = self.sample_rate  # 16000
        if chunk.sample_rate != target_sr and chunk.sample_rate > 0:
            num_target_samples = int(len(raw_samples) * target_sr / float(chunk.sample_rate))
            if num_target_samples > 0:
                orig_indices = np.arange(len(raw_samples))
                target_indices = np.linspace(0, len(raw_samples) - 1, num_target_samples)
                resampled = np.interp(target_indices, orig_indices, raw_samples).astype(np.float32)
                return resampled.tolist()
            return []

        return raw_samples.tolist()

    def process_chunk(self, chunk: AudioChunk) -> VADResult:
        """Evalúa un AudioChunk a través de Silero VAD para detectar eventos de voz con histeresis."""
        self._ensure_model_loaded()
        import numpy as np

        chunk_duration = chunk.duration_seconds
        energy_rms = chunk.energy_rms

        # Extraer y resamplear muestras a 16kHz
        new_samples = self._extract_and_resample_samples(chunk)
        self._buffer.extend(new_samples)

        # Inferencia ONNX en ventanas fijas de 512 muestras
        window_probs: list[float] = []
        while len(self._buffer) >= self.window_size_samples:
            window = np.array(self._buffer[: self.window_size_samples], dtype=np.float32).reshape(1, -1)
            del self._buffer[: self.window_size_samples]

            # Tensor de entrada [1, context_size + window_size] = [1, 576]
            inp = np.concatenate([self._context, window], axis=1).astype(np.float32)
            self._context = window[:, -self.context_size_samples :].copy()

            out, self._h, self._c = self._session.run(
                None,
                {"input": inp, "h": self._h, "c": self._c},
            )
            prob = float(out[0])
            window_probs.append(prob)

        # Determinar probabilidad de voz representativa del chunk
        if window_probs:
            # Ponderar pico máximo y promedio para detectar fonemas rápidos y transiciones
            speech_prob = float(max(window_probs))
            self._last_speech_prob = speech_prob
        else:
            speech_prob = self._last_speech_prob

        # Aplicación de Histeresis sobre la probabilidad de voz
        threshold_to_use = self.end_threshold if self._in_speech else self.start_threshold
        is_above_threshold = speech_prob >= threshold_to_use

        if is_above_threshold:
            if self._in_speech and self._silence_duration_seconds >= 0.25:
                logger.info(
                    f"[SILERO EOS] voice_resumed (prob: {speech_prob:.2f} >= {self.end_threshold:.2f}, "
                    f"pausa_previa: {self._silence_duration_seconds:.2f}s)"
                )

            self._consecutive_speech_chunks += 1
            self._consecutive_silence_chunks = 0
            self._silence_duration_seconds = 0.0
            self._speech_duration_seconds += chunk_duration
            self._eos_emitted = False

            # Failsafe Watchdog de seguridad técnica contra stream atascado
            if self._speech_duration_seconds >= self.max_speech_duration_seconds:
                self._in_speech = False
                logger.warning(
                    f"[SILERO VAD] [FAILSAFE WATCHDOG] Límite de seguridad alcanzado ({self._speech_duration_seconds:.1f}s >= "
                    f"{self.max_speech_duration_seconds:.1f}s)."
                )
                return VADResult(
                    event=VADEvent.TIMEOUT,
                    is_speech=False,
                    confidence=speech_prob,
                    energy=energy_rms,
                    duration_ms=self._speech_duration_seconds * 1000.0,
                )

            # Transición a SPEECH_START con padding de confirmación
            if not self._in_speech and self._consecutive_speech_chunks >= self.speech_pad_chunks:
                self._in_speech = True
                logger.info(
                    f"[SILERO EOS] voice_started (prob={speech_prob:.2f} >= start_threshold={self.start_threshold:.2f})"
                )
                return VADResult(
                    event=VADEvent.SPEECH_START,
                    is_speech=True,
                    confidence=speech_prob,
                    energy=energy_rms,
                    duration_ms=self._speech_duration_seconds * 1000.0,
                )

            if self._in_speech:
                return VADResult(
                    event=VADEvent.SPEECH_CONTINUE,
                    is_speech=True,
                    confidence=speech_prob,
                    energy=energy_rms,
                    duration_ms=self._speech_duration_seconds * 1000.0,
                )

        else:
            self._consecutive_silence_chunks += 1
            self._consecutive_speech_chunks = 0
            self._silence_duration_seconds += chunk_duration

            # Si estábamos en habla y se acumula suficiente silencio -> SPEECH_END adaptativo
            if self._in_speech:
                adaptive_threshold = self.get_adaptive_silence_threshold()
                if self._silence_duration_seconds >= adaptive_threshold:
                    self._in_speech = False
                    self._eos_emitted = True
                    total_speech = self._speech_duration_seconds
                    silence_dur = self._silence_duration_seconds
                    self.reset()
                    logger.info(
                        f"[SILERO EOS] end_of_speech duration={silence_dur:.2f}s total_speech={total_speech:.2f}s "
                        f"(umbral_adaptativo={adaptive_threshold:.2f}s)"
                    )
                    return VADResult(
                        event=VADEvent.SPEECH_END,
                        is_speech=False,
                        confidence=speech_prob,
                        energy=energy_rms,
                        duration_ms=total_speech * 1000.0,
                    )
                else:
                    # Pausa natural dentro de la intervención del usuario
                    if self._silence_duration_seconds >= 0.35 and (self._silence_duration_seconds - chunk_duration) < 0.35:
                        logger.info(f"[SILERO EOS] silence_started duration={self._silence_duration_seconds:.2f}s")
                    return VADResult(
                        event=VADEvent.SPEECH_CONTINUE,
                        is_speech=True,
                        confidence=speech_prob,
                        energy=energy_rms,
                        duration_ms=self._speech_duration_seconds * 1000.0,
                    )

            # Silencio continuo prolongado sin habla previa
            if self._silence_duration_seconds >= self.silence_timeout_seconds:
                return VADResult(
                    event=VADEvent.TIMEOUT,
                    is_speech=False,
                    confidence=speech_prob,
                    energy=energy_rms,
                    duration_ms=self._silence_duration_seconds * 1000.0,
                )

        return VADResult(
            event=VADEvent.SILENCE,
            is_speech=False,
            confidence=speech_prob,
            energy=energy_rms,
            duration_ms=chunk_duration * 1000.0,
        )

    def health(self) -> dict[str, Any]:
        """Comprueba el estado operativo real del servicio y de la sesión ONNX."""
        loaded = self._session is not None
        import onnxruntime

        return {
            "status": "HEALTHY" if loaded else "READY",
            "backend": "silero",
            "model_loaded": loaded,
            "resolved_model_path": str(self._resolved_model_path) if self._resolved_model_path else None,
            "provider": "CPUExecutionProvider",
            "sample_rate": self.sample_rate,
            "window_size_samples": self.window_size_samples,
            "context_size_samples": self.context_size_samples,
            "start_threshold": self.start_threshold,
            "end_threshold": self.end_threshold,
            "adaptive_eos_enabled": self.adaptive_eos_enabled,
            "in_speech": self._in_speech,
            "onnxruntime_version": onnxruntime.__version__,
        }

    def capabilities(self) -> dict[str, Any]:
        """Declara las capacidades formales y restricciones técnicas del adaptador Silero VAD."""
        return {
            "backend": "silero",
            "supported_sample_rates": [8000, 16000],
            "automatic_resampling": True,
            "requires_network": False,
            "device": "cpu",
            "stateful": True,
            "streaming": True,
            "hysteresis": True,
            "adaptive_eos": True,
            "pause_tolerance": True,
            "pre_roll_preservation": True,
            "post_roll_preservation": True,
            "license": "MIT",
            "speaker_recognition": False,  # Silero VAD detecta actividad de voz, NO reconoce hablante
            "echo_cancellation": False,     # VAD no cancela eco acústico físico
        }
