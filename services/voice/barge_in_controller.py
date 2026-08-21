"""Controlador de Interrupciones y Barge-in (barge_in_controller.py - Fase 30).

Permite al usuario interrumpir a JESSYCA mientras está hablando (TTS activo)
o cancelando inmediatamente la ejecución de tareas ante comandos de voz o actividad del micrófono.
"""

from __future__ import annotations

import threading

from core.cancellation import CancellationToken
from core.logger import get_logger
from services.voice.tts_service import ITTSService

logger = get_logger("jessyca.voice.barge_in")


class BargeInController:
    """Controlador central de interrupciones y corte de habla (Barge-in)."""

    def __init__(self, tts_service: ITTSService | None = None) -> None:
        self.tts_service = tts_service
        self._lock = threading.RLock()
        self._is_tts_active = False
        self._interrupted_count = 0
        self._current_cancellation_token: CancellationToken | None = None

    def notify_tts_started(self, cancellation_token: CancellationToken | None = None) -> None:
        """Notifica que JESSYCA ha comenzado a hablar."""
        with self._lock:
            self._is_tts_active = True
            self._current_cancellation_token = cancellation_token

    def notify_tts_finished(self) -> None:
        """Notifica que JESSYCA ha concluido la reproducción de voz."""
        with self._lock:
            self._is_tts_active = False
            self._current_cancellation_token = None

    def trigger_barge_in(self, reason: str = "User speech detected") -> bool:
        """Ejecuta una interrupción inmediata de la salida de audio si JESSYCA está hablando.

        Retorna True si se detuvo una reproducción activa, o False si no había voz activa.
        """
        with self._lock:
            if not self._is_tts_active:
                return False

            logger.info(f"[BARGE-IN] Interrumpiendo reproducción de voz: '{reason}'")
            self._is_tts_active = False
            self._interrupted_count += 1

            if self._current_cancellation_token:
                self._current_cancellation_token.cancel()
                self._current_cancellation_token = None

            if self.tts_service and hasattr(self.tts_service, "stop"):
                try:
                    self.tts_service.stop()
                except Exception as exc:
                    logger.warning(f"[BARGE-IN] Error al invocar tts_service.stop(): {exc}")

            return True

    @property
    def is_tts_active(self) -> bool:
        with self._lock:
            return self._is_tts_active

    @property
    def interrupted_count(self) -> int:
        with self._lock:
            return self._interrupted_count

    def reset(self) -> None:
        """Restablece el estado del controlador."""
        with self._lock:
            self._is_tts_active = False
            self._interrupted_count = 0
            self._current_cancellation_token = None
