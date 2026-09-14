"""Excepciones especializadas para el subsistema State Machine de JESSYCA 4.0."""

from __future__ import annotations


class StateMachineError(Exception):
    """Excepción base para todos los errores de la máquina de estados."""


class InvalidStateTransitionError(StateMachineError):
    """Lanzada cuando se intenta una transición no permitida entre dos estados."""

    def __init__(self, from_state: str, to_state: str, message: str | None = None) -> None:
        self.from_state = from_state
        self.to_state = to_state
        msg = (
            message
            if message is not None
            else f"Transición de estado no válida rechazada: '{from_state}' → '{to_state}'."
        )
        super().__init__(msg)


class UnknownStateError(StateMachineError):
    """Lanzada cuando se recibe o referencia un estado desconocido o no registrado."""


class InvalidContextError(StateMachineError):
    """Lanzada cuando los datos del contexto de estado son inconsistentes o inválidos."""
