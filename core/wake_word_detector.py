"""Subsistema de Detección de Palabra de Activación Local (WakeWordDetector - Etapa 13.2).

GARANTÍAS RIGUROSAS DE SEGURIDAD Y PRIVACIDAD EN ETAPA 13.2:
1. DESHABILITADO POR DEFECTO: WAKE_WORD_ENABLED=False. CERO escucha sin activación explícita.
2. PROCESAMIENTO 100% LOCAL: CERO envío de paquetes o streams de audio a servidores/servicios externos.
3. AUDIO EFÍMERO Y EN MEMORIA RAM: CERO escritura o archivo de audio guardado en disco sin consentimiento.
4. BUFFER ACOTADO (Bounded Buffer): Límite estricto de bytes en RAM ajustado por AUDIO_BUFFER_MAX_SECONDS.
5. CANCELACIÓN LIMPIA: Cancelación inmediata con sobreescritura de ceros en memoria RAM.
6. ESTADO VISIBLE: Transiciones de estado visibles y seguras mediante hilos:
   INACTIVE -> LISTENING -> TRIGGERED -> PROCESSING -> INACTIVE / ERROR.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.autonomy_policy import (
    AutonomousTaskRequest,
    AutonomyPolicy,
)
from core.event_bus import get_event_bus
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.wake_word")


class WakeWordState(StrEnum):
    """Estados formales y visibles del detector de palabra de activación."""

    INACTIVE = "INACTIVE"
    LISTENING = "LISTENING"
    TRIGGERED = "TRIGGERED"
    PROCESSING = "PROCESSING"
    ERROR = "ERROR"


class WakeWordSecurityError(MCPError):
    """Error base para violaciones de seguridad o privacidad en WakeWordDetector."""

    pass


class WakeWordDisabledError(WakeWordSecurityError):
    """Error emitido al intentar iniciar el detector estando deshabilitado por configuración."""

    pass


class WakeWordDetector:
    """Detector Local de Palabra de Activación (WakeWordDetector - Etapa 13.2).

    Garantiza privacidad total en memoria efímera con estados visibles y cero persistencia.
    """

    def __init__(
        self,
        autonomy_policy: AutonomyPolicy | None = None,
        bytes_per_sample: int = 2,  # 16-bit PCM por defecto
    ) -> None:
        from config.settings import AppSettings
        settings = AppSettings()


        self.enabled = settings.WAKE_WORD_ENABLED
        self.keyword = settings.WAKE_WORD_KEYWORD.lower()
        self.max_seconds = settings.AUDIO_BUFFER_MAX_SECONDS
        self.sample_rate = settings.AUDIO_SAMPLE_RATE
        self.bytes_per_sample = bytes_per_sample

        # Capacidad máxima del buffer acotado en bytes
        self.max_capacity_bytes = int(self.max_seconds * self.sample_rate * self.bytes_per_sample)

        self._state = WakeWordState.INACTIVE
        self._audio_buffer = bytearray()
        self._lock = threading.RLock()

        self.autonomy_policy = autonomy_policy or AutonomyPolicy()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    @property
    def state(self) -> WakeWordState:
        """Estado visible thread-safe actual del detector."""
        with self._lock:
            return self._state

    @property
    def buffer_size_bytes(self) -> int:
        """Tamaño actual en bytes del buffer de audio efímero en memoria."""
        with self._lock:
            return len(self._audio_buffer)

    @property
    def buffer_duration_seconds(self) -> float:
        """Duración aproximada en segundos del audio contenido en el buffer efímero."""
        with self._lock:
            bytes_per_sec = self.sample_rate * self.bytes_per_sample
            if bytes_per_sec <= 0:
                return 0.0
            return len(self._audio_buffer) / bytes_per_sec

    def start_listening(self) -> bool:
        """Inicia el modo de escucha local.

        Si WAKE_WORD_ENABLED=False, se lanza WakeWordDisabledError.
        """
        with self._lock:
            if not self.enabled:
                raise WakeWordDisabledError(
                    "[SECURITY] WakeWordDetector se encuentra deshabilitado por configuración (WAKE_WORD_ENABLED=False). CERO escucha sin consentimiento."
                )

            if self._state == WakeWordState.ERROR:
                raise WakeWordSecurityError(
                    "No se puede iniciar el detector desde un estado de ERROR sin antes ejecutar reset_error()."
                )

            self._clear_buffer_in_memory()
            self._set_state(WakeWordState.LISTENING)
            logger.info(f"[WAKE_WORD] Escucha local activada. Palabra clave: '{self.keyword}'. Buffer máx: {self.max_seconds}s.")
            return True

    def stop_listening(self) -> None:
        """Detiene la escucha local y destruye de inmediato el buffer de audio en memoria RAM."""
        with self._lock:
            self._clear_buffer_in_memory()
            if self._state != WakeWordState.ERROR:
                self._set_state(WakeWordState.INACTIVE)
            logger.info("[WAKE_WORD] Escucha local detenida. Buffer efímero destruido.")

    def cancel(self) -> None:
        """Soporte de cancelación limpia inmediata con destrucción segura de memoria."""
        with self._lock:
            self._clear_buffer_in_memory()
            self._set_state(WakeWordState.INACTIVE)
            logger.info("[WAKE_WORD] Detector cancelado. Memoria RAM purgada a 0x00.")

    def reset_error(self) -> None:
        """Recupera el detector desde un estado de ERROR cambiándolo a INACTIVE."""
        with self._lock:
            self._clear_buffer_in_memory()
            self._set_state(WakeWordState.INACTIVE)
            logger.info("[WAKE_WORD] Estado de ERROR restablecido a INACTIVE.")

    def process_audio_chunk(self, chunk: bytes) -> bool:
        """Recibe y procesa un fragmento de audio binario efímero en la memoria RAM.

        Mantiene estricto el límite del buffer acotado (Bounded Buffer) descartando el audio más antiguo.
        NO PERSISTE AUDIO EN DISCO NI RED.
        """
        with self._lock:
            if not self.enabled:
                return False

            if self._state != WakeWordState.LISTENING:
                return False

            if not chunk:
                return False

            # Agregar el chunk al buffer efímero en RAM
            self._audio_buffer.extend(chunk)

            # Acotar el buffer al límite máximo configurado descartando muestras antiguas
            if len(self._audio_buffer) > self.max_capacity_bytes:
                overflow_bytes = len(self._audio_buffer) - self.max_capacity_bytes
                del self._audio_buffer[:overflow_bytes]

            return True

    def trigger_keyword(
        self,
        phrase: str,
        task_id: str | None = None,
        tool_name: str = "system.read",
        operation: str = "get_status",
        parameters: dict[str, Any] | None = None,
        action_callback: Callable[[AutonomousTaskRequest], Any] | None = None,
    ) -> bool:
        """Simula o ejecuta la detección local de la palabra clave de activación.

        Realiza la transición de estados:
        LISTENING -> TRIGGERED -> PROCESSING -> LISTENING / INACTIVE.
        Ruta por AutonomyPolicy obligatoria.
        """
        with self._lock:
            if not self.enabled:
                raise WakeWordDisabledError("La palabra de activación está deshabilitada.")

            if self._state != WakeWordState.LISTENING:
                return False

            phrase_clean = phrase.lower().strip()
            if self.keyword not in phrase_clean:
                return False

            # 1. Transición a TRIGGERED
            self._set_state(WakeWordState.TRIGGERED)
            logger.info(f"[WAKE_WORD] Palabra de activación detectada: '{phrase_clean}'. Transición a TRIGGERED.")

            # 2. Transición a PROCESSING
            self._set_state(WakeWordState.PROCESSING)

            tid = task_id or f"wakeword-{int(time.time())}"
            req = AutonomousTaskRequest(
                task_id=tid,
                tool_name=tool_name,
                operation=operation,
                is_wake_word=True,
                parameters=parameters or {},
            )

            try:
                # Pasar obligatoriamente por AutonomyPolicy
                self.autonomy_policy.enforce_task_execution(req)

                if action_callback is not None:
                    action_callback(req)

                self._log_wake_word_audit(phrase_clean, success=True)
                self._clear_buffer_in_memory()
                self._set_state(WakeWordState.LISTENING)
                return True

            except Exception as e:
                logger.error(f"[WAKE_WORD] Error o denegación al procesar la activación por Wake Word: {e}")
                self._log_wake_word_audit(phrase_clean, success=False, error=str(e))
                self._clear_buffer_in_memory()
                self._set_state(WakeWordState.ERROR)
                return False

    def _clear_buffer_in_memory(self) -> None:
        """Sobreescribe los bytes del buffer en memoria con ceros (0x00) antes de vaciarlo."""
        if self._audio_buffer:
            for i in range(len(self._audio_buffer)):
                self._audio_buffer[i] = 0
            self._audio_buffer.clear()

    def _set_state(self, new_state: WakeWordState) -> None:
        old_state = self._state
        self._state = new_state
        self.event_bus.publish(
            "wake_word:state_changed",
            {"old_state": str(old_state), "new_state": str(new_state)},
        )

    def _log_wake_word_audit(self, phrase: str, success: bool, error: str = "") -> None:
        """Registra el evento de auditoría sanitizado sin guardar jamás fragmentos o datos de audio."""
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.POLICY_EVALUATED if success else AuditEventType.EXECUTION_DENIED,
                request_id=f"wakeword-{int(time.time())}",
                tool_name="wake_word.detector",
                operation="keyword_match",
                duration_ms=0.0,
                reason=f"Wake word trigger {'successful' if success else 'failed/denied'}. Error: {error}",
                metadata={
                    "keyword_detected": True,
                    "success": success,
                    "buffer_bytes_purged": True,
                },
            )
        )
