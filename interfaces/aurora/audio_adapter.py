"""Adaptador de análisis de audio desacoplado para JESSYCA ORB — Núcleo Aurora.

Diseñado para:
1. Calcular RMS, amplitud normalizada (0.0 - 1.0) e intensidad sin abrir una segunda captura de micro.
2. Identificar el inicio y fin REAL de reproducción TTS (no basándose únicamente en SpeakRequested).
3. Proveer modo de prueba con datos sintéticos identificados explícitamente como simulados (is_simulated=True).
"""

from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass, field
from typing import Any

from interfaces.aurora.visual_states import AuroraVisualState


@dataclass
class AudioMetrics:
    """Métricas cuantitativas de audio en tiempo real para modulación de shaders."""

    rms: float = 0.0
    normalized_amplitude: float = 0.0  # Rango [0.0, 1.0]
    voice_detected: bool = False
    dominant_frequency_hz: float = 0.0
    tts_playback_active: bool = False
    is_simulated: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rms": round(self.rms, 4),
            "normalized_amplitude": round(self.normalized_amplitude, 4),
            "voice_detected": self.voice_detected,
            "dominant_frequency_hz": round(self.dominant_frequency_hz, 1),
            "tts_playback_active": self.tts_playback_active,
            "is_simulated": self.is_simulated,
            "timestamp": self.timestamp,
        }


class AuroraAudioAdapter:
    """Adaptador de audio desacoplado y seguro para el Núcleo Aurora."""

    def __init__(self) -> None:
        self._current_metrics = AudioMetrics(is_simulated=True)
        self._tts_playing = False
        self._last_chunk_time = 0.0
        self._noise_floor = 100.0  # Piso de ruido base para normalización dinámica

    @property
    def current_metrics(self) -> AudioMetrics:
        return self._current_metrics

    def process_pcm_chunk(
        self,
        pcm_bytes: bytes,
        sample_rate: int = 16000,
        sample_width: int = 2,
    ) -> AudioMetrics:
        """Procesa de forma no invasiva un fragmento PCM capturado por el motor de audio real.

        NO abre micrófono ni compite con CalibratedVoiceCaptureEngine.
        """
        if not pcm_bytes or len(pcm_bytes) < sample_width:
            return AudioMetrics(
                tts_playback_active=self._tts_playing,
                is_simulated=False,
            )

        num_samples = len(pcm_bytes) // sample_width
        fmt = f"<{num_samples}h" if sample_width == 2 else f"<{num_samples}b"

        try:
            samples = struct.unpack(fmt, pcm_bytes[: num_samples * sample_width])
            sum_squares = sum(s * s for s in samples)
            rms = math.sqrt(sum_squares / num_samples)

            # Normalización suave entre 0.0 y 1.0 respecto a techo de 32767
            max_val = 32767.0 if sample_width == 2 else 127.0
            norm_amp = min(1.0, max(0.0, (rms - self._noise_floor) / (max_val * 0.4)))

            # Detección simple de voz por umbral de energía
            voice_detected = norm_amp > 0.08

            # Cálculo de frecuencia dominante aproximada (Zero-Crossing Rate)
            zcr = sum(
                1 for i in range(1, len(samples))
                if (samples[i] >= 0 and samples[i - 1] < 0) or (samples[i] < 0 and samples[i - 1] >= 0)
            )
            dominant_freq = (zcr * sample_rate) / (2.0 * num_samples) if num_samples > 0 else 0.0

            self._current_metrics = AudioMetrics(
                rms=rms,
                normalized_amplitude=norm_amp,
                voice_detected=voice_detected,
                dominant_frequency_hz=dominant_freq,
                tts_playback_active=self._tts_playing,
                is_simulated=False,
                timestamp=time.time(),
            )
            return self._current_metrics
        except Exception:
            return AudioMetrics(tts_playback_active=self._tts_playing, is_simulated=False)

    def notify_tts_playback_start(self) -> None:
        """Notificación de inicio real de reproducción acústica del TTS."""
        self._tts_playing = True
        self._current_metrics.tts_playback_active = True

    def notify_tts_playback_end(self) -> None:
        """Notificación de finalización real de reproducción acústica del TTS."""
        self._tts_playing = False
        self._current_metrics.tts_playback_active = False

    def generate_simulated_metrics(
        self,
        visual_state: AuroraVisualState,
        elapsed_time: float,
    ) -> AudioMetrics:
        """Genera métricas sintéticas de demostración para el prototipo visual independiente.

        Marcado explícitamente con is_simulated=True para no confundir con audio real.
        """
        if visual_state == AuroraVisualState.LISTENING:
            # Simulación de onda de voz humana al escuchar
            base = 0.25 + 0.25 * math.sin(elapsed_time * 5.0) * math.cos(elapsed_time * 2.3)
            norm_amp = max(0.05, min(0.85, abs(base)))
            return AudioMetrics(
                rms=norm_amp * 8000.0,
                normalized_amplitude=norm_amp,
                voice_detected=True,
                dominant_frequency_hz=220.0 + 100.0 * math.sin(elapsed_time * 3.0),
                tts_playback_active=False,
                is_simulated=True,
                timestamp=time.time(),
            )
        elif visual_state == AuroraVisualState.SPEAKING:
            # Modulación rítmica de habla sintética de Jessyca:
            # Cadencia de frase natural (~2.4s de locución con micro-pausa de ~0.35s)
            phrase_cycle = elapsed_time % 2.75
            is_in_phrase = phrase_cycle < 2.40

            if is_in_phrase:
                # Cadencia de sílabas a ~4.25 Hz (frecuencia silábica universal del habla)
                syl_freq = 4.25
                syllable_phase = (elapsed_time * syl_freq) % 1.0
                # Envolvente de sílaba: ataque rápido (primer 22%), sostenimiento y decaimiento
                if syllable_phase < 0.22:
                    env = syllable_phase / 0.22
                else:
                    env = max(0.18, 1.0 - (syllable_phase - 0.22) * 1.05)

                # Micro-inflexiones armónicas (formantes vocales)
                harmonics = 0.14 * math.sin(elapsed_time * 22.0) + 0.08 * math.sin(elapsed_time * 36.0)
                norm_amp = max(0.15, min(0.96, env * 0.72 + harmonics + 0.12))
                dom_freq = 215.0 + 35.0 * math.sin(elapsed_time * 4.0)
            else:
                # Pausa natural entre frases (respiración / puntuación)
                norm_amp = 0.08 + 0.03 * math.sin(elapsed_time * 6.0)
                dom_freq = 185.0

            return AudioMetrics(
                rms=norm_amp * 12000.0,
                normalized_amplitude=norm_amp,
                voice_detected=False,
                dominant_frequency_hz=dom_freq,
                tts_playback_active=True,
                is_simulated=True,
                timestamp=time.time(),
            )
        elif visual_state == AuroraVisualState.EXECUTING:
            amp = max(0.40, min(0.48, 0.44 + 0.02 * math.sin(elapsed_time * 2.0)))
            return AudioMetrics(
                rms=amp * 6000.0,
                normalized_amplitude=amp,
                voice_detected=False,
                dominant_frequency_hz=120.0,
                tts_playback_active=False,
                is_simulated=True,
                timestamp=time.time(),
            )
        elif visual_state == AuroraVisualState.THINKING:
            # Pulso cognitivo de baja intensidad con modulación de cálculo
            pulse = 0.08 + 0.05 * abs(math.sin(elapsed_time * 3.5) * math.cos(elapsed_time * 7.0))
            return AudioMetrics(
                rms=pulse * 2500.0,
                normalized_amplitude=pulse,
                voice_detected=False,
                dominant_frequency_hz=180.0 + 30.0 * math.sin(elapsed_time * 4.0),
                tts_playback_active=False,
                is_simulated=True,
                timestamp=time.time(),
            )
        else:
            # Silencio ambiental en reposo o verificación
            noise = 0.02 + 0.015 * math.sin(elapsed_time * 1.5)
            return AudioMetrics(
                rms=noise * 1000.0,
                normalized_amplitude=noise,
                voice_detected=False,
                dominant_frequency_hz=60.0,
                tts_playback_active=False,
                is_simulated=True,
                timestamp=time.time(),
            )
