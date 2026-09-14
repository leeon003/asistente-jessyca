"""Modelo de contexto de estado para una sesión activa en JESSYCA 4.0."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.state.states import SessionState


@dataclass
class StateContext:
    """Contenedor de estado y metadatos mínimos para el ciclo de vida conversacional.

    Atributos:
        current_state: Estado actual de la máquina de estados.
        previous_state: Estado inmediatamente anterior (o None si es el estado inicial).
        session_id: Identificador único universal de la sesión.
        conversation_active: Indicador de si la ventana conversacional continua está activa.
        follow_up_deadline: Timestamp UTC hasta el cual se espera interacción de seguimiento.
        last_activity: Timestamp UTC de la última interacción registrada.
        utterance: Última transcripción de texto recibida en la sesión.
        intent: Última intención clasificada.
        action: Última acción o tool propuesta o ejecutada.
        verification_result: Resultado de la última verificación realizada.
    """

    current_state: SessionState = SessionState.IDLE
    previous_state: SessionState | None = None
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_active: bool = False
    follow_up_deadline: datetime | None = None
    last_activity: datetime = field(default_factory=lambda: datetime.now(UTC))
    utterance: str | None = None
    intent: str | None = None
    action: str | None = None
    verification_result: Any | None = None

    def reset(self, new_session_id: str | None = None) -> None:
        """Restablece el contexto a valores limpios iniciales."""
        self.current_state = SessionState.IDLE
        self.previous_state = None
        self.session_id = new_session_id or str(uuid.uuid4())
        self.conversation_active = False
        self.follow_up_deadline = None
        self.last_activity = datetime.now(UTC)
        self.utterance = None
        self.intent = None
        self.action = None
        self.verification_result = None
