"""Gestor de Turnos Conversacionales y Coordinación de Barge-In (turn_manager.py - Fase 52).

Gestiona la toma de turnos entre el usuario y JESSYCA:
USER_TURN <-> ASSISTANT_TURN, con soporte para INTERRUPTED, CANCELLED y COMPLETED.

Garantiza:
1. Corte inmediato y seguro de la reproducción de voz (Barge-In).
2. Discriminación de frases de pura interrupción ("Espera", "Para", "No", "Déjame hablar") frente a nuevos comandos.
3. Prevención de condiciones de carrera mediante sincronización atómica con RLock.
4. Preservación de la sesión continua tras ser interrumpida.
"""

from __future__ import annotations

import re
import threading
from enum import StrEnum
from typing import Any

from core.cancellation import CancellationToken
from core.logger import get_logger
from services.voice.barge_in_controller import BargeInController

logger = get_logger("jessyca.voice.turn_manager")


class VoiceTurnState(StrEnum):
    """Estados formales del turno conversacional en el subsistema de voz."""

    USER_TURN = "USER_TURN"
    ASSISTANT_TURN = "ASSISTANT_TURN"
    INTERRUPTED = "INTERRUPTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


PURE_INTERRUPTION_PHRASES: frozenset[str] = frozenset({
    "espera",
    "espera un momento",
    "para",
    "para ya",
    "no",
    "no espera",
    "déjame hablar",
    "dejame hablar",
    "detente",
    "deténte",
    "cállate",
    "callate",
    "silencio",
    "un momento",
    "aguanta",
    "pausa",
    "alto",
})


class TurnManager:
    """Coordinador de toma de turnos e interrupciones en tiempo real (Fase 52)."""

    def __init__(self, barge_in_controller: BargeInController | None = None) -> None:
        self.barge_in = barge_in_controller or BargeInController()
        self._state = VoiceTurnState.USER_TURN
        self._lock = threading.RLock()
        self._turn_id = 0
        self._interruption_history: list[dict[str, Any]] = []

    @property
    def current_state(self) -> VoiceTurnState:
        with self._lock:
            return self._state

    @property
    def turn_id(self) -> int:
        with self._lock:
            return self._turn_id

    def start_user_turn(self) -> None:
        """Inicia formalmente el turno del usuario (captura y procesamiento)."""
        with self._lock:
            self._turn_id += 1
            self._state = VoiceTurnState.USER_TURN
            logger.info(f"[TURN MANAGER] Turno {self._turn_id} iniciado por el USUARIO.")

    def start_assistant_turn(self, cancellation_token: CancellationToken | None = None) -> None:
        """Inicia formalmente el turno del asistente (síntesis y reproducción de voz)."""
        with self._lock:
            self._state = VoiceTurnState.ASSISTANT_TURN
            self.barge_in.notify_tts_started(cancellation_token)
            logger.info(f"[TURN MANAGER] Turno {self._turn_id} iniciado por JESSYCA (Hablando).")

    def handle_barge_in(self, reason: str = "User speech detected") -> bool:
        """Ejecuta una interrupción (Barge-in) sobre el turno del asistente si está hablando."""
        with self._lock:
            if self._state != VoiceTurnState.ASSISTANT_TURN and not self.barge_in.is_tts_active:
                return False

            logger.info(f"[TURN MANAGER] Interrupción detectada en turno {self._turn_id}: '{reason}'")
            self._state = VoiceTurnState.INTERRUPTED
            interrupted = self.barge_in.trigger_barge_in(reason=reason)

            self._interruption_history.append({
                "turn_id": self._turn_id,
                "reason": reason,
                "success": interrupted,
            })
            return True

    def is_pure_interruption(self, text: str) -> bool:
        """Determina si una frase es exclusivamente para detener la respuesta sin ordenar una acción."""
        clean = re.sub(r"[^\w\s]", "", text.strip().lower())
        # Si coincide exactamente con alguna frase de interrupción o es una sola palabra como 'no', 'para', 'espera'
        if clean in PURE_INTERRUPTION_PHRASES:
            return True
        tokens = clean.split()
        if len(tokens) <= 3 and all(t in PURE_INTERRUPTION_PHRASES or t in ("por", "favor", "jessica", "jessyca", "oye") for t in tokens):
            return True
        return False

    def complete_turn(self) -> None:
        """Concluye exitosamente el turno conversacional."""
        with self._lock:
            self._state = VoiceTurnState.COMPLETED
            self.barge_in.notify_tts_finished()
            logger.info(f"[TURN MANAGER] Turno {self._turn_id} COMPLETADO limpiamente.")

    def cancel_turn(self, reason: str = "Turn cancelled") -> None:
        """Cancela el turno conversacional activo."""
        with self._lock:
            self._state = VoiceTurnState.CANCELLED
            self.barge_in.trigger_barge_in(reason=reason)
            logger.info(f"[TURN MANAGER] Turno {self._turn_id} CANCELADO: {reason}")

    def reset(self) -> None:
        """Restablece el gestor de turnos a su estado inicial."""
        with self._lock:
            self._state = VoiceTurnState.USER_TURN
            self._turn_id = 0
            self._interruption_history.clear()
            self.barge_in.reset()
