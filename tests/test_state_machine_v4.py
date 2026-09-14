"""Pruebas unitarias completas para la Máquina de Estados de JESSYCA 4.0 (Fase 66).

Cubre todos los requerimientos obligatorios:
- TEST 1: Estado inicial IDLE.
- TEST 2: Transición IDLE → WAKEWORD.
- TEST 3: Transición completa (IDLE → WAKEWORD → LISTENING → TRANSCRIBING → ROUTING → EXECUTING → VERIFYING → RESPONDING → IDLE).
- TEST 4: Transición de conversación (RESPONDING → LISTENING).
- TEST 5: Transición de confirmación (ROUTING → CONFIRMING → EXECUTING).
- TEST 6: Transición de aclaración (ROUTING → CLARIFYING → LISTENING → TRANSCRIBING → ROUTING).
- TEST 7: Transición inválida rechazada (IDLE → EXECUTING).
- TEST 8: previous_state correctamente mantenido.
- TEST 9: session_id único y accesible.
- TEST 10: conversation_active gestionado correctamente.
- TEST 11: follow_up_deadline renovable.
- TEST 12: Expiración de conversación con asyncio sin time.sleep() bloqueante.
- TEST 13: Entry handlers ejecutados al ingresar a un estado.
- TEST 14: Exit handlers ejecutados al salir de un estado.
- TEST 15: Transición inválida no corrompe el estado actual.
- Aislamiento completo sin dependencias de hardware real (micrófono, GPU, Ollama, TTS, Windows UI).
"""

from __future__ import annotations

import asyncio

import pytest

from core.state import (
    InvalidStateTransitionError,
    SessionState,
    StateContext,
    StateMachine,
    UnknownStateError,
)


def get_state(machine: StateMachine) -> SessionState:
    """Helper para obtener el estado actual sin false type narrowing de mypy."""
    return machine.current_state


def get_prev_state(machine: StateMachine) -> SessionState | None:
    """Helper para obtener el estado previo sin false type narrowing de mypy."""
    return machine.previous_state



# ---------------------------------------------------------------------------
# TEST 1: Estado inicial IDLE
# ---------------------------------------------------------------------------

def test_1_initial_state_idle() -> None:
    """Verifica que la máquina de estados inicia siempre en IDLE por defecto."""
    machine = StateMachine()
    assert machine.current_state == SessionState.IDLE
    assert machine.previous_state is None
    assert machine.conversation_active is False


# ---------------------------------------------------------------------------
# TEST 2: Transición IDLE → WAKEWORD
# ---------------------------------------------------------------------------
def test_2_transition_idle_to_wakeword() -> None:
    """Verifica que la transición de inicio de interacción IDLE → WAKEWORD es válida."""
    machine = StateMachine()
    machine.transition_to(SessionState.WAKEWORD)
    assert machine.current_state == SessionState.WAKEWORD
    assert machine.previous_state == SessionState.IDLE


# ---------------------------------------------------------------------------
# TEST 3: Flujo canónico completo
# ---------------------------------------------------------------------------
def test_3_full_pipeline_flow() -> None:
    """Verifica el recorrido completo del ciclo de comando:

    IDLE → WAKEWORD → LISTENING → TRANSCRIBING → ROUTING → EXECUTING → VERIFYING → RESPONDING → IDLE
    """
    machine = StateMachine()

    flow = [
        SessionState.WAKEWORD,
        SessionState.LISTENING,
        SessionState.TRANSCRIBING,
        SessionState.ROUTING,
        SessionState.EXECUTING,
        SessionState.VERIFYING,
        SessionState.RESPONDING,
        SessionState.IDLE,
    ]

    for target in flow:
        assert machine.can_transition_to(target) is True
        machine.transition_to(target)

    assert machine.current_state == SessionState.IDLE
    assert machine.previous_state == SessionState.RESPONDING


# ---------------------------------------------------------------------------
# TEST 4: Transición de conversación continua (RESPONDING → LISTENING)
# ---------------------------------------------------------------------------
def test_4_conversational_follow_up_transition() -> None:
    """Verifica que tras responder, la máquina puede pasar directamente a LISTENING."""
    machine = StateMachine()

    # Avanzar hasta RESPONDING
    for state in [
        SessionState.WAKEWORD,
        SessionState.LISTENING,
        SessionState.TRANSCRIBING,
        SessionState.ROUTING,
        SessionState.RESPONDING,
    ]:
        machine.transition_to(state)

    assert get_state(machine) == SessionState.RESPONDING
    # Transición conversacional
    assert machine.can_transition_to(SessionState.LISTENING) is True
    machine.transition_to(SessionState.LISTENING)

    assert get_state(machine) == SessionState.LISTENING
    assert machine.previous_state == SessionState.RESPONDING




# ---------------------------------------------------------------------------
# TEST 5: Transición de confirmación (ROUTING → CONFIRMING → EXECUTING)
# ---------------------------------------------------------------------------
def test_5_confirmation_flow() -> None:
    """Verifica el flujo para acciones con confirmación requerida."""
    machine = StateMachine()

    for state in [
        SessionState.WAKEWORD,
        SessionState.LISTENING,
        SessionState.TRANSCRIBING,
        SessionState.ROUTING,
    ]:
        machine.transition_to(state)

    assert get_state(machine) == SessionState.ROUTING

    # Enrutamiento a confirmación
    machine.transition_to(SessionState.CONFIRMING)
    assert get_state(machine) == SessionState.CONFIRMING
    assert get_prev_state(machine) == SessionState.ROUTING

    # Confirmación concedida -> ejecución
    machine.transition_to(SessionState.EXECUTING)
    assert get_state(machine) == SessionState.EXECUTING
    assert get_prev_state(machine) == SessionState.CONFIRMING


# ---------------------------------------------------------------------------
# TEST 6: Transición de aclaración (ROUTING → CLARIFYING → LISTENING → TRANSCRIBING → ROUTING)
# ---------------------------------------------------------------------------
def test_6_clarification_flow() -> None:
    """Verifica el ciclo de solicitud de aclaración ante ambigüedad."""
    machine = StateMachine()

    for state in [
        SessionState.WAKEWORD,
        SessionState.LISTENING,
        SessionState.TRANSCRIBING,
        SessionState.ROUTING,
    ]:
        machine.transition_to(state)

    assert get_state(machine) == SessionState.ROUTING

    # Pasa a aclaración
    machine.transition_to(SessionState.CLARIFYING)
    assert get_state(machine) == SessionState.CLARIFYING

    # Vuelve a escuchar aclaración del usuario
    machine.transition_to(SessionState.LISTENING)
    assert get_state(machine) == SessionState.LISTENING

    # Transcribe y enruta de nuevo
    machine.transition_to(SessionState.TRANSCRIBING)
    machine.transition_to(SessionState.ROUTING)
    assert get_state(machine) == SessionState.ROUTING


# ---------------------------------------------------------------------------
# TEST 7: Transición inválida rechazada (IDLE → EXECUTING)
# ---------------------------------------------------------------------------
def test_7_invalid_transition_rejected() -> None:
    """Verifica que una transición prohibida lance InvalidStateTransitionError."""
    machine = StateMachine()
    assert machine.current_state == SessionState.IDLE

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        machine.transition_to(SessionState.EXECUTING)

    assert exc_info.value.from_state == "IDLE"
    assert exc_info.value.to_state == "EXECUTING"


# ---------------------------------------------------------------------------
# TEST 8: previous_state
# ---------------------------------------------------------------------------
def test_8_previous_state_tracking() -> None:
    """Verifica que previous_state se actualice fielmente en cada paso."""
    machine = StateMachine()
    assert get_prev_state(machine) is None

    machine.transition_to(SessionState.WAKEWORD)
    assert get_prev_state(machine) == SessionState.IDLE

    machine.transition_to(SessionState.LISTENING)
    assert get_prev_state(machine) == SessionState.WAKEWORD

    machine.transition_to(SessionState.IDLE)
    assert get_prev_state(machine) == SessionState.LISTENING


# ---------------------------------------------------------------------------
# TEST 9: session_id
# ---------------------------------------------------------------------------
def test_9_session_id_persistence_and_reset() -> None:
    """Verifica que el identificador de sesión se preserve y pueda restablecerse."""
    custom_id = "test-session-12345"
    ctx = StateContext(session_id=custom_id)
    machine = StateMachine(context=ctx)

    assert machine.session_id == custom_id

    # Reset genera nuevo session_id si no se especifica
    machine.reset()
    assert machine.session_id != custom_id
    assert len(machine.session_id) >= 32


# ---------------------------------------------------------------------------
# TEST 10: conversation_active
# ---------------------------------------------------------------------------
def test_10_conversation_active_lifecycle() -> None:
    """Verifica el estado del flag de conversación continua."""
    machine = StateMachine(follow_up_window=10.0)
    assert machine.conversation_active is False

    machine.renew_follow_up()
    assert machine.conversation_active is True

    # Avanzar a LISTENING y provocar timeout de seguimiento
    machine.transition_to(SessionState.WAKEWORD)
    machine.transition_to(SessionState.LISTENING)
    machine.handle_follow_up_timeout()

    assert machine.current_state == SessionState.IDLE
    assert machine.conversation_active is False


# ---------------------------------------------------------------------------
# TEST 11: Renovación de follow_up_deadline
# ---------------------------------------------------------------------------
def test_11_follow_up_deadline_renewal() -> None:
    """Verifica que el deadline de seguimiento se renueva adecuadamente con ventana configurable."""
    machine = StateMachine(follow_up_window=20.0)

    t1 = machine.renew_follow_up()
    assert machine.context.follow_up_deadline == t1
    assert machine.is_follow_up_expired() is False

    # Renovar con parámetro explícito diferente
    t2 = machine.renew_follow_up(window_seconds=30.0)
    assert t2 > t1
    assert machine.context.follow_up_deadline == t2


# ---------------------------------------------------------------------------
# TEST 12: Expiración de conversación con asyncio sin time.sleep()
# ---------------------------------------------------------------------------
def test_12_non_blocking_timeout_expiration() -> None:
    """Verifica la expiración asíncrona de la ventana de seguimiento sin sleep bloqueante."""
    async def _run() -> None:
        # Ventana mínima para prueba asíncrona no bloqueante
        machine = StateMachine(follow_up_window=0.05)

        machine.transition_to(SessionState.WAKEWORD)
        machine.transition_to(SessionState.LISTENING)
        machine.renew_follow_up(window_seconds=0.05)

        assert get_state(machine) == SessionState.LISTENING
        assert machine.conversation_active is True

        # Espera asíncrona no bloqueante
        await machine.run_follow_up_timeout(duration=0.06)

        # Debe haber expirado y retornado a IDLE
        assert get_state(machine) == SessionState.IDLE
        assert machine.conversation_active is False

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# TEST 13: Entry handlers
# ---------------------------------------------------------------------------
def test_13_entry_handlers_execution() -> None:
    """Verifica que los handlers de entrada al estado se ejecutan en orden."""
    machine = StateMachine()
    entry_logs: list[str] = []

    def on_enter_wakeword(ctx: StateContext) -> None:
        entry_logs.append(f"enter:{ctx.current_state.value}")

    def on_enter_listening(ctx: StateContext) -> None:
        entry_logs.append(f"enter:{ctx.current_state.value}")

    machine.on_enter(SessionState.WAKEWORD, on_enter_wakeword)
    machine.on_enter(SessionState.LISTENING, on_enter_listening)

    machine.transition_to(SessionState.WAKEWORD)
    assert entry_logs == ["enter:WAKEWORD"]

    machine.transition_to(SessionState.LISTENING)
    assert entry_logs == ["enter:WAKEWORD", "enter:LISTENING"]


# ---------------------------------------------------------------------------
# TEST 14: Exit handlers
# ---------------------------------------------------------------------------
def test_14_exit_handlers_execution() -> None:
    """Verifica que los handlers de salida del estado se ejecutan antes de ingresar al nuevo estado."""
    machine = StateMachine()
    exit_logs: list[str] = []

    def on_exit_idle(ctx: StateContext) -> None:
        exit_logs.append(f"exit:{ctx.current_state.value}")

    def on_exit_wakeword(ctx: StateContext) -> None:
        exit_logs.append(f"exit:{ctx.current_state.value}")

    machine.on_exit(SessionState.IDLE, on_exit_idle)
    machine.on_exit(SessionState.WAKEWORD, on_exit_wakeword)

    machine.transition_to(SessionState.WAKEWORD)
    assert exit_logs == ["exit:IDLE"]

    machine.transition_to(SessionState.LISTENING)
    assert exit_logs == ["exit:IDLE", "exit:WAKEWORD"]


# ---------------------------------------------------------------------------
# TEST 15: Transición inválida no corrompe el estado actual
# ---------------------------------------------------------------------------
def test_15_invalid_transition_preserves_state() -> None:
    """Verifica que el rechazo de una transición mantenga intacto el estado y contexto previos."""
    machine = StateMachine()
    machine.transition_to(SessionState.WAKEWORD)
    assert machine.current_state == SessionState.WAKEWORD
    assert machine.previous_state == SessionState.IDLE

    # Intento de transición prohibida: WAKEWORD → EXECUTING
    with pytest.raises(InvalidStateTransitionError):
        machine.transition_to(SessionState.EXECUTING)

    # El estado no debe haber cambiado
    assert machine.current_state == SessionState.WAKEWORD
    assert machine.previous_state == SessionState.IDLE


# ---------------------------------------------------------------------------
# TEST 16: Resolución por string y errores de estado desconocido
# ---------------------------------------------------------------------------
def test_16_string_resolution_and_unknown_state_error() -> None:
    """Verifica la aceptación de nombres en mayúsculas/minúsculas y rechazo de nombres desconocidos."""
    machine = StateMachine()
    machine.transition_to("wakeword")
    assert machine.current_state == SessionState.WAKEWORD

    with pytest.raises(UnknownStateError):
        machine.transition_to("ESTADO_INEXISTENTE")


# ---------------------------------------------------------------------------
# TEST 17: Transición asíncrona con handlers async
# ---------------------------------------------------------------------------
def test_17_async_transition_with_async_handlers() -> None:
    """Verifica que transition_to_async soporte y espere adecuadamente corrutinas async def."""
    async def _run() -> None:
        machine = StateMachine()
        events: list[str] = []

        async def async_entry(ctx: StateContext) -> None:
            await asyncio.sleep(0.01)
            events.append("async_entry_wakeword")

        async def async_exit(ctx: StateContext) -> None:
            await asyncio.sleep(0.01)
            events.append("async_exit_idle")

        machine.on_exit(SessionState.IDLE, async_exit)
        machine.on_enter(SessionState.WAKEWORD, async_entry)

        await machine.transition_to_async(SessionState.WAKEWORD)

        assert events == ["async_exit_idle", "async_entry_wakeword"]
        assert machine.current_state == SessionState.WAKEWORD

    asyncio.run(_run())
