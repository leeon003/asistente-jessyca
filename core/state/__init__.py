"""Módulo de máquina de estados para JESSYCA 4.0.

Gestiona el ciclo de vida de la sesión, validación de transiciones canónicas,
control de ventanas conversacionales continuas sin bloqueos y callbacks de estado.
"""

from __future__ import annotations

from core.state.context import StateContext
from core.state.exceptions import (
    InvalidContextError,
    InvalidStateTransitionError,
    StateMachineError,
    UnknownStateError,
)
from core.state.machine import VALID_TRANSITIONS, StateMachine
from core.state.states import SessionState

__all__ = [
    "InvalidContextError",
    "InvalidStateTransitionError",
    "SessionState",
    "StateContext",
    "StateMachine",
    "StateMachineError",
    "UnknownStateError",
    "VALID_TRANSITIONS",
]
