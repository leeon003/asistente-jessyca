"""TTS Provider Architecture & Manager (tts_provider.py - Fase 72).

Implementa la abstracción de proveedores de síntesis de voz (BaseTTSProvider),
integración de Pocket TTS (CPU/GPU) y Edge-TTS (es-PE-CamilaNeural), con
TTSManager para selección dinámica, métricas de latencia T1-T4, fallback
transparente no silencioso, suscripción a SpeakRequested en el Event Bus y
gestión limpia de recursos.
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.cancellation import CancellationToken
from core.events.base import SpeakRequested
from core.logger import get_logger
from services.voice.tts_service import (
    DEFAULT_VOICE_NAME,
    EdgeTTSService,
    ITTSService,
    TTSResult,
)
from services.voice.voice_errors import TTSFailureError, VoiceCancelledError

logger = get_logger("jessyca.voice.tts_provider")


@dataclass
class TTSMetrics:
    """Métricas cuantitativas de rendimiento y latencia para operaciones de TTS."""

    t1_request_to_synth_ms: float = 0.0  # Tiempo desde solicitud hasta inicio de síntesis
    t2_first_audio_ms: float = 0.0  # Tiempo hasta disponer de audio reproducible
    t3_total_gen_ms: float = 0.0  # Tiempo total de generación / síntesis
    t4_audio_duration_ms: float = 0.0  # Duración del audio generado
    provider_used: str = ""
    engine_used: str = ""
    voice_name: str = ""
    rtf: float = 0.0  # Real-Time Factor (t3_total_gen_ms / t4_audio_duration_ms)
    fallback_used: bool = False
    is_success: bool = True
    error_message: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def calculate_rtf(self) -> float:
        """Calcula el factor de tiempo real (RTF). Menor a 1.0 significa más rápido que tiempo real."""
        if self.t4_audio_duration_ms > 0:
            self.rtf = (self.t3_total_gen_ms) / self.t4_audio_duration_ms
        else:
            self.rtf = 0.0
        return self.rtf

    def to_dict(self) -> dict[str, Any]:
        return {
            "t1_request_to_synth_ms": round(self.t1_request_to_synth_ms, 2),
            "t2_first_audio_ms": round(self.t2_first_audio_ms, 2),
            "t3_total_gen_ms": round(self.t3_total_gen_ms, 2),
            "t4_audio_duration_ms": round(self.t4_audio_duration_ms, 2),
            "rtf": round(self.calculate_rtf(), 4),
            "provider_used": self.provider_used,
            "engine_used": self.engine_used,
            "voice_name": self.voice_name,
            "fallback_used": self.fallback_used,
            "is_success": self.is_success,
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat(),
        }


class BaseTTSProvider(ABC):
    """Contrato base abstracto para proveedores de síntesis de voz en JESSYCA."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre identificador único del proveedor."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Indica si el proveedor está instalado y listo para operar."""
        ...

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[TTSResult, TTSMetrics]:
        """Sintetiza texto a bytes de audio y recopila métricas T1-T4."""
        ...

    @abstractmethod
    def speak(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[bool, TTSMetrics]:
        """Sintetiza y reproduce el audio en los altavoces del sistema."""
        ...

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Diagnóstico de salud del proveedor."""
        ...

    def stop(self) -> None:
        """Detiene de inmediato cualquier reproducción o generación activa.

        Los proveedores que interactúen con sintetizadores o mixers deben sobreescribir este método.
        """
        return None


class PocketTTSProvider(BaseTTSProvider):
    """Proveedor de síntesis de voz mediante Kyutai Pocket TTS optimizado para CPU/GPU."""

    def __init__(
        self,
        default_voice: str = "alba",
        device: str = "cpu",
        model_instance: Any = None,
    ) -> None:
        self._name = "pocket-tts"
        self.default_voice = default_voice
        self.device = device
        self._model: Any = model_instance
        self._voice_states: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._is_initialized = model_instance is not None
        self._init_error: str | None = None

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        with self._lock:
            if self._model is not None:
                return True
            try:
                import pocket_tts  # type: ignore[import-untyped]  # noqa: F401

                return True
            except ImportError as e:
                self._init_error = str(e)
                return False

    def _ensure_model(self) -> Any:
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from pocket_tts import TTSModel

                logger.info(f"[POCKET-TTS] Cargando modelo en dispositivo: {self.device}...")
                model = TTSModel.load_model()
                if self.device == "cuda":
                    model = model.to("cuda")
                self._model = model
                self._is_initialized = True
                return self._model
            except Exception as e:
                self._init_error = str(e)
                logger.error(f"[POCKET-TTS] Error al cargar modelo Pocket TTS: {e}")
                raise TTSFailureError(f"No se pudo cargar Pocket TTS: {e}") from e

    def _get_voice_state(self, model: Any, voice_name: str) -> Any:
        with self._lock:
            if voice_name in self._voice_states:
                return self._voice_states[voice_name]
            try:
                state = model.get_state_for_audio_prompt(voice_name)
                self._voice_states[voice_name] = state
                return state
            except Exception as e:
                logger.warning(f"[POCKET-TTS] Error obteniendo prompt de voz '{voice_name}': {e}. Usando fallback.")
                state = model.get_state_for_audio_prompt(self.default_voice)
                self._voice_states[voice_name] = state
                return state

    def synthesize(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[TTSResult, TTSMetrics]:
        if cancellation_token and cancellation_token.is_cancelled:
            raise VoiceCancelledError("Síntesis Pocket TTS cancelada antes de iniciar.")

        target_voice = voice or self.default_voice
        metrics = TTSMetrics(
            provider_used=self.name,
            engine_used="pocket_tts",
            voice_name=target_voice,
        )

        clean_text = text.strip()
        if not clean_text:
            return (
                TTSResult(
                    audio_bytes=b"",
                    duration_seconds=0.0,
                    voice_name=target_voice,
                    is_success=True,
                ),
                metrics,
            )

        t_request = time.perf_counter()

        try:
            model = self._ensure_model()
            t_synth_start = time.perf_counter()
            metrics.t1_request_to_synth_ms = (t_synth_start - t_request) * 1000.0

            if cancellation_token and cancellation_token.is_cancelled:
                raise VoiceCancelledError("Síntesis Pocket TTS cancelada.")

            voice_state = self._get_voice_state(model, target_voice)
            audio_tensor = model.generate_audio(voice_state, clean_text)

            t_gen_done = time.perf_counter()
            metrics.t3_total_gen_ms = (t_gen_done - t_synth_start) * 1000.0

            # Conversión de tensor a WAV PCM en memoria
            import scipy.io.wavfile  # type: ignore[import-untyped]

            buf = io.BytesIO()
            sample_rate = getattr(model, "sample_rate", 24000)
            cpu_numpy = audio_tensor.detach().cpu().numpy()
            scipy.io.wavfile.write(buf, sample_rate, cpu_numpy)
            wav_bytes = buf.getvalue()

            t_playable = time.perf_counter()
            metrics.t2_first_audio_ms = (t_playable - t_request) * 1000.0

            # Duración estimada en base a muestras y sample rate
            duration_s = float(len(cpu_numpy)) / float(sample_rate) if sample_rate > 0 else 0.0
            metrics.t4_audio_duration_ms = duration_s * 1000.0
            metrics.calculate_rtf()
            metrics.is_success = True

            result = TTSResult(
                audio_bytes=wav_bytes,
                duration_seconds=duration_s,
                voice_name=target_voice,
                is_success=True,
                metadata={"sample_rate": sample_rate, "device": self.device},
            )
            return result, metrics

        except VoiceCancelledError:
            raise
        except Exception as e:
            metrics.is_success = False
            metrics.error_message = str(e)
            logger.error(f"[POCKET-TTS] Error de síntesis: {e}")
            return (
                TTSResult(
                    audio_bytes=b"",
                    duration_seconds=0.0,
                    voice_name=target_voice,
                    is_success=False,
                    error_message=str(e),
                ),
                metrics,
            )

    def speak(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[bool, TTSMetrics]:
        result, metrics = self.synthesize(text, voice=voice, cancellation_token=cancellation_token)
        if not result.is_success or not result.audio_bytes:
            return False, metrics

        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=1024)

            sound = pygame.mixer.Sound(io.BytesIO(result.audio_bytes))
            sound.play()
            while pygame.mixer.get_busy():
                if cancellation_token and cancellation_token.is_cancelled:
                    sound.stop()
                    pygame.mixer.stop()
                    raise VoiceCancelledError("Reproducción Pocket TTS interrumpida.")
                pygame.time.wait(20)

            return True, metrics
        except VoiceCancelledError:
            raise
        except Exception as e:
            logger.warning(f"[POCKET-TTS] Error al reproducir audio con pygame: {e}")
            metrics.error_message = str(e)
            return False, metrics

    def stop(self) -> None:
        """Detiene la reproducción activa en pygame."""
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.stop()
        except Exception as e:
            logger.debug(f"[POCKET-TTS] Error al detener pygame mixer: {e}")

    def health_check(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.is_available(),
            "initialized": self._is_initialized,
            "device": self.device,
            "default_voice": self.default_voice,
            "cached_voices": list(self._voice_states.keys()),
            "last_error": self._init_error,
        }


class EdgeTTSProvider(BaseTTSProvider):
    """Proveedor de síntesis de voz mediante Edge-TTS con voz es-PE-CamilaNeural."""

    def __init__(
        self,
        default_voice: str = DEFAULT_VOICE_NAME,
        service_instance: ITTSService | None = None,
    ) -> None:
        self._name = "edge-tts"
        self.default_voice = default_voice
        self._service = service_instance or EdgeTTSService(default_voice=default_voice)
        self._lock = threading.RLock()

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        try:
            import edge_tts  # noqa: F401

            return True
        except ImportError:
            return False

    def synthesize(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[TTSResult, TTSMetrics]:
        target_voice = voice or self.default_voice
        metrics = TTSMetrics(
            provider_used=self.name,
            engine_used="edge_tts",
            voice_name=target_voice,
        )

        clean_text = text.strip()
        if not clean_text:
            return (
                TTSResult(
                    audio_bytes=b"",
                    duration_seconds=0.0,
                    voice_name=target_voice,
                    is_success=True,
                ),
                metrics,
            )

        t_start = time.perf_counter()
        metrics.t1_request_to_synth_ms = 0.5  # Inmediato en edge_tts

        try:
            res = self._service.synthesize(
                clean_text,
                voice=target_voice,
                cancellation_token=cancellation_token,
            )
            t_done = time.perf_counter()
            metrics.t3_total_gen_ms = (t_done - t_start) * 1000.0
            metrics.t2_first_audio_ms = metrics.t3_total_gen_ms
            metrics.t4_audio_duration_ms = res.duration_seconds * 1000.0
            metrics.calculate_rtf()
            metrics.is_success = res.is_success
            metrics.error_message = res.error_message
            return res, metrics
        except VoiceCancelledError:
            raise
        except Exception as e:
            metrics.is_success = False
            metrics.error_message = str(e)
            return (
                TTSResult(
                    audio_bytes=b"",
                    duration_seconds=0.0,
                    voice_name=target_voice,
                    is_success=False,
                    error_message=str(e),
                ),
                metrics,
            )

    def speak(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[bool, TTSMetrics]:
        result, metrics = self.synthesize(text, voice=voice, cancellation_token=cancellation_token)
        if not result.is_success or not result.audio_bytes:
            return False, metrics

        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=1024)

            sound = pygame.mixer.Sound(io.BytesIO(result.audio_bytes))
            sound.play()
            while pygame.mixer.get_busy():
                if cancellation_token and cancellation_token.is_cancelled:
                    sound.stop()
                    pygame.mixer.stop()
                    raise VoiceCancelledError("Reproducción Edge-TTS interrumpida.")
                pygame.time.wait(20)

            return True, metrics
        except VoiceCancelledError:
            raise
        except Exception as e:
            logger.warning(f"[EDGE-TTS] Error reproduciendo audio con pygame: {e}")
            metrics.error_message = str(e)
            return False, metrics

    def stop(self) -> None:
        """Detiene la reproducción en pygame y cancela el servicio Edge-TTS."""
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.stop()
        except Exception:
            pass
        if hasattr(self._service, "stop"):
            try:
                self._service.stop()
            except Exception as e:
                logger.debug(f"[EDGE-TTS] Error al invocar service.stop: {e}")

    def health_check(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.is_available(),
            "default_voice": self.default_voice,
        }


class TTSManager:
    """Administrador centralizado de síntesis de voz e intercambio de proveedores."""

    def __init__(
        self,
        preferred_provider: str = "pocket-tts",
        fallback_provider: str = "edge-tts",
        providers: dict[str, BaseTTSProvider] | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._lock = threading.RLock()
        self.preferred_provider_name = preferred_provider
        self.fallback_provider_name = fallback_provider
        self.timeout_seconds = timeout_seconds

        # Registro de proveedores
        if providers is not None:
            self._providers = dict(providers)
        else:
            self._providers = {
                "pocket-tts": PocketTTSProvider(),
                "edge-tts": EdgeTTSProvider(default_voice=DEFAULT_VOICE_NAME),
            }

        # Control de deduplicación de eventos SpeakRequested
        self._handled_event_ids: set[str] = set()
        self._max_handled_events: int = 1000

        # Historial de métricas
        self.last_metrics: TTSMetrics | None = None
        self._temp_files: list[str] = []

        # Estado de reproducción activa y cancelación (Fase 73)
        self._is_playing: bool = False
        self._is_generating: bool = False
        self._current_token: CancellationToken | None = None

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._is_playing

    @property
    def is_generating(self) -> bool:
        with self._lock:
            return self._is_generating

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._is_playing or self._is_generating

    def cancel(self, reason: str = "barge_in") -> bool:
        """Cancela inmediatamente la síntesis o reproducción activa de voz (Barge-in)."""
        with self._lock:
            was_active = self._is_playing or self._is_generating
            logger.info(f"[TTS MANAGER] Cancelación ejecutada ({reason}). Activo previo: {was_active}")

            if self._current_token:
                self._current_token.cancel()

            for p in self._providers.values():
                if hasattr(p, "stop"):
                    try:
                        p.stop()
                    except Exception:
                        pass

            try:
                import pygame

                if pygame.mixer.get_init():
                    pygame.mixer.stop()
            except Exception:
                pass

            self._is_playing = False
            self._is_generating = False
            self._current_token = None
            return was_active

    def register_provider(self, provider: BaseTTSProvider) -> None:
        with self._lock:
            self._providers[provider.name] = provider

    def get_provider(self, name: str) -> BaseTTSProvider | None:
        with self._lock:
            return self._providers.get(name)

    def get_active_provider(self) -> BaseTTSProvider:
        with self._lock:
            pref = self._providers.get(self.preferred_provider_name)
            if pref and pref.is_available():
                return pref
            fallback = self._providers.get(self.fallback_provider_name)
            if fallback and fallback.is_available():
                return fallback
            # Si ninguno está disponible, retorna el preferido para que reporte su error
            return pref or list(self._providers.values())[0]

    def synthesize(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[TTSResult, TTSMetrics]:
        """Sintetiza audio intentando con el proveedor preferido y fallback transparente si falla."""
        token = cancellation_token or self._current_token
        with self._lock:
            pref_provider = self._providers.get(self.preferred_provider_name)
            fb_provider = self._providers.get(self.fallback_provider_name)

        # 1. Intento con proveedor preferido si está disponible
        if pref_provider and pref_provider.is_available():
            try:
                res, metrics = pref_provider.synthesize(
                    text,
                    voice=voice,
                    cancellation_token=token,
                )
                if res.is_success and res.audio_bytes:
                    self.last_metrics = metrics
                    return res, metrics
                logger.warning(
                    f"TTS:\n"
                    f"{pref_provider.name} failed ({res.error_message})\n"
                    f"-> fallback:\n"
                    f"Edge-TTS Camila"
                )
            except VoiceCancelledError:
                raise
            except Exception as e:
                logger.warning(
                    f"TTS:\n"
                    f"{pref_provider.name} failed ({e})\n"
                    f"-> fallback:\n"
                    f"Edge-TTS Camila"
                )
        else:
            logger.info(
                f"TTS:\n"
                f"{self.preferred_provider_name} not available\n"
                f"-> fallback:\n"
                f"Edge-TTS Camila"
            )

        # 2. Activación de Fallback (Edge-TTS Camila)
        if fb_provider and fb_provider.is_available():
            try:
                res, metrics = fb_provider.synthesize(
                    text,
                    voice=voice,
                    cancellation_token=token,
                )
                metrics.fallback_used = True
                self.last_metrics = metrics
                return res, metrics
            except VoiceCancelledError:
                raise
            except Exception as ex2:
                logger.error(f"[TTS MANAGER] Fallback {fb_provider.name} también falló: {ex2}")
                err_metrics = TTSMetrics(
                    provider_used=fb_provider.name,
                    fallback_used=True,
                    is_success=False,
                    error_message=str(ex2),
                )
                self.last_metrics = err_metrics
                return (
                    TTSResult(
                        audio_bytes=b"",
                        duration_seconds=0.0,
                        voice_name=voice or DEFAULT_VOICE_NAME,
                        is_success=False,
                        error_message=str(ex2),
                    ),
                    err_metrics,
                )

        # 3. Ningún proveedor disponible
        err_msg = "Ningún proveedor TTS disponible en el sistema (Pocket TTS y Edge TTS no operativos)."
        logger.error(f"[TTS MANAGER] {err_msg}")
        fail_metrics = TTSMetrics(
            provider_used="none",
            is_success=False,
            error_message=err_msg,
        )
        self.last_metrics = fail_metrics
        return (
            TTSResult(
                audio_bytes=b"",
                duration_seconds=0.0,
                voice_name=voice or DEFAULT_VOICE_NAME,
                is_success=False,
                error_message=err_msg,
            ),
            fail_metrics,
        )

    def speak(
        self,
        text: str,
        voice: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[bool, TTSMetrics]:
        """Sintetiza y reproduce audio con fallback explícito no silencioso y soporte Barge-in."""
        token = cancellation_token or CancellationToken()
        with self._lock:
            self._current_token = token
            self._is_generating = True
            self._is_playing = False
            pref_provider = self._providers.get(self.preferred_provider_name)
            fb_provider = self._providers.get(self.fallback_provider_name)

        try:
            # 1. Intento con proveedor preferido
            if pref_provider and pref_provider.is_available():
                try:
                    with self._lock:
                        self._is_generating = True
                        self._is_playing = False
                    success, metrics = pref_provider.speak(
                        text,
                        voice=voice,
                        cancellation_token=token,
                    )
                    if success:
                        self.last_metrics = metrics
                        return True, metrics
                    logger.warning(
                        f"TTS:\n"
                        f"{pref_provider.name} failed\n"
                        f"-> fallback:\n"
                        f"Edge-TTS Camila"
                    )
                except VoiceCancelledError:
                    logger.info("[TTS MANAGER] Locución cancelada por interrupción del usuario (Barge-in).")
                    c_metrics = TTSMetrics(
                        provider_used=pref_provider.name,
                        is_success=False,
                        error_message="cancelled_by_barge_in",
                    )
                    self.last_metrics = c_metrics
                    return False, c_metrics
                except Exception as e:
                    logger.warning(
                        f"TTS:\n"
                        f"{pref_provider.name} failed ({e})\n"
                        f"-> fallback:\n"
                        f"Edge-TTS Camila"
                    )
            else:
                logger.info(
                    f"TTS:\n"
                    f"{self.preferred_provider_name} not available\n"
                    f"-> fallback:\n"
                    f"Edge-TTS Camila"
                )

            # 2. Fallback a Edge-TTS Camila
            if fb_provider and fb_provider.is_available():
                try:
                    with self._lock:
                        self._is_generating = True
                        self._is_playing = False
                    success, metrics = fb_provider.speak(
                        text,
                        voice=voice,
                        cancellation_token=token,
                    )
                    metrics.fallback_used = True
                    self.last_metrics = metrics
                    return success, metrics
                except VoiceCancelledError:
                    logger.info("[TTS MANAGER] Locución de fallback cancelada por interrupción (Barge-in).")
                    c_metrics = TTSMetrics(
                        provider_used=fb_provider.name,
                        is_success=False,
                        error_message="cancelled_by_barge_in",
                    )
                    self.last_metrics = c_metrics
                    return False, c_metrics
                except Exception as ex2:
                    logger.error(f"[TTS MANAGER] Fallback {fb_provider.name} también falló en speak: {ex2}")
                    metrics = TTSMetrics(
                        provider_used=fb_provider.name,
                        fallback_used=True,
                        is_success=False,
                        error_message=str(ex2),
                    )
                    self.last_metrics = metrics
                    return False, metrics

            # 3. Ninguno disponible
            metrics = TTSMetrics(
                provider_used="none",
                is_success=False,
                error_message="Sin proveedores TTS disponibles para reproducción.",
            )
            self.last_metrics = metrics
            return False, metrics
        finally:
            with self._lock:
                self._is_playing = False
                self._is_generating = False
                if self._current_token is token:
                    self._current_token = None

    def handle_speak_requested(self, event: SpeakRequested) -> tuple[bool, TTSMetrics]:
        """Procesa un evento SpeakRequested publicado en el Event Bus evitando duplicados."""
        event_id = getattr(event, "id", None) or f"{event.text}:{event.timestamp.isoformat()}"
        with self._lock:
            if event_id in self._handled_event_ids:
                logger.debug(f"[TTS MANAGER] Evento SpeakRequested ya procesado ({event_id}), ignorando duplicado.")
                return False, TTSMetrics(is_success=False, error_message="Duplicate event")

            if len(self._handled_event_ids) > self._max_handled_events:
                self._handled_event_ids.clear()
            self._handled_event_ids.add(event_id)

        logger.info(f"[TTS MANAGER] SpeakRequested recibido: '{event.text[:50]}...'")
        return self.speak(event.text, voice=event.voice)

    def connect_event_bus(self, bus: Any) -> None:
        """Conecta el TTS Manager al Event Bus suscribiéndose a SpeakRequested."""
        bus.subscribe(SpeakRequested, self.handle_speak_requested)
        logger.info("[TTS MANAGER] Suscrito a SpeakRequested en el Event Bus.")

    @contextlib.contextmanager
    def managed_temp_file(self, suffix: str = ".wav") -> Generator[str, None, None]:
        """Genera un archivo temporal gestionado que se limpia garantizadamente al salir del contexto."""
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="jessyca_tts_")
        os.close(fd)
        with self._lock:
            self._temp_files.append(path)
        try:
            yield path
        finally:
            with self._lock:
                if path in self._temp_files:
                    self._temp_files.remove(path)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as e:
                    logger.debug(f"[TTS MANAGER] Error al limpiar temporal {path}: {e}")

    def clean_temp_files(self) -> None:
        """Limpia todos los archivos temporales registrados."""
        with self._lock:
            remaining = list(self._temp_files)
            for path in remaining:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            self._temp_files.clear()

    def health_check(self) -> dict[str, Any]:
        with self._lock:
            return {
                "preferred_provider": self.preferred_provider_name,
                "fallback_provider": self.fallback_provider_name,
                "active_provider": self.get_active_provider().name,
                "providers": {name: p.health_check() for name, p in self._providers.items()},
                "last_metrics": self.last_metrics.to_dict() if self.last_metrics else None,
            }


_GLOBAL_TTS_MANAGER: TTSManager | None = None
_GLOBAL_LOCK = threading.Lock()


def get_tts_manager() -> TTSManager:
    """Obtiene la instancia singleton de TTSManager configurada según settings."""
    global _GLOBAL_TTS_MANAGER
    with _GLOBAL_LOCK:
        if _GLOBAL_TTS_MANAGER is None:
            from config.manager import get_settings

            settings = get_settings()
            preferred = getattr(settings, "VOICE_TTS_PROVIDER", "edge-tts")
            fallback = getattr(settings, "VOICE_TTS_FALLBACK", "edge-tts")
            timeout_s = getattr(settings, "VOICE_TTS_TIMEOUT_SECONDS", 10.0)
            pocket_voice = getattr(settings, "VOICE_POCKET_TTS_VOICE", "alba")
            pocket_device = getattr(settings, "VOICE_POCKET_TTS_DEVICE", "cpu")

            pocket_provider = PocketTTSProvider(default_voice=pocket_voice, device=pocket_device)
            edge_provider = EdgeTTSProvider(default_voice=getattr(settings, "VOICE_DEFAULT_VOICE", DEFAULT_VOICE_NAME))

            _GLOBAL_TTS_MANAGER = TTSManager(
                preferred_provider=preferred,
                fallback_provider=fallback,
                providers={
                    "pocket-tts": pocket_provider,
                    "edge-tts": edge_provider,
                },
                timeout_seconds=timeout_s,
            )
        return _GLOBAL_TTS_MANAGER
