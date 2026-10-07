"""Adaptador de inferencia acústica de palabra de activación basado en openWakeWord (Fase I5).

GARANTÍA ABSOLUTA DE SEGURIDAD Y VERACIDAD ACÚSTICA:
1. SEGURIDAD: detected=True ÚNICAMENTE abre la escucha de audio; NUNCA autoriza herramientas ni acciones.
2. VERACIDAD ACÚSTICA: openWakeWord incluye modelos preentrenados en inglés (Alexa, Hey Jarvis, etc.).
   Bajo NINGUNA circunstancia se afirma que renombrar un modelo en inglés o cambiar el parámetro keyword
   a 'Jessyca' crea detección acústica del nombre en español.
   Si no se configura un modelo local compilado/entrenado para la palabra clave, la capacidad se declara
   honestamente como NO DISPONIBLE (is_acoustic_model_available = False).
3. PROCESAMIENTO: Maneja resampling automático a 16kHz, buffering por ventanas (1280 muestras = 80ms),
   umbral configurable, cooldown anti-ráfaga y reset de estado por sesión.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np

from core.logger import get_logger
from services.voice.audio_capture import AudioChunk
from services.voice.wake_word_service import IWakeWordService, WakeWordResult

logger = get_logger("jessyca.services.voice.openwakeword_service")


class OpenWakeWordAcousticService(IWakeWordService):
    """Adaptador desacoplado para detección acústica local con openWakeWord."""

    authorizes_action: bool = False  # Wake word NEVER grants execution rights

    def __init__(
        self,
        keyword: str = "jessyca",
        model_path: str | Path | None = None,
        confidence_threshold: float = 0.60,
        cooldown_seconds: float = 2.0,
        target_sample_rate: int = 16000,
        enabled: bool = True,
        fallback_to_manual: bool = True,
    ) -> None:
        self.keyword = keyword.lower().strip()
        self.model_path = Path(model_path) if model_path else None
        self.confidence_threshold = confidence_threshold
        self.cooldown_seconds = cooldown_seconds
        self.target_sample_rate = target_sample_rate
        self.enabled = enabled
        self.fallback_to_manual = fallback_to_manual

        self._model: Any | None = None
        self._model_loaded: bool = False
        self._load_error: str | None = None
        self._last_trigger_time: float = 0.0
        self._manual_triggered: bool = False
        self._audio_buffer: list[np.ndarray] = []
        self._chunk_size_samples = 1280  # 80ms a 16kHz requeridos por openWakeWord

        # Intentar carga perezosa si hay modelo configurado
        if self.model_path and self.model_path.exists():
            self._load_acoustic_model()

    def _load_acoustic_model(self) -> bool:
        """Carga el modelo acústico local de forma segura."""
        if self._model_loaded:
            return True

        if not self.model_path or not self.model_path.exists():
            self._load_error = f"Modelo acústico no encontrado en la ruta especificada: {self.model_path}"
            logger.info(f"[OPENWAKEWORD] {self._load_error}")
            return False

        try:
            from openwakeword.model import Model

            logger.info(f"[OPENWAKEWORD] Cargando modelo acústico local desde: {self.model_path}")
            self._model = Model(
                wakeword_models=[str(self.model_path)],
                inference_framework="onnx",
            )
            self._model_loaded = True
            self._load_error = None
            logger.info(f"[OPENWAKEWORD] Modelo '{self.keyword}' cargado exitosamente.")
            return True
        except ImportError as err:
            self._load_error = f"Librería 'openwakeword' no disponible: {err}"
            logger.warning(f"[OPENWAKEWORD] {self._load_error}")
            return False
        except Exception as e:
            self._load_error = f"Fallo al inicializar openWakeWord: {e}"
            logger.error(f"[OPENWAKEWORD] {self._load_error}")
            return False

    def is_acoustic_model_available(self) -> bool:
        """Declara con honestidad si existe un modelo acústico real cargado y compatible."""
        if not self.enabled:
            return False
        if self._model_loaded and self._model is not None:
            return True
        return False

    def trigger_manually(self) -> None:
        """Permite activación manual interactiva / Push-to-Talk independiente del motor acústico."""
        self._manual_triggered = True

    def reset(self) -> None:
        """Restablece el estado interno, buffer de audio y memoria del modelo acústico."""
        self._manual_triggered = False
        self._audio_buffer.clear()
        if self._model_loaded and self._model is not None:
            try:
                self._model.reset()
            except Exception:
                pass
        logger.debug("[OPENWAKEWORD] Estado y buffers de audio reiniciados.")

    def _resample_audio(self, audio_data: np.ndarray, orig_sr: int) -> np.ndarray:
        """Re-muestrea audio a 16000 Hz si la tasa de entrada difiere."""
        if orig_sr == self.target_sample_rate:
            return audio_data

        try:
            from scipy import signal
            num_target_samples = int(len(audio_data) * self.target_sample_rate / orig_sr)
            resampled = signal.resample(audio_data, num_target_samples)
            return resampled.astype(np.int16)
        except Exception:
            # Interpolación lineal simple de fallback si falla scipy
            target_length = int(len(audio_data) * self.target_sample_rate / orig_sr)
            if target_length <= 0:
                return audio_data
            indices = np.linspace(0, len(audio_data) - 1, target_length)
            return np.interp(indices, np.arange(len(audio_data)), audio_data).astype(np.int16)

    def process_audio(self, chunk: AudioChunk) -> WakeWordResult:
        """Procesa un fragmento de audio efímero para inferencia acústica.

        INVARIANTE DE SEGURIDAD ABSOLUTA:
        El resultado SIEMPRE tiene authorizes_action=False.
        """
        now = time.time()

        if not self.enabled:
            return WakeWordResult(
                detected=False,
                keyword=self.keyword,
                confidence=0.0,
                metadata={"status": "DISABLED", "authorizes_action": False},
                authorizes_action=False,
            )

        # 1. Soporte de activación manual / Push-to-Talk
        if self._manual_triggered:
            self._manual_triggered = False
            self._last_trigger_time = now
            logger.info(f"[WAKE WORD] Activación manual/Push-to-Talk para '{self.keyword}' recibida.")
            return WakeWordResult(
                detected=True,
                keyword=self.keyword,
                confidence=1.0,
                metadata={"trigger": "manual_push_to_talk", "authorizes_action": False},
                authorizes_action=False,
            )

        # 2. Si no hay modelo acústico disponible
        if not self.is_acoustic_model_available():
            status_reason = self._load_error or "NO_MODEL_CONFIGURED_FOR_KEYWORD"
            return WakeWordResult(
                detected=False,
                keyword=self.keyword,
                confidence=0.0,
                metadata={
                    "status": "ACOUSTIC_MODEL_UNAVAILABLE",
                    "reason": status_reason,
                    "language_note": "openWakeWord preentrenado soporta inglés; se requiere modelo entrenado para español.",
                    "fallback_to_manual": self.fallback_to_manual,
                    "authorizes_action": False,
                },
                authorizes_action=False,
            )

        # 3. Verificación de período de enfriamiento (cooldown anti-ráfaga)
        if now - self._last_trigger_time < self.cooldown_seconds:
            return WakeWordResult(
                detected=False,
                keyword=self.keyword,
                confidence=0.0,
                metadata={"status": "COOLDOWN_ACTIVE", "authorizes_action": False},
                authorizes_action=False,
            )

        # 4. Preparación y resampling del audio
        try:
            # Convertir bytes a int16 si es necesario
            if isinstance(chunk.data, bytes):
                pcm_data = np.frombuffer(chunk.data, dtype=np.int16)
            elif isinstance(chunk.data, np.ndarray):
                pcm_data = chunk.data.astype(np.int16)
            else:
                return WakeWordResult(
                    detected=False,
                    keyword=self.keyword,
                    confidence=0.0,
                    metadata={"error": "INVALID_AUDIO_FORMAT", "authorizes_action": False},
                    authorizes_action=False,
                )

            # Re-muestreo si difiere de 16kHz
            sample_rate = chunk.sample_rate if hasattr(chunk, "sample_rate") and chunk.sample_rate else self.target_sample_rate
            if sample_rate != self.target_sample_rate:
                pcm_data = self._resample_audio(pcm_data, sample_rate)

            # Acumular en buffer
            self._audio_buffer.append(pcm_data)
            all_samples = np.concatenate(self._audio_buffer)

            # Inferencia cuando se alcance al menos 1280 muestras (80ms)
            if len(all_samples) < self._chunk_size_samples:
                return WakeWordResult(
                    detected=False,
                    keyword=self.keyword,
                    confidence=0.0,
                    metadata={"status": "BUFFERING", "samples": len(all_samples)},
                    authorizes_action=False,
                )

            # Tomar las primeras 1280 muestras y conservar el resto en buffer
            frame_to_process = all_samples[:self._chunk_size_samples]
            remaining = all_samples[self._chunk_size_samples:]
            self._audio_buffer = [remaining] if len(remaining) > 0 else []

            # Ejecutar predicción con openWakeWord
            prediction = self._model.predict(frame_to_process)

            # Obtener el score para el modelo cargado
            score = 0.0
            for model_name, score_val in prediction.items():
                if self.keyword in model_name.lower() or len(prediction) == 1:
                    score = float(score_val)
                    break

            is_detected = score >= self.confidence_threshold

            if is_detected:
                self._last_trigger_time = now
                self.reset()
                logger.info(
                    f"[OPENWAKEWORD] ¡Palabra de activación detectada! "
                    f"Keyword='{self.keyword}', Confianza={score:.3f} >= Umbral={self.confidence_threshold}"
                )
                return WakeWordResult(
                    detected=True,
                    keyword=self.keyword,
                    confidence=score,
                    metadata={
                        "engine": "openwakeword",
                        "model_path": str(self.model_path),
                        "score": score,
                        "threshold": self.confidence_threshold,
                        "authorizes_action": False,
                    },
                    authorizes_action=False,
                )

            return WakeWordResult(
                detected=False,
                keyword=self.keyword,
                confidence=score,
                metadata={
                    "engine": "openwakeword",
                    "score": score,
                    "threshold": self.confidence_threshold,
                    "authorizes_action": False,
                },
                authorizes_action=False,
            )

        except Exception as e:
            logger.error(f"[OPENWAKEWORD] Error durante la inferencia de audio: {e}")
            return WakeWordResult(
                detected=False,
                keyword=self.keyword,
                confidence=0.0,
                metadata={"error": str(e), "authorizes_action": False},
                authorizes_action=False,
            )
