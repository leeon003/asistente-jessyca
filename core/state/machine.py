"""Máquina de estados explícita, asíncrona y tipada para JESSYCA 4.0."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from core.logger import get_logger
from core.state.context import StateContext
from core.state.exceptions import (
    InvalidStateTransitionError,
    UnknownStateError,
)
from core.state.states import SessionState

logger = get_logger("jessyca.state_machine")

StateCallback = Callable[[StateContext], Any | Coroutine[Any, Any, Any]]

# Tabla de transiciones canónicas permitidas
VALID_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.IDLE: {
        SessionState.WAKEWORD,
    },
    SessionState.WAKEWORD: {
        SessionState.LISTENING,
        SessionState.IDLE,
    },
    SessionState.LISTENING: {
        SessionState.TRANSCRIBING,
        SessionState.IDLE,
    },
    SessionState.TRANSCRIBING: {
        SessionState.ROUTING,
        SessionState.LISTENING,
        SessionState.IDLE,
    },

    SessionState.ROUTING: {
        SessionState.EXECUTING,
        SessionState.CONFIRMING,
        SessionState.CLARIFYING,
        SessionState.RESPONDING,
        SessionState.IDLE,
    },
    SessionState.CONFIRMING: {
        SessionState.EXECUTING,
        SessionState.RESPONDING,
        SessionState.IDLE,
    },
    SessionState.CLARIFYING: {
        SessionState.LISTENING,
        SessionState.RESPONDING,
        SessionState.IDLE,
    },
    SessionState.EXECUTING: {
        SessionState.VERIFYING,
        SessionState.RESPONDING,
        SessionState.IDLE,
    },
    SessionState.VERIFYING: {
        SessionState.RESPONDING,
        SessionState.IDLE,
    },
    SessionState.RESPONDING: {
        SessionState.IDLE,
        SessionState.LISTENING,
    },
}


class StateMachine:
    """Máquina de estados de control del ciclo de vida para JESSYCA 4.0."""

    def __init__(
        self,
        follow_up_window: float = 15.0,
        context: StateContext | None = None,
    ) -> None:
        """Inicializa la máquina de estados.

        Args:
            follow_up_window: Ventana de seguimiento conversacional en segundos (configurable).
            context: Contexto inicial opcional. Si es None, se crea un StateContext nuevo.
        """
        self.follow_up_window = float(follow_up_window)
        self._context = context or StateContext()

        # Callbacks por estado
        self._entry_handlers: dict[SessionState, list[StateCallback]] = {
            state: [] for state in SessionState
        }
        self._exit_handlers: dict[SessionState, list[StateCallback]] = {
            state: [] for state in SessionState
        }

        # Tarea asíncrona de seguimiento de timeout
        self._timer_task: asyncio.Task[None] | None = None

    @property
    def current_state(self) -> SessionState:
        """Estado actual de la sesión."""
        return self._context.current_state

    @property
    def previous_state(self) -> SessionState | None:
        """Estado anterior inmediato."""
        return self._context.previous_state

    @property
    def context(self) -> StateContext:
        """Contexto de sesión activo."""
        return self._context

    @property
    def session_id(self) -> str:
        """Identificador de la sesión activa."""
        return self._context.session_id

    @property
    def conversation_active(self) -> bool:
        """Indica si la conversación continua de seguimiento está activa."""
        return self._context.conversation_active

    def on_enter(self, state: SessionState, handler: StateCallback) -> None:
        """Registra un callback que se ejecutará al ingresar al estado especificado."""
        self._validate_state(state)
        self._entry_handlers[state].append(handler)

    def on_exit(self, state: SessionState, handler: StateCallback) -> None:
        """Registra un callback que se ejecutará al salir del estado especificado."""
        self._validate_state(state)
        self._exit_handlers[state].append(handler)

    def can_transition_to(self, target_state: SessionState | str) -> bool:
        """Verifica si es válida la transición desde el estado actual al estado objetivo."""
        resolved = self._resolve_state(target_state)
        allowed = VALID_TRANSITIONS.get(self._context.current_state, set())
        return resolved in allowed

    def transition_to(self, target_state: SessionState | str) -> None:
        """Ejecuta sincrónicamente una transición de estado si es válida.

        Lanza:
            UnknownStateError: Si el estado no existe en SessionState.
            InvalidStateTransitionError: Si la transición no está permitida.
        """
        resolved = self._resolve_state(target_state)
        current = self._context.current_state

        if not self.can_transition_to(resolved):
            raise InvalidStateTransitionError(current.value, resolved.value)

        # 1. Ejecutar exit handlers del estado actual
        self._invoke_handlers_sync(self._exit_handlers[current])

        # 2. Actualizar contexto
        self._context.previous_state = current
        self._context.current_state = resolved
        self._context.last_activity = datetime.now(UTC)

        # 3. Registrar transición en el formato canónico requerido
        logger.info(f"STATE: {current.value} → {resolved.value} (session_id={self._context.session_id})")

        # 4. Ejecutar entry handlers del nuevo estado
        self._invoke_handlers_sync(self._entry_handlers[resolved])

    async def transition_to_async(self, target_state: SessionState | str) -> None:
        """Ejecuta asíncronamente una transición de estado esperando handlers async."""
        resolved = self._resolve_state(target_state)
        current = self._context.current_state

        if not self.can_transition_to(resolved):
            raise InvalidStateTransitionError(current.value, resolved.value)

        # 1. Ejecutar exit handlers
        await self._invoke_handlers_async(self._exit_handlers[current])

        # 2. Actualizar contexto
        self._context.previous_state = current
        self._context.current_state = resolved
        self._context.last_activity = datetime.now(UTC)

        # 3. Registrar transición
        logger.info(f"STATE: {current.value} → {resolved.value} (session_id={self._context.session_id})")

        # 4. Ejecutar entry handlers
        await self._invoke_handlers_async(self._entry_handlers[resolved])

    def renew_follow_up(self, window_seconds: float | None = None) -> datetime:
        """Renueva la ventana de seguimiento conversacional continuo.

        Args:
            window_seconds: Duración personalizada en segundos; si es None, usa follow_up_window.

        Returns:
            datetime: Nuevo timestamp UTC de deadline.
        """
        duration = float(window_seconds if window_seconds is not None else self.follow_up_window)
        now = datetime.now(UTC)
        deadline = now + timedelta(seconds=duration)

        self._context.follow_up_deadline = deadline
        self._context.conversation_active = True
        self._context.last_activity = now

        logger.debug(
            f"STATE: Conversación renovada [Ventana: {duration}s, Deadline: {deadline.isoformat()}]"
        )
        return deadline

    def is_follow_up_expired(self) -> bool:
        """Comprueba si el deadline de seguimiento conversacional ha expirado."""
        if self._context.follow_up_deadline is None:
            return True
        return datetime.now(UTC) >= self._context.follow_up_deadline

    def handle_follow_up_timeout(self) -> None:
        """Gestiona la expiración de la ventana de seguimiento, retornando a IDLE."""
        if self._context.current_state == SessionState.LISTENING:
            logger.info("STATE: Ventana de seguimiento expirada en LISTENING. Retornando a IDLE.")
            self._context.conversation_active = False
            self.transition_to(SessionState.IDLE)
        else:
            self._context.conversation_active = False

    async def run_follow_up_timeout(self, duration: float | None = None) -> None:
        """Espera de forma no bloqueante mediante asyncio y ejecuta el timeout si expira."""
        wait_time = float(duration if duration is not None else self.follow_up_window)
        try:
            await asyncio.sleep(wait_time)
            if self.is_follow_up_expired():
                self.handle_follow_up_timeout()
        except asyncio.CancelledError:
            logger.debug("STATE: Temporizador de seguimiento cancelado por actividad del usuario.")

    def cancel_timer(self) -> None:
        """Cancela la tarea asíncrona de temporizador si estuviera en ejecución."""
        if self._timer_task is not None and not self._timer_task.done():
            self._timer_task.cancel()
            self._timer_task = None

    def reset(self, new_session_id: str | None = None) -> None:
        """Restablece la máquina de estados y el contexto a estado IDLE inicial."""
        self.cancel_timer()
        self._context.reset(new_session_id=new_session_id)

    def _resolve_state(self, state: SessionState | str) -> SessionState:
        """Resuelve un valor SessionState o string a un enum SessionState válido."""
        if isinstance(state, SessionState):
            return state
        if isinstance(state, str):
            try:
                return SessionState[state.strip().upper()]
            except KeyError:
                raise UnknownStateError(f"Estado desconocido: '{state}'") from None
        raise UnknownStateError(f"Tipo de estado no válido: {type(state)}")

    def _validate_state(self, state: SessionState) -> None:
        """Valida que un estado pertenezca a SessionState."""
        if not isinstance(state, SessionState):
            raise UnknownStateError(f"Estado desconocido o no válido: {state}")

    def _invoke_handlers_sync(self, handlers: list[StateCallback]) -> None:
        """Ejecuta los handlers de forma segura y síncrona."""
        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    try:
                        loop = asyncio.get_running_loop()
                        if loop.is_running():
                            loop.create_task(handler(self._context))
                    except RuntimeError:
                        asyncio.run(handler(self._context))
                else:
                    handler(self._context)
            except Exception as exc:
                logger.error(
                    f"STATE: Error en callback de estado {getattr(handler, '__name__', repr(handler))}: {exc}",
                    exc_info=True,
                )

    async def _invoke_handlers_async(self, handlers: list[StateCallback]) -> None:
        """Ejecuta los handlers de forma asíncrona y awaitable."""
        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    await handler(self._context)
                else:
                    handler(self._context)
            except Exception as exc:
                logger.error(
                    f"STATE: Error en callback asíncrono {getattr(handler, '__name__', repr(handler))}: {exc}",
                    exc_info=True,
                )
