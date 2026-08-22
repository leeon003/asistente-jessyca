"""Gestor de Sesiones de Voz Continua (continuous_voice_session.py - Fases 51 y 52).

Convierte el flujo de voz en una conversación continua de múltiples turnos:
WAKE -> CONVERSATION_ACTIVE -> LISTEN -> PROCESS -> SPEAK -> WAITING_FOR_FOLLOWUP -> ... -> TIMEOUT -> IDLE.

Funcionalidades:
1. Estados formales de sesión de voz (VoiceSessionMode).
2. Ventana de seguimiento (Follow-up) configurable sin exigir wake word.
3. Expiración determinista por inactividad (conversation_idle_timeout).
4. Audio buffer circular con pre-roll para evitar truncamientos de VAD.
5. Inmunidad a habla de fondo tras timeout.
6. Integración con TurnManager para soporte de Barge-in y toma de turnos (Fase 52).
"""

from __future__ import annotations

import collections
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.logger import get_logger
from services.voice.turn_manager import TurnManager

logger = get_logger("jessyca.voice.continuous_session")


class VoiceSessionMode(StrEnum):
    """Estados del ciclo de vida de una sesión conversacional por voz."""

    IDLE = "IDLE"
    WAKE_DETECTED = "WAKE_DETECTED"
    CONVERSATION_ACTIVE = "CONVERSATION_ACTIVE"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    WAITING_FOR_FOLLOWUP = "WAITING_FOR_FOLLOWUP"
    ENDING = "ENDING"


class AudioPreRollBuffer:
    """Buffer circular thread-safe para conservar fragmentos de audio previos a la activación de VAD."""

    def __init__(self, max_chunks: int = 10) -> None:
        self.max_chunks = max_chunks
        self._buffer: collections.deque[bytes] = collections.deque(maxlen=max_chunks)
        self._lock = threading.Lock()

    def append(self, chunk_data: bytes) -> None:
        """Agrega un chunk de audio al buffer circular."""
        if chunk_data:
            with self._lock:
                self._buffer.append(chunk_data)

    def get_preroll_bytes(self) -> bytes:
        """Obtiene la concatenación de todos los chunks almacenados en el pre-roll."""
        with self._lock:
            return b"".join(self._buffer)

    def clear(self) -> None:
        """Limpia el buffer circular."""
        with self._lock:
            self._buffer.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)


@dataclass
class ContinuousVoiceSession:
    """Representa una sesión conversacional continua por voz con control de estados, timeouts y turnos."""

    session_id: str = field(default_factory=lambda: f"voice-sess-{uuid.uuid4().hex[:8]}")
    mode: VoiceSessionMode = VoiceSessionMode.IDLE
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    conversation_idle_timeout: float = 10.0
    followup_timeout: float = 8.0
    turns_count: int = 0
    pre_roll_buffer: AudioPreRollBuffer = field(default_factory=AudioPreRollBuffer)
    turn_manager: TurnManager = field(default_factory=TurnManager)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def touch(self) -> None:
        """Actualiza la marca temporal de actividad reciente."""
        with self._lock:
            self.last_activity = time.time()

    def is_active(self) -> bool:
        """Indica si la sesión conversacional está en un estado activo o de seguimiento."""
        with self._lock:
            self.check_timeout()
            return self.mode in (
                VoiceSessionMode.WAKE_DETECTED,
                VoiceSessionMode.CONVERSATION_ACTIVE,
                VoiceSessionMode.LISTENING,
                VoiceSessionMode.PROCESSING,
                VoiceSessionMode.SPEAKING,
                VoiceSessionMode.WAITING_FOR_FOLLOWUP,
            )

    def should_require_wake_word(self) -> bool:
        """Determina si la entrada de voz actual exige la palabra de activación.

        En modo IDLE o tras expirar el timeout: EXIGE wake word.
        En modo CONVERSATION_ACTIVE o WAITING_FOR_FOLLOWUP: NO exige wake word.
        """
        with self._lock:
            self.check_timeout()
            if self.mode in (VoiceSessionMode.CONVERSATION_ACTIVE, VoiceSessionMode.WAITING_FOR_FOLLOWUP):
                return False
            return True

    def on_wake_detected(self) -> None:
        """Señaliza la detección exitosa de la palabra de activación."""
        with self._lock:
            self.touch()
            self.mode = VoiceSessionMode.CONVERSATION_ACTIVE
            self.turns_count += 1
            self.turn_manager.start_user_turn()
            logger.info(f"[VOICE SESSION STARTED] Sesión '{self.session_id}' activada por wake word (Turno {self.turns_count}).")

    def on_listening_started(self) -> None:
        """Señaliza el inicio de la captura de audio por micrófono."""
        with self._lock:
            self.touch()
            if self.mode != VoiceSessionMode.IDLE:
                self.mode = VoiceSessionMode.LISTENING
                self.turn_manager.start_user_turn()

    def on_processing_started(self) -> None:
        """Señaliza el inicio del procesamiento de STT y razonamiento del agente."""
        with self._lock:
            self.touch()
            self.mode = VoiceSessionMode.PROCESSING

    def on_speaking_started(self) -> None:
        """Señaliza el inicio de la reproducción de voz (TTS)."""
        with self._lock:
            self.touch()
            self.mode = VoiceSessionMode.SPEAKING
            self.turn_manager.start_assistant_turn()

    def on_speaking_finished(self) -> None:
        """Señaliza el fin de la respuesta hablada y abre la ventana de seguimiento (Follow-up)."""
        with self._lock:
            self.touch()
            self.mode = VoiceSessionMode.WAITING_FOR_FOLLOWUP
            self.turn_manager.complete_turn()
            logger.info(f"[VOICE FOLLOWUP OPEN] Ventana de seguimiento abierta por {self.conversation_idle_timeout}s.")

    def on_interrupted(self, reason: str = "User speech during TTS") -> None:
        """Señaliza una interrupción exitosa del habla de JESSYCA (Barge-In)."""
        with self._lock:
            self.touch()
            self.mode = VoiceSessionMode.WAITING_FOR_FOLLOWUP
            self.turn_manager.handle_barge_in(reason=reason)
            logger.info(f"[VOICE SESSION INTERRUPTED] Sesión '{self.session_id}' interrumpida: {reason}")

    def on_turn_completed(self) -> None:
        """Señaliza la conclusión de un turno conversacional exitoso."""
        with self._lock:
            self.touch()
            self.turns_count += 1
            self.mode = VoiceSessionMode.WAITING_FOR_FOLLOWUP
            self.turn_manager.complete_turn()

    def check_timeout(self) -> bool:
        """Verifica si la sesión ha expirado por inactividad y regresa a IDLE."""
        with self._lock:
            if self.mode == VoiceSessionMode.IDLE:
                return False

            elapsed = time.time() - self.last_activity
            limit = self.conversation_idle_timeout

            if elapsed > limit:
                logger.info(
                    f"[VOICE SESSION TIMEOUT] Sesión '{self.session_id}' expiró tras {elapsed:.1f}s de silencio. Regresando a IDLE."
                )
                self.mode = VoiceSessionMode.IDLE
                self.pre_roll_buffer.clear()
                self.turn_manager.reset()
                return True
            return False

    def end_session(self) -> None:
        """Finaliza formalmente la sesión de voz continua."""
        with self._lock:
            self.touch()
            self.mode = VoiceSessionMode.IDLE
            self.pre_roll_buffer.clear()
            self.turn_manager.reset()
            logger.info(f"[VOICE SESSION ENDED] Sesión de voz '{self.session_id}' finalizada.")

    def to_dict(self) -> dict[str, Any]:
        """Serializa el estado de la sesión de voz continua."""
        with self._lock:
            return {
                "session_id": self.session_id,
                "mode": self.mode.value,
                "turn_state": self.turn_manager.current_state.value,
                "created_at": self.created_at,
                "last_activity": self.last_activity,
                "conversation_idle_timeout": self.conversation_idle_timeout,
                "followup_timeout": self.followup_timeout,
                "turns_count": self.turns_count,
                "is_active": self.is_active(),
            }
