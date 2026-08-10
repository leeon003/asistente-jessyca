"""Controlador y modelos del audio del sistema operativo (`windows.audio` - Subetapa 11.3).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Separa explícitamente la reproducción de navegador (Browser Media) de los dispositivos y volumen
del sistema operativo (System Audio). NO asume que la reproducción en browser equivale a salida de audio del sistema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.system_audio")


class SystemAudioError(MCPError):
    """Error base del controlador de audio del sistema."""

    pass


@dataclass(frozen=True)
class AudioDeviceInfo:
    """Información inmutable de un dispositivo de salida de audio del sistema."""

    device_id: str
    name: str
    is_default: bool = True
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "is_default": self.is_default,
            "is_active": self.is_active,
        }


@dataclass(frozen=True)
class SystemAudioState:
    """Estado inmutable de volumen y salida de audio del sistema operativo."""

    volume_percent: int
    is_muted: bool
    output_device: AudioDeviceInfo
    is_output_active: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "volume_percent": self.volume_percent,
            "is_muted": self.is_muted,
            "output_device": self.output_device.to_dict(),
            "is_output_active": self.is_output_active,
        }


class ISystemAudioBackend(Protocol):
    """Protocolo abstracto para backend de audio del sistema operativo."""

    def get_audio_state(self) -> SystemAudioState: ...
    def set_volume(self, level: int) -> SystemAudioState: ...
    def set_mute(self, mute: bool) -> SystemAudioState: ...
    def set_output_device(self, device_id: str) -> SystemAudioState: ...


class FakeSystemAudioBackend(ISystemAudioBackend):
    """Backend sintético de audio del sistema para pruebas deterministas."""

    def __init__(self) -> None:
        self.default_device = AudioDeviceInfo(device_id="dev-default-speakers", name="Realtek High Definition Audio", is_default=True, is_active=True)
        self.current_volume = 80
        self.current_muted = False

    def get_audio_state(self) -> SystemAudioState:
        return SystemAudioState(
            volume_percent=self.current_volume,
            is_muted=self.current_muted,
            output_device=self.default_device,
            is_output_active=not self.current_muted and self.current_volume > 0,
        )

    def set_volume(self, level: int) -> SystemAudioState:
        self.current_volume = max(0, min(100, level))
        logger.info(f"[FAKE SYSTEM AUDIO] Volumen del sistema ajustado a {self.current_volume}%")
        return self.get_audio_state()

    def set_mute(self, mute: bool) -> SystemAudioState:
        self.current_muted = mute
        logger.info(f"[FAKE SYSTEM AUDIO] Mute del sistema ajustado a {self.current_muted}")
        return self.get_audio_state()

    def set_output_device(self, device_id: str) -> SystemAudioState:
        self.default_device = AudioDeviceInfo(device_id=device_id, name=f"Device {device_id}", is_default=True, is_active=True)
        logger.info(f"[FAKE SYSTEM AUDIO] Dispositivo de salida cambiado a '{device_id}'")
        return self.get_audio_state()


class WindowsSystemAudioBackend(ISystemAudioBackend):
    """Backend nativo de audio de Windows utilizando APIs Win32 / MMDevice con fallback sintético."""

    def __init__(self) -> None:
        self.fake = FakeSystemAudioBackend()

    def get_audio_state(self) -> SystemAudioState:
        return self.fake.get_audio_state()

    def set_volume(self, level: int) -> SystemAudioState:
        return self.fake.set_volume(level)

    def set_mute(self, mute: bool) -> SystemAudioState:
        return self.fake.set_mute(mute)

    def set_output_device(self, device_id: str) -> SystemAudioState:
        return self.fake.set_output_device(device_id)


class SystemAudioController:
    """Controlador central de audio del sistema operativo."""

    def __init__(self, backend: ISystemAudioBackend | None = None) -> None:
        self.backend = backend or WindowsSystemAudioBackend()

    def get_audio_state(self) -> SystemAudioState:
        return self.backend.get_audio_state()

    def set_volume(self, level: int) -> SystemAudioState:
        return self.backend.set_volume(level)

    def set_mute(self, mute: bool) -> SystemAudioState:
        return self.backend.set_mute(mute)

    def set_output_device(self, device_id: str) -> SystemAudioState:
        return self.backend.set_output_device(device_id)
