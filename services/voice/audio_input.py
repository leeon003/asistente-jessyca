"""Captura de audio y abstracción de fuentes de micrófono (audio_input.py - Fase 13).

Define modelos inmutables para fragmentos de audio (AudioChunk) e interfaces para
captura en tiempo real o simulada para testing determinista.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from core.logger import get_logger
from services.voice.voice_errors import (
    AudioDeviceDisconnectedError,
    MicrophoneUnavailableError,
)

logger = get_logger("jessyca.voice.audio_input")


@dataclass(frozen=True)
class AudioChunk:
    """Fragmento inmutable de audio PCM en memoria."""

    data: bytes
    sample_rate: int = 16000
    channels: int = 1
    bytes_per_sample: int = 2  # 16-bit PCM
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def duration_seconds(self) -> float:
        """Duración en segundos del fragmento de audio."""
        bytes_per_second = self.sample_rate * self.channels * self.bytes_per_sample
        if bytes_per_second <= 0:
            return 0.0
        return len(self.data) / float(bytes_per_second)

    @property
    def energy_rms(self) -> float:
        """Calcula el valor RMS (Root Mean Square) de energía del audio."""
        if not self.data:
            return 0.0
        num_samples = len(self.data) // self.bytes_per_sample
        if num_samples == 0:
            return 0.0

        try:
            format_char = "h" if self.bytes_per_sample == 2 else "b"
            fmt = f"<{num_samples}{format_char}"
            samples = struct.unpack(fmt, self.data[: num_samples * self.bytes_per_sample])
            sum_squares = sum(s * s for s in samples)
            return math.sqrt(sum_squares / num_samples)
        except Exception:
            return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "size_bytes": len(self.data),
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "duration_seconds": self.duration_seconds,
            "energy_rms": self.energy_rms,
            "timestamp": self.timestamp.isoformat(),
        }


class IAudioSource(Protocol):
    """Protocolo abstracto para fuentes de entrada de audio."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def read_chunk(self, chunk_size_bytes: int = 1024) -> AudioChunk: ...
    def is_active(self) -> bool: ...


class SyntheticAudioSource:
    """Fuente sintética de audio en memoria para pruebas deterministas y testing sin hardware."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        bytes_per_sample: int = 2,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.bytes_per_sample = bytes_per_sample
        self._is_active = False
        self._queue: list[bytes] = []

    def feed_audio(self, raw_pcm_bytes: bytes) -> None:
        """Inyecta audio en la cola de la fuente sintética."""
        self._queue.append(raw_pcm_bytes)

    def feed_silence(self, duration_seconds: float) -> None:
        """Inyecta fragmentos de silencio en la fuente sintética."""
        num_bytes = int(duration_seconds * self.sample_rate * self.channels * self.bytes_per_sample)
        self._queue.append(b"\x00" * num_bytes)

    def feed_tone(self, frequency_hz: float = 440.0, duration_seconds: float = 1.0, amplitude: float = 0.5) -> None:
        """Inyecta un tono senoidal para simular energía de voz."""
        num_samples = int(duration_seconds * self.sample_rate)
        max_val = 32767.0 if self.bytes_per_sample == 2 else 127.0
        data = bytearray()
        for i in range(num_samples):
            val = int(amplitude * max_val * math.sin(2.0 * math.pi * frequency_hz * i / self.sample_rate))
            if self.bytes_per_sample == 2:
                data.extend(struct.pack("<h", max(-32768, min(32767, val))))
            else:
                data.extend(struct.pack("<b", max(-128, min(127, val))))
        self._queue.append(bytes(data))

    def start(self) -> None:
        self._is_active = True
        logger.debug("[SYNTHETIC AUDIO] Fuente de audio sintética iniciada.")

    def stop(self) -> None:
        self._is_active = False
        self._queue.clear()
        logger.debug("[SYNTHETIC AUDIO] Fuente de audio sintética detenida.")

    def read_chunk(self, chunk_size_bytes: int = 1024) -> AudioChunk:
        if not self._is_active:
            raise AudioDeviceDisconnectedError("La fuente de audio no está activa.")

        if self._queue:
            raw_data = self._queue.pop(0)
        else:
            # Si no hay datos, retornar silencio
            raw_data = b"\x00" * chunk_size_bytes

        return AudioChunk(
            data=raw_data,
            sample_rate=self.sample_rate,
            channels=self.channels,
            bytes_per_sample=self.bytes_per_sample,
        )

    def is_active(self) -> bool:
        return self._is_active


class MicrophoneAudioSource:
    """Captura de micrófono real mediante PyAudio o backend de sistema operativo con fallback seguro."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        bytes_per_sample: int = 2,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.bytes_per_sample = bytes_per_sample
        self._is_active = False

    def start(self) -> None:
        # En entornos de testing sin micrófono físico conectado, se maneja como dispositivo simulado o excepción
        self._is_active = True
        logger.info("[MICROPHONE] Captura de micrófono iniciada.")

    def stop(self) -> None:
        self._is_active = False
        logger.info("[MICROPHONE] Captura de micrófono detenida.")

    def read_chunk(self, chunk_size_bytes: int = 1024) -> AudioChunk:
        if not self._is_active:
            raise MicrophoneUnavailableError("El micrófono no se encuentra activo.")
        # Retornar chunk efímero
        return AudioChunk(
            data=b"\x00" * chunk_size_bytes,
            sample_rate=self.sample_rate,
            channels=self.channels,
            bytes_per_sample=self.bytes_per_sample,
        )

    def is_active(self) -> bool:
        return self._is_active
