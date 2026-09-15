"""Motor de Captura, Calibración y Diagnóstico de Audio por Voz (audio_capture.py - Fase 51.1).

Implementa:
1. Inspección diagnóstica de dispositivos de micrófono (MicrophoneDiagnostics).
2. Calibración dinámica de ruido ambiente (AmbientNoiseCalibrator).
3. Captura continua con buffer circular de pre-roll (300-500ms), histeresis VAD y post-roll (500-800ms).
4. Detección diferenciada de causas de descarte (VoiceDiscardReason).
5. Mensajes claros y no técnicos al usuario según el tipo de fallo.
6. Emisión de telemetría técnica (VoiceCaptureDiagnostic) respetando la privacidad.
"""

from __future__ import annotations

import collections
import math
import struct
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.logger import get_logger
from services.voice.audio_input import AudioChunk
from services.voice.continuous_voice_session import AudioPreRollBuffer
from services.voice.device_resolver import (
    ResolvedAudioDevice,
    VoiceDeviceResolver,
    get_voice_device_resolver,
)
from services.voice.vad_service import EnergyVADService
from services.voice.voice_diagnostics import (
    VoiceCaptureDiagnostic,
    VoiceDiscardReason,
    get_voice_telemetry,
)

logger = get_logger("jessyca.voice.capture")


@dataclass(frozen=True)
class MicrophoneDeviceInfo:
    """Información técnica de un dispositivo de entrada de audio."""

    index: int
    name: str
    sample_rate: int = 16000
    channels: int = 1
    is_default: bool = False
    is_available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "is_default": self.is_default,
            "is_available": self.is_available,
        }


class MicrophoneDiagnostics:
    """Diagnóstico e inspección de dispositivos de entrada de audio del sistema."""

    @staticmethod
    def inspect_devices() -> list[MicrophoneDeviceInfo]:
        """Lista todos los dispositivos de micrófono detectados en Windows."""
        devices: list[MicrophoneDeviceInfo] = []
        try:
            import speech_recognition as sr  # type: ignore[import-untyped]
            names = sr.Microphone.list_microphone_names()
            for idx, name in enumerate(names):
                devices.append(
                    MicrophoneDeviceInfo(
                        index=idx,
                        name=name,
                        sample_rate=16000,
                        channels=1,
                        is_default=(idx == 0),
                        is_available=True,
                    )
                )
        except Exception as e:
            logger.warning(f"[MIC DIAGNOSTICS] No se pudieron listar dispositivos de micrófono: {e}")
            devices.append(
                MicrophoneDeviceInfo(
                    index=0,
                    name="Default Microphone (Fallback)",
                    sample_rate=16000,
                    channels=1,
                    is_default=True,
                    is_available=False,
                )
            )
        return devices

    @staticmethod
    def get_default_device() -> MicrophoneDeviceInfo:
        """Retorna el dispositivo predeterminado del sistema."""
        devices = MicrophoneDiagnostics.inspect_devices()
        for d in devices:
            if d.is_default:
                return d
        return devices[0] if devices else MicrophoneDeviceInfo(0, "Default Microphone", 16000, 1, True, True)

    @staticmethod
    def resolve_best_microphone(preferred_patterns: list[str] | None = None) -> ResolvedAudioDevice:
        """Resuelve el mejor micrófono físico disponible delegando en VoiceDeviceResolver (Fase 51.2)."""
        resolver = VoiceDeviceResolver(preferred_microphones=preferred_patterns)
        return resolver.resolve_input_device()


@dataclass(frozen=True)
class NoiseCalibrationResult:
    """Resultado formal de la calibración de ruido ambiente."""

    noise_floor_rms: float
    avg_rms: float
    peak_rms: float
    recommended_start_threshold: float
    recommended_end_threshold: float
    duration_sec: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "noise_floor_rms": self.noise_floor_rms,
            "avg_rms": self.avg_rms,
            "peak_rms": self.peak_rms,
            "recommended_start_threshold": self.recommended_start_threshold,
            "recommended_end_threshold": self.recommended_end_threshold,
            "duration_sec": self.duration_sec,
            "timestamp": self.timestamp.isoformat(),
        }


class AmbientNoiseCalibrator:
    """Calibrador de ruido de fondo para ajuste adaptativo de umbrales VAD."""

    @staticmethod
    def calibrate_from_chunks(chunks: list[AudioChunk], duration_sec: float = 1.0) -> NoiseCalibrationResult:
        """Calcula métricas de ruido ambiente y sugiere umbrales de histeresis a partir de chunks."""
        if not chunks:
            # Fallback seguro con valores estándar
            return NoiseCalibrationResult(
                noise_floor_rms=80.0,
                avg_rms=100.0,
                peak_rms=150.0,
                recommended_start_threshold=300.0,
                recommended_end_threshold=180.0,
                duration_sec=duration_sec,
            )

        energies = [c.energy_rms for c in chunks if c.energy_rms > 0.0]
        if not energies:
            avg_rms = 50.0
            peak_rms = 100.0
            noise_floor = 40.0
        else:
            avg_rms = sum(energies) / len(energies)
            peak_rms = max(energies)
            # El 25% percentil o valor mínimo como noise floor
            sorted_e = sorted(energies)
            noise_floor = sorted_e[int(len(sorted_e) * 0.25)] if len(sorted_e) > 4 else sorted_e[0]

        # Umbrales con histeresis:
        # start_threshold: ruido base * 2.5 (mínimo 200.0, máximo 900.0)
        # end_threshold: start_threshold * 0.65
        rec_start = max(200.0, min(900.0, max(noise_floor * 2.5, avg_rms * 1.8)))
        rec_end = max(120.0, rec_start * 0.65)

        logger.info(
            f"[NOISE CALIBRATION] Ruido Base: {noise_floor:.1f} RMS | Promedio: {avg_rms:.1f} | "
            f"Pico: {peak_rms:.1f} -> Umbrales VAD: Start={rec_start:.1f}, End={rec_end:.1f}"
        )

        return NoiseCalibrationResult(
            noise_floor_rms=noise_floor,
            avg_rms=avg_rms,
            peak_rms=peak_rms,
            recommended_start_threshold=rec_start,
            recommended_end_threshold=rec_end,
            duration_sec=duration_sec,
        )


@dataclass(frozen=True)
class VoiceCaptureResult:
    """Resultado formal de una captura de voz con clasificación y feedback."""

    text: str
    confidence: float
    discard_reason: VoiceDiscardReason
    user_feedback_message: str
    diagnostic: VoiceCaptureDiagnostic
    is_success: bool
    eos_timestamp: float = 0.0
    eos_to_stt_start_ms: float = 0.0
    stt_duration_ms: float = 0.0

    @property
    def has_text(self) -> bool:
        return bool(self.text and self.text.strip())


class CalibratedVoiceCaptureEngine:
    """Motor integral y calibrado de captura de audio y VAD con histeresis y pre/post roll."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        pre_roll_ms: int = 400,
        post_roll_ms: int = 600,
        min_speech_ms: int = 300,
        max_capture_ms: int = 300000,
        silence_timeout_ms: int = 2500,
        confidence_threshold: float = 0.50,
        language: str = "es",
        vad_service: EnergyVADService | None = None,
        device_index: int | None = None,
        device_resolver: VoiceDeviceResolver | None = None,
        resolved_device: ResolvedAudioDevice | None = None,
        adaptive_eos_enabled: bool = True,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.pre_roll_ms = pre_roll_ms
        self.post_roll_ms = post_roll_ms
        self.min_speech_ms = min_speech_ms
        self.max_capture_ms = max_capture_ms
        self.silence_timeout_ms = silence_timeout_ms
        self.confidence_threshold = confidence_threshold
        self.language = language
        self.adaptive_eos_enabled = adaptive_eos_enabled
        self.device_resolver = device_resolver or get_voice_device_resolver()

        self.resolved_device: ResolvedAudioDevice | None = resolved_device
        if resolved_device is not None:
            self.device_index: int | None = resolved_device.index
        elif device_index is not None:
            self.device_index = device_index
        else:
            try:
                self.resolved_device = self.device_resolver.resolve_input_device()
                self.device_index = self.resolved_device.index
            except Exception as e:
                logger.warning(f"[VOICE CAPTURE] Fallo al resolver dispositivo ({e}). Usando índice predeterminado.")
                self.device_index = None

        # Configuración del buffer de pre-roll (chunks de ~50ms)
        max_preroll_chunks = max(4, int(pre_roll_ms / 50))
        self.pre_roll_buffer = AudioPreRollBuffer(max_chunks=max_preroll_chunks)

        self.vad_service = vad_service or EnergyVADService(
            energy_threshold=350.0,
            start_threshold=350.0,
            end_threshold=200.0,
            silence_timeout_seconds=silence_timeout_ms / 1000.0,
            silence_end_seconds=1.0,
            silence_end_short_seconds=1.0,
            silence_end_extended_seconds=1.35,
            pause_tolerance_seconds=1.2,
            adaptive_eos_enabled=adaptive_eos_enabled,
            max_speech_duration_seconds=max_capture_ms / 1000.0,
        )

        self._recognizer: Any = None
        self._microphone: Any = None
        self._is_calibrated = False
        self._lock = threading.RLock()
        self._init_speech_recognition()

    def _init_speech_recognition(self) -> None:
        """Inicializa el reconocedor nativo con el micrófono resuelto."""
        try:
            import speech_recognition as sr
            self._recognizer = sr.Recognizer()
            self._recognizer.energy_threshold = 300
            self._recognizer.dynamic_energy_threshold = False  # Usamos nuestra propia histeresis adaptativa
            self._recognizer.pause_threshold = max(0.5, self.post_roll_ms / 1000.0)
            self._recognizer.phrase_threshold = max(0.2, self.min_speech_ms / 1000.0)
            self._microphone = sr.Microphone(
                device_index=self.device_index,
                sample_rate=self.sample_rate,
            )
            dev_desc = self.resolved_device.display_name if self.resolved_device else f"Índice {self.device_index}"
            logger.info(f"[VOICE CAPTURE] Micrófono inicializado: {dev_desc} (sample_rate: {self.sample_rate}Hz)")
        except Exception as e:
            logger.warning(f"[VOICE CAPTURE] Advertencia inicializando SpeechRecognition: {e}")

    def calibrate_ambient_noise(self, duration_sec: float = 1.0) -> NoiseCalibrationResult:
        """Ejecuta una calibración en vivo del micrófono para sintonizar los umbrales de histeresis."""
        with self._lock:
            if not self._microphone or not self._recognizer:
                res = AmbientNoiseCalibrator.calibrate_from_chunks([], duration_sec)
                self._is_calibrated = True
                return res

            try:
                dev_desc = self.resolved_device.display_name if self.resolved_device else "micrófono"
                logger.info(f"[VOICE CAPTURE] Calibrando micrófono ({dev_desc}) durante {duration_sec:.1f}s...")
                with self._microphone as source:
                    self._recognizer.adjust_for_ambient_noise(source, duration=duration_sec)

                energy = float(getattr(self._recognizer, "energy_threshold", 300.0))
                # Ajustar thresholds con histeresis
                rec_start = max(200.0, min(800.0, energy * 1.3))
                rec_end = max(120.0, rec_start * 0.65)
                self.vad_service.update_thresholds(rec_start, rec_end)

                result = NoiseCalibrationResult(
                    noise_floor_rms=energy * 0.7,
                    avg_rms=energy,
                    peak_rms=energy * 1.5,
                    recommended_start_threshold=rec_start,
                    recommended_end_threshold=rec_end,
                    duration_sec=duration_sec,
                )
                self._is_calibrated = True
                return result
            except Exception as e:
                logger.error(f"[VOICE CAPTURE] Fallo durante calibración: {e}")
                res = AmbientNoiseCalibrator.calibrate_from_chunks([], duration_sec)
                self._is_calibrated = True
                return res

    def evaluate_adaptive_stream(
        self,
        chunk_stream: Iterable[bytes],
        sample_rate: int = 16000,
        sample_width: int = 2,
        timeout: float = 7.0,
        failsafe_watchdog_sec: float = 300.0,
    ) -> tuple[bytes, dict[str, Any]]:
        """Núcleo adaptativo de captura y detección de fin de habla (Adaptive End-of-Speech).

        Evalúa el flujo continuo de audio distinguiendo:
        1. Espera de inicio de voz con retención circular de pre-roll.
        2. Detección de inicio de voz ([EOS] voice_started).
        3. Captura continua con histeresis RMS tolerando pausas naturales ([EOS] silence_started, [EOS] voice_resumed).
        4. Fin de habla adaptativo según longitud de frase ([EOS] end_of_speech).
        5. Preservación íntegra de post-roll ([EOS] post_roll preserved).
        6. Watchdog de seguridad técnica contra micrófono atascado ([EOS] failsafe_watchdog).
        """
        import speech_recognition as sr

        bytes_per_sample = max(1, sample_width)
        bytes_per_second = float(sample_rate * bytes_per_sample)

        # Buffer circular de pre-roll
        preroll_duration_sec = self.pre_roll_ms / 1000.0
        preroll_buffer: collections.deque[bytes] = collections.deque()
        preroll_bytes_total = 0
        target_preroll_bytes = int(preroll_duration_sec * bytes_per_second)

        captured_frames: list[bytes] = []
        elapsed_wait_audio_sec = 0.0
        voice_started = False
        wall_start_wait_ts = time.monotonic()

        # FASE 1: Espera de voz inicial (Waiting for Speech)
        for chunk in chunk_stream:
            chunk_bytes = bytes(chunk)
            if not chunk_bytes:
                continue

            chunk_dur = len(chunk_bytes) / bytes_per_second
            elapsed_wait_audio_sec += chunk_dur

            # Mantener pre-roll circular
            preroll_buffer.append(chunk_bytes)
            preroll_bytes_total += len(chunk_bytes)
            while preroll_bytes_total > target_preroll_bytes and len(preroll_buffer) > 1:
                dropped = preroll_buffer.popleft()
                preroll_bytes_total -= len(dropped)

            # Comprobar timeout de espera sin voz
            wall_wait_elapsed = time.monotonic() - wall_start_wait_ts
            if timeout > 0 and (elapsed_wait_audio_sec > timeout or wall_wait_elapsed > timeout):
                logger.info(f"[EOS] Timeout de espera sin voz ({elapsed_wait_audio_sec:.2f}s > {timeout:.2f}s).")
                raise sr.WaitTimeoutError("listening timed out while waiting for phrase to start")

            rms = self._compute_rms(chunk_bytes)
            if rms >= self.vad_service.start_threshold:
                voice_started = True
                logger.info(
                    f"[EOS] voice_started (RMS: {rms:.1f} >= start_threshold: {self.vad_service.start_threshold:.1f})"
                )
                captured_frames.extend(preroll_buffer)
                break

        if not voice_started:
            raise sr.WaitTimeoutError("listening timed out while waiting for phrase to start")

        # FASE 2: Captura Continua con Silencio Adaptativo y Watchdog
        total_speech_sec = chunk_dur
        silence_sec = 0.0
        in_pause = False
        wall_speech_start_ts = time.monotonic()
        end_reason = "end_of_speech"

        for chunk in chunk_stream:
            chunk_bytes = bytes(chunk)
            if not chunk_bytes:
                break
            chunk_dur = len(chunk_bytes) / bytes_per_second
            captured_frames.append(chunk_bytes)

            # Watchdog de seguridad técnica (failsafe watchdog contra micrófono o stream atascado)
            wall_speech_elapsed = time.monotonic() - wall_speech_start_ts
            if total_speech_sec >= failsafe_watchdog_sec or wall_speech_elapsed >= failsafe_watchdog_sec:
                logger.warning(
                    f"[EOS] [FAILSAFE WATCHDOG] Activado ({total_speech_sec:.1f}s speech / {wall_speech_elapsed:.1f}s wall). "
                    "Protección técnica contra micrófono o VAD atascado."
                )
                end_reason = "failsafe_watchdog"
                break

            rms = self._compute_rms(chunk_bytes)
            is_speech_chunk = (rms >= self.vad_service.end_threshold)

            if is_speech_chunk:
                total_speech_sec += chunk_dur
                if in_pause and silence_sec >= 0.25:
                    logger.info(f"[EOS] voice_resumed (tras pausa de {silence_sec:.2f}s)")
                in_pause = False
                silence_sec = 0.0
            else:
                silence_sec += chunk_dur
                if not in_pause and silence_sec >= 0.35:
                    in_pause = True
                    logger.info(f"[EOS] silence_started duration={silence_sec:.2f}s")

                # Cálculo del umbral adaptativo
                if total_speech_sec < 1.2:
                    # Comando corto (ej. "abre el bloc de notas") -> umbral ágil de 1.0s
                    adaptive_silence = self.vad_service.silence_end_short_seconds
                else:
                    # Pregunta conversacional o compleja (ej. física 5s, 30s, 60s)
                    # Tolera pausas naturales de reflexión (hasta 1.2s - 1.35s)
                    adaptive_silence = self.vad_service.silence_end_extended_seconds

                if silence_sec >= adaptive_silence:
                    logger.info(
                        f"[EOS] end_of_speech duration={silence_sec:.2f}s "
                        f"total_speech={total_speech_sec:.2f}s (umbral adaptativo: {adaptive_silence:.2f}s)"
                    )
                    end_reason = "end_of_speech"
                    break

        # FASE 3: Preservación de Post-Roll y Emisión Final
        logger.info(f"[EOS] post_roll preserved ({self.post_roll_ms}ms)")
        total_audio_sec = sum(len(f) for f in captured_frames) / bytes_per_second
        logger.info(f"[EOS] utterance_final listo para STT (duración audio: {total_audio_sec:.2f}s)")

        metadata = {
            "end_reason": end_reason,
            "total_speech_sec": total_speech_sec,
            "silence_sec": silence_sec,
            "total_audio_sec": total_audio_sec,
            "voice_started": voice_started,
        }
        return b"".join(captured_frames), metadata

    def _listen_adaptive(
        self,
        source: Any,
        timeout: float = 7.0,
        failsafe_watchdog_sec: float = 300.0,
    ) -> Any:
        """Graba audio desde el micrófono en vivo usando evaluación continua de Adaptive End-of-Speech."""
        import speech_recognition as sr

        def mic_stream() -> Iterable[bytes]:
            while True:
                buf = source.stream.read(source.CHUNK)
                if not buf:
                    break
                yield buf

        audio_bytes, _ = self.evaluate_adaptive_stream(
            chunk_stream=mic_stream(),
            sample_rate=source.SAMPLE_RATE,
            sample_width=source.SAMPLE_WIDTH,
            timeout=timeout,
            failsafe_watchdog_sec=failsafe_watchdog_sec,
        )
        return sr.AudioData(audio_bytes, source.SAMPLE_RATE, source.SAMPLE_WIDTH)

    def capture_and_transcribe(
        self,
        mode: str = "IDLE",
        timeout: float = 7.0,
        phrase_time_limit: float | None = None,
        custom_audio_bytes: bytes | None = None,
    ) -> VoiceCaptureResult:
        """Captura audio del usuario con Adaptive End-of-Speech, transcribe y emite diagnósticos."""
        with self._lock:
            start_ts = time.time()
            diag = VoiceCaptureDiagnostic(
                mode=mode,
                sample_rate=self.sample_rate,
                channels=self.channels,
                pre_roll_ms=self.pre_roll_ms,
                post_roll_ms=self.post_roll_ms,
            )

            # 1. Si se proporciona audio sintético (para testing determinista)
            if custom_audio_bytes is not None:
                return self._process_simulated_audio(custom_audio_bytes, diag, start_ts)

            # 2. Captura real de micrófono mediante Adaptive End-of-Speech
            if not self._microphone or not self._recognizer:
                diag_data = diag.to_dict()
                diag_data["discard_reason"] = VoiceDiscardReason.DEVICE_ERROR.value
                diag_data["duration_ms"] = (time.time() - start_ts) * 1000.0
                final_diag = VoiceCaptureDiagnostic.model_validate(diag_data)
                get_voice_telemetry().record_capture(final_diag)
                return VoiceCaptureResult(
                    text="",
                    confidence=0.0,
                    discard_reason=VoiceDiscardReason.DEVICE_ERROR,
                    user_feedback_message="[El micrófono no está disponible.]",
                    diagnostic=final_diag,
                    is_success=False,
                )

            import speech_recognition as sr
            try:
                with self._microphone as source:
                    watchdog_limit = (
                        phrase_time_limit
                        if (phrase_time_limit is not None and phrase_time_limit < 300.0)
                        else (self.max_capture_ms / 1000.0)
                    )
                    audio_data = self._listen_adaptive(
                        source,
                        timeout=timeout,
                        failsafe_watchdog_sec=watchdog_limit,
                    )
                t_eos = time.perf_counter()

                raw_bytes = audio_data.get_raw_data()
                rms = self._compute_rms(raw_bytes)

                # 3. Transcripción con Google Speech Recognition en español
                t_stt_start = time.perf_counter()
                eos_to_stt_start_ms = (t_stt_start - t_eos) * 1000.0
                text = self._recognizer.recognize_google(audio_data, language="es-ES")
                t_stt_end = time.perf_counter()
                stt_duration_ms = (t_stt_end - t_stt_start) * 1000.0
                text_clean = (text or "").strip()
                confidence = 0.90 if text_clean else 0.0

                diag_data = diag.to_dict()
                diag_data["duration_ms"] = (time.time() - start_ts) * 1000.0
                diag_data["audio_rms"] = rms
                diag_data["vad_detected"] = True
                diag_data["stt_attempted"] = True
                diag_data["stt_text"] = text_clean
                diag_data["stt_confidence"] = confidence
                diag_data["eos_to_stt_start_ms"] = eos_to_stt_start_ms
                diag_data["stt_duration_ms"] = stt_duration_ms
                diag_data["discard_reason"] = VoiceDiscardReason.NONE.value

                final_diag = VoiceCaptureDiagnostic.model_validate(diag_data)
                final_diag.log_diagnostic()
                get_voice_telemetry().record_capture(final_diag)

                return VoiceCaptureResult(
                    text=text_clean,
                    confidence=confidence,
                    discard_reason=VoiceDiscardReason.NONE,
                    user_feedback_message="",
                    diagnostic=final_diag,
                    is_success=True,
                    eos_timestamp=t_eos,
                    eos_to_stt_start_ms=eos_to_stt_start_ms,
                    stt_duration_ms=stt_duration_ms,
                )

            except sr.WaitTimeoutError:
                # Silencio prolongado
                diag_data = diag.to_dict()
                diag_data["duration_ms"] = (time.time() - start_ts) * 1000.0
                diag_data["discard_reason"] = VoiceDiscardReason.NO_AUDIO.value
                final_diag = VoiceCaptureDiagnostic.model_validate(diag_data)
                get_voice_telemetry().record_capture(final_diag)
                return VoiceCaptureResult(
                    text="",
                    confidence=0.0,
                    discard_reason=VoiceDiscardReason.NO_AUDIO,
                    user_feedback_message="[No detecté voz. Habla un poco más cerca del micrófono.]",
                    diagnostic=final_diag,
                    is_success=False,
                )

            except sr.UnknownValueError:
                # Habla ininteligible o baja confianza
                diag_data = diag.to_dict()
                diag_data["duration_ms"] = (time.time() - start_ts) * 1000.0
                diag_data["stt_attempted"] = True
                diag_data["discard_reason"] = VoiceDiscardReason.EMPTY_TRANSCRIPT.value
                final_diag = VoiceCaptureDiagnostic.model_validate(diag_data)
                get_voice_telemetry().record_capture(final_diag)
                return VoiceCaptureResult(
                    text="",
                    confidence=0.0,
                    discard_reason=VoiceDiscardReason.EMPTY_TRANSCRIPT,
                    user_feedback_message="[Te escuché, pero no pude entender la frase. Intenta de nuevo.]",
                    diagnostic=final_diag,
                    is_success=False,
                )

            except sr.RequestError as req_err:
                logger.error(f"[VOICE CAPTURE] Error del servicio STT: {req_err}")
                diag_data = diag.to_dict()
                diag_data["duration_ms"] = (time.time() - start_ts) * 1000.0
                diag_data["discard_reason"] = VoiceDiscardReason.OTHER.value
                final_diag = VoiceCaptureDiagnostic.model_validate(diag_data)
                get_voice_telemetry().record_capture(final_diag)
                return VoiceCaptureResult(
                    text="",
                    confidence=0.0,
                    discard_reason=VoiceDiscardReason.OTHER,
                    user_feedback_message="[Error de conexión con el servicio de voz.]",
                    diagnostic=final_diag,
                    is_success=False,
                )

            except Exception as e:
                logger.error(f"[VOICE CAPTURE] Error de captura: {e}")
                diag_data = diag.to_dict()
                diag_data["duration_ms"] = (time.time() - start_ts) * 1000.0
                diag_data["discard_reason"] = VoiceDiscardReason.DEVICE_ERROR.value
                final_diag = VoiceCaptureDiagnostic.model_validate(diag_data)
                get_voice_telemetry().record_capture(final_diag)
                return VoiceCaptureResult(
                    text="",
                    confidence=0.0,
                    discard_reason=VoiceDiscardReason.DEVICE_ERROR,
                    user_feedback_message="[El micrófono no respondió adecuadamente.]",
                    diagnostic=final_diag,
                    is_success=False,
                )

    def _process_simulated_audio(
        self,
        audio_bytes: bytes,
        diag: VoiceCaptureDiagnostic,
        start_ts: float,
    ) -> VoiceCaptureResult:
        """Procesa un buffer de audio en memoria para pruebas y validaciones deterministas."""
        rms = self._compute_rms(audio_bytes)
        duration_ms = (len(audio_bytes) / float(self.sample_rate * 2)) * 1000.0

        if not audio_bytes or len(audio_bytes) < 100:
            diag_data = diag.to_dict()
            diag_data["duration_ms"] = duration_ms
            diag_data["audio_rms"] = rms
            diag_data["discard_reason"] = VoiceDiscardReason.NO_AUDIO.value
            final_diag = VoiceCaptureDiagnostic.model_validate(diag_data)
            return VoiceCaptureResult(
                text="",
                confidence=0.0,
                discard_reason=VoiceDiscardReason.NO_AUDIO,
                user_feedback_message="[No detecté voz. Habla un poco más cerca del micrófono.]",
                diagnostic=final_diag,
                is_success=False,
            )

        if duration_ms < self.min_speech_ms:
            diag_data = diag.to_dict()
            diag_data["duration_ms"] = duration_ms
            diag_data["audio_rms"] = rms
            diag_data["discard_reason"] = VoiceDiscardReason.TOO_SHORT.value
            final_diag = VoiceCaptureDiagnostic.model_validate(diag_data)
            return VoiceCaptureResult(
                text="",
                confidence=0.0,
                discard_reason=VoiceDiscardReason.TOO_SHORT,
                user_feedback_message="[Audio demasiado breve o ruido descartado.]",
                diagnostic=final_diag,
                is_success=False,
            )

        if rms < self.vad_service.end_threshold:
            diag_data = diag.to_dict()
            diag_data["duration_ms"] = duration_ms
            diag_data["audio_rms"] = rms
            diag_data["discard_reason"] = VoiceDiscardReason.LOW_ENERGY.value
            final_diag = VoiceCaptureDiagnostic.model_validate(diag_data)
            return VoiceCaptureResult(
                text="",
                confidence=0.0,
                discard_reason=VoiceDiscardReason.LOW_ENERGY,
                user_feedback_message="[Volumen de voz demasiado bajo.]",
                diagnostic=final_diag,
                is_success=False,
            )

        # Simular transcripción exitosa de prueba
        diag_data = diag.to_dict()
        diag_data["duration_ms"] = duration_ms
        diag_data["audio_rms"] = rms
        diag_data["vad_detected"] = True
        diag_data["stt_attempted"] = True
        diag_data["stt_text"] = "Hola Jessica abre el bloc de notas"
        diag_data["stt_confidence"] = 0.95
        diag_data["discard_reason"] = VoiceDiscardReason.NONE.value

        final_diag = VoiceCaptureDiagnostic.model_validate(diag_data)
        get_voice_telemetry().record_capture(final_diag)

        return VoiceCaptureResult(
            text="Hola Jessica abre el bloc de notas",
            confidence=0.95,
            discard_reason=VoiceDiscardReason.NONE,
            user_feedback_message="",
            diagnostic=final_diag,
            is_success=True,
        )

    def _compute_rms(self, data: bytes) -> float:
        """Calcula el RMS de un buffer PCM de 16 bits."""
        if not data:
            return 0.0
        num_samples = len(data) // 2
        if num_samples == 0:
            return 0.0
        try:
            samples = struct.unpack(f"<{num_samples}h", data[: num_samples * 2])
            sum_sq = sum(s * s for s in samples)
            return math.sqrt(sum_sq / num_samples)
        except Exception:
            return 0.0
