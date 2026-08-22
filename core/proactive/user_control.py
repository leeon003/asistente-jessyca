"""Gestor de Control de Usuario y Preferencias de Proactividad (user_control.py - Fase 44).

Permite al usuario gobernar completamente el comportamiento proactivo de JESSYCA:
- Habilitar (enable)
- Deshabilitar (disable)
- Silenciar temporalmente / Pausar (mute / unmute)
- Configurar sensibilidad, umbrales y fuentes permitidas (configure)

PRINCIPIO: SOBERANÍA ABSOLUTA DEL USUARIO.
"""

from __future__ import annotations

import copy
import threading
import time
from typing import Any

from core.logger import get_logger
from core.proactive.proactive_models import EventSourceType, UserControlSettings

logger = get_logger("jessyca.proactive.user_control")


class ProactiveUserControl:
    """Administrador de estado, silencio y configuración del usuario para asistencia proactiva."""

    def __init__(self, initial_settings: UserControlSettings | None = None) -> None:
        self._lock = threading.RLock()
        self._settings = initial_settings or UserControlSettings()

    def enable(self) -> None:
        """Habilita la inteligencia proactiva."""
        with self._lock:
            self._settings.enabled = True
            logger.info("[USER CONTROL] Inteligencia proactiva habilitada por el usuario.")

    def disable(self) -> None:
        """Deshabilita por completo la inteligencia proactiva."""
        with self._lock:
            self._settings.enabled = False
            logger.info("[USER CONTROL] Inteligencia proactiva deshabilitada por el usuario.")

    def is_enabled(self) -> bool:
        """Indica si el motor proactivo está habilitado."""
        with self._lock:
            return self._settings.enabled

    def mute(self, duration_seconds: float) -> None:
        """Silencia las notificaciones y sugerencias proactivas durante un tiempo específico."""
        with self._lock:
            self._settings.muted_until = time.time() + max(0.0, duration_seconds)
            logger.info(f"[USER CONTROL] Inteligencia proactiva silenciada por {duration_seconds} segundos.")

    def unmute(self) -> None:
        """Elimina el silencio activo de forma inmediata."""
        with self._lock:
            self._settings.muted_until = None
            logger.info("[USER CONTROL] Silencio proactivo cancelado. Notificaciones reanudadas.")

    def is_muted(self) -> bool:
        """Comprueba si el asistente se encuentra actualmente silenciado."""
        with self._lock:
            return self._settings.is_muted()

    def is_active(self) -> bool:
        """Indica si el motor proactivo puede operar activamente (habilitado, no silenciado, no en horario silencioso)."""
        with self._lock:
            return self._settings.is_active()

    def configure(self, settings_or_dict: UserControlSettings | dict[str, Any]) -> UserControlSettings:
        """Actualiza la configuración y preferencias de asistencia proactiva."""
        with self._lock:
            if isinstance(settings_or_dict, UserControlSettings):
                self._settings = copy.deepcopy(settings_or_dict)
            elif isinstance(settings_or_dict, dict):
                for k, v in settings_or_dict.items():
                    if hasattr(self._settings, k):
                        if k == "allowed_sources" and isinstance(v, (list, set)):
                            v = {EventSourceType(s) if not isinstance(s, EventSourceType) else s for s in v}
                        setattr(self._settings, k, v)

            logger.info("[USER CONTROL] Configuración de inteligencia proactiva actualizada exitosamente.")
            return copy.deepcopy(self._settings)

    def get_settings(self) -> UserControlSettings:
        """Obtiene una copia inmutable de la configuración actual."""
        with self._lock:
            return copy.deepcopy(self._settings)

    def reset(self) -> None:
        """Restablece los ajustes por defecto."""
        with self._lock:
            self._settings = UserControlSettings()
