"""Tests de integración para el Adaptador de Verificación Obligatoria de Fase 70.

Cubre exhaustivamente:
- TEST 1: Acción verificada (Execution éxito + Verification evidencia -> VERIFIED).
- TEST 2: Acción fallida (Execution falla -> FAILED).
- TEST 3: No verificable (Execution funciona pero sin verificador -> NOT_VERIFIABLE).
- TEST 4: Verificador falla (Lanza excepción -> NOT_VERIFIABLE / NO VERIFIED).
- TEST 5: Abrir aplicación (Simulación open notepad -> VERIFIED).
- TEST 6: Cerrar aplicación (Simulación cierre -> proceso desaparece -> VERIFIED).
- TEST 7: Cierre fallido (Proceso continúa existiendo -> FAILED).
- TEST 8: Evidence (VerificationResult conserva evidencia estructurada).
- TEST 9: Session ID (VerificationResult conserva session_id).
- TEST 10: State Machine (Comprobar EXECUTING -> VERIFYING -> RESPONDING).
- TEST 11: No falso positivo (Execution retorna éxito pero verification demuestra que no ocurrió -> FAILED).
- TEST 12: Evento único (VerificationResult llega al Event Bus una sola vez).
- TEST 13: Seguridad / Confirmación (requires_confirmation bloquea ejecución directa).
- TEST 14: Verificación de Screenshot (archivo existente y válido en disco).
- TEST 15 / INTEGRACIÓN: Flujo E2E desde UtteranceFinal -> Fast Router -> IntentClassified -> ActionProposed -> Execution -> Verification -> VerificationResult -> Response.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

from core.bus import EventBus
from core.events.base import (
    ActionProposed,
    IntentClassified,
    SpeakRequested,
    UtteranceFinal,
    VerificationResult,
)
from core.execution.execution_verifier import ExecutionEvidence, ExecutionVerifier
from core.execution.verification_event_adapter import (
    ActionVerificationAdapter,
    VerificationStatus,
)
from core.routing.fast_router import FastRouter
from core.state.context import StateContext
from core.state.machine import StateMachine
from core.state.states import SessionState


class FakeExecutionVerifier(ExecutionVerifier):
    """Verificador simulado configurable para pruebas unitarias sin tocar procesos del SO."""

    def __init__(
        self,
        is_verified: bool = True,
        evidence_details: dict[str, Any] | None = None,
        raise_exception: bool = False,
    ) -> None:
        super().__init__()
        self._is_verified = is_verified
        self._evidence_details = evidence_details or {}
        self._raise_exception = raise_exception

    def verify_execution(
        self,
        action: str,
        target: str,
        parameters: dict[str, Any] | None = None,
        timeout_seconds: float = 2.5,
    ) -> ExecutionEvidence:
        if self._raise_exception:
            raise RuntimeError("Fallo simulado de hardware/sensor en verificador.")

        return ExecutionEvidence(
            verification_type="fake_verification",
            target=target,
            is_verified=self._is_verified,
            details=self._evidence_details,
        )


def test_01_action_verified_success() -> None:
    """TEST 1: Execution devuelve éxito y Verification encuentra evidencia -> VERIFIED."""
    async def _run() -> None:
        bus = EventBus()
        sm = StateMachine(context=StateContext(session_id="test_sess_01"))
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        fake_verifier = FakeExecutionVerifier(
            is_verified=True,
            evidence_details={"pids": [12345], "process_exists": True},
        )

        def mock_executor(action: str, params: dict[str, Any]) -> dict[str, Any]:
            return {"exito": True, "action": action}

        results: list[VerificationResult] = []
        bus.subscribe(VerificationResult, lambda e: results.append(e))

        async with ActionVerificationAdapter(
            event_bus=bus,
            state_machine=sm,
            execution_verifier=fake_verifier,
            executor_fn=mock_executor,
        ):
            event = ActionProposed(
                action_name="open_application",
                parameters={"app_name": "notepad"},
                session_id="test_sess_01",
                metadata={"intent": "open_application"},
            )
            await bus.publish(event)

        assert len(results) == 1
        res = results[0]
        assert res.status == VerificationStatus.VERIFIED
        assert res.verified is True
        assert res.confidence == 1.0
        assert res.evidence.get("details", {}).get("pids") == [12345]

    asyncio.run(_run())


def test_02_action_execution_failed() -> None:
    """TEST 2: Execution falla -> FAILED (anti-false success)."""
    async def _run() -> None:
        bus = EventBus()
        sm = StateMachine(context=StateContext(session_id="test_sess_02"))
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        def failing_executor(action: str, params: dict[str, Any]) -> dict[str, Any]:
            return {"exito": False, "error": "Application binary not found"}

        results: list[VerificationResult] = []
        bus.subscribe(VerificationResult, lambda e: results.append(e))

        async with ActionVerificationAdapter(
            event_bus=bus,
            state_machine=sm,
            executor_fn=failing_executor,
        ):
            event = ActionProposed(
                action_name="open_application",
                parameters={"app_name": "non_existent_app"},
                session_id="test_sess_02",
            )
            await bus.publish(event)

        assert len(results) == 1
        res = results[0]
        assert res.status == VerificationStatus.FAILED
        assert res.verified is False
        assert res.confidence == 0.0
        assert "No pude abrir" in (res.message or "")

    asyncio.run(_run())


def test_03_action_not_verifiable() -> None:
    """TEST 3: Execution funciona pero no existe verificador disponible -> NOT_VERIFIABLE."""
    async def _run() -> None:
        bus = EventBus()
        sm = StateMachine(context=StateContext(session_id="test_sess_03"))
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        def ok_executor(action: str, params: dict[str, Any]) -> dict[str, Any]:
            return {"exito": True, "action": action}

        results: list[VerificationResult] = []
        bus.subscribe(VerificationResult, lambda e: results.append(e))

        async with ActionVerificationAdapter(
            event_bus=bus,
            state_machine=sm,
            executor_fn=ok_executor,
        ):
            # Media volume no tiene sensor determinista en este contexto
            event = ActionProposed(
                action_name="media.volume_up",
                parameters={"level": 50},
                session_id="test_sess_03",
            )
            await bus.publish(event)

        assert len(results) == 1
        res = results[0]
        assert res.status == VerificationStatus.NOT_VERIFIABLE
        assert res.verified is False
        assert "no pude verificar" in (res.message or "").lower()

    asyncio.run(_run())


def test_04_verifier_raises_exception() -> None:
    """TEST 4: El verificador lanza excepción -> NO VERIFIED (NOT_VERIFIABLE/FAILED)."""
    async def _run() -> None:
        bus = EventBus()
        sm = StateMachine(context=StateContext(session_id="test_sess_04"))
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        exploding_verifier = FakeExecutionVerifier(raise_exception=True)

        def ok_executor(action: str, params: dict[str, Any]) -> dict[str, Any]:
            return {"exito": True}

        results: list[VerificationResult] = []
        bus.subscribe(VerificationResult, lambda e: results.append(e))

        async with ActionVerificationAdapter(
            event_bus=bus,
            state_machine=sm,
            execution_verifier=exploding_verifier,
            executor_fn=ok_executor,
        ):
            event = ActionProposed(
                action_name="open_application",
                parameters={"app_name": "notepad"},
                session_id="test_sess_04",
            )
            await bus.publish(event)

        assert len(results) == 1
        res = results[0]
        assert res.status != VerificationStatus.VERIFIED
        assert res.verified is False
        assert "verifier_exception" in res.evidence

    asyncio.run(_run())


def test_05_open_application_verified() -> None:
    """TEST 5: Abrir aplicación -> Simular open notepad -> VERIFIED."""
    async def _run() -> None:
        bus = EventBus()
        sm = StateMachine(context=StateContext(session_id="test_sess_05"))
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        mock_verifier = FakeExecutionVerifier(
            is_verified=True,
            evidence_details={"pids": [4567], "matched_names": ["notepad.exe"]},
        )

        def mock_open(action: str, params: dict[str, Any]) -> dict[str, Any]:
            return {"exito": True, "app_state": "APPLICATION_OPENED"}

        results: list[VerificationResult] = []
        speaks: list[SpeakRequested] = []
        bus.subscribe(VerificationResult, lambda e: results.append(e))
        bus.subscribe(SpeakRequested, lambda e: speaks.append(e))

        async with ActionVerificationAdapter(
            event_bus=bus,
            state_machine=sm,
            execution_verifier=mock_verifier,
            executor_fn=mock_open,
        ):
            event = ActionProposed(
                action_name="open_application",
                parameters={"app_name": "notepad"},
                session_id="test_sess_05",
            )
            await bus.publish(event)

        assert len(results) == 1
        assert results[0].status == VerificationStatus.VERIFIED
        assert "Bloc de notas está abierto" in (results[0].message or "")
        assert len(speaks) == 1
        assert "Bloc de notas está abierto" in speaks[0].text

    asyncio.run(_run())


def test_06_close_application_verified() -> None:
    """TEST 6: Cerrar aplicación -> Proceso desaparece -> VERIFIED."""
    async def _run() -> None:
        bus = EventBus()
        sm = StateMachine(context=StateContext(session_id="test_sess_06"))
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        mock_verifier = FakeExecutionVerifier(
            is_verified=True,
            evidence_details={"terminated": True},
        )

        def mock_close(action: str, params: dict[str, Any]) -> dict[str, Any]:
            return {"exito": True, "terminados": 1}

        results: list[VerificationResult] = []
        bus.subscribe(VerificationResult, lambda e: results.append(e))

        async with ActionVerificationAdapter(
            event_bus=bus,
            state_machine=sm,
            execution_verifier=mock_verifier,
            executor_fn=mock_close,
        ):
            event = ActionProposed(
                action_name="close_application",
                parameters={"app_name": "notepad"},
                session_id="test_sess_06",
            )
            await bus.publish(event)

        assert len(results) == 1
        assert results[0].status == VerificationStatus.VERIFIED
        assert "Bloc de notas está cerrado" in (results[0].message or "")

    asyncio.run(_run())


def test_07_close_application_failed_still_running() -> None:
    """TEST 7: Cierre fallido -> Proceso continúa existiendo -> FAILED."""
    async def _run() -> None:
        bus = EventBus()
        sm = StateMachine(context=StateContext(session_id="test_sess_07"))
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        # El verificador comprueba que sigue activo (is_verified=False)
        mock_verifier = FakeExecutionVerifier(
            is_verified=False,
            evidence_details={"terminated": False, "still_running": True},
        )

        def mock_failed_close(action: str, params: dict[str, Any]) -> dict[str, Any]:
            return {"exito": True, "terminados": 0}

        results: list[VerificationResult] = []
        speaks: list[SpeakRequested] = []
        bus.subscribe(VerificationResult, lambda e: results.append(e))
        bus.subscribe(SpeakRequested, lambda e: speaks.append(e))

        async with ActionVerificationAdapter(
            event_bus=bus,
            state_machine=sm,
            execution_verifier=mock_verifier,
            executor_fn=mock_failed_close,
        ):
            event = ActionProposed(
                action_name="close_application",
                parameters={"app_name": "notepad"},
                session_id="test_sess_07",
            )
            await bus.publish(event)

        assert len(results) == 1
        assert results[0].status == VerificationStatus.FAILED
        assert results[0].verified is False
        # Anti-false success: NO debe decir "Listo, cerrado."
        assert "Listo" not in (results[0].message or "")
        assert "No pude cerrar" in (results[0].message or "")
        assert "No pude cerrar" in speaks[0].text

    asyncio.run(_run())


def test_08_evidence_preserved() -> None:
    """TEST 8: VerificationResult conserva evidencia estructurada correctamente."""
    async def _run() -> None:
        bus = EventBus()
        sm = StateMachine(context=StateContext(session_id="test_sess_08"))
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        evidence_payload = {"pids": [9999], "window_found": True, "cpu_percent": 0.5}
        fake_verifier = FakeExecutionVerifier(
            is_verified=True,
            evidence_details=evidence_payload,
        )

        results: list[VerificationResult] = []
        bus.subscribe(VerificationResult, lambda e: results.append(e))

        async with ActionVerificationAdapter(
            event_bus=bus,
            state_machine=sm,
            execution_verifier=fake_verifier,
            executor_fn=lambda a, p: {"exito": True},
        ):
            event = ActionProposed(
                action_name="open_application",
                parameters={"app_name": "calc"},
                session_id="test_sess_08",
            )
            await bus.publish(event)

        assert len(results) == 1
        assert results[0].evidence["details"] == evidence_payload

    asyncio.run(_run())


def test_09_session_id_preserved() -> None:
    """TEST 9: VerificationResult conserva el session_id original de forma estricta."""
    async def _run() -> None:
        bus = EventBus()
        unique_session = "custom_session_id_xyz_123"

        results: list[VerificationResult] = []
        bus.subscribe(VerificationResult, lambda e: results.append(e))

        async with ActionVerificationAdapter(
            event_bus=bus,
            execution_verifier=FakeExecutionVerifier(is_verified=True),
            executor_fn=lambda a, p: {"exito": True},
        ):
            event = ActionProposed(
                action_name="open_application",
                parameters={"app_name": "notepad"},
                session_id=unique_session,
            )
            await bus.publish(event)

        assert len(results) == 1
        assert results[0].session_id == unique_session

    asyncio.run(_run())


def test_10_state_machine_transition_lifecycle() -> None:
    """TEST 10: Comprobar transiciones formales: EXECUTING -> VERIFYING -> RESPONDING."""
    async def _run() -> None:
        bus = EventBus()
        sm = StateMachine(context=StateContext(session_id="test_sess_10"))
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        visited_states: list[SessionState] = []
        sm.on_enter(SessionState.EXECUTING, lambda ctx: visited_states.append(SessionState.EXECUTING))
        sm.on_enter(SessionState.VERIFYING, lambda ctx: visited_states.append(SessionState.VERIFYING))
        sm.on_enter(SessionState.RESPONDING, lambda ctx: visited_states.append(SessionState.RESPONDING))

        async with ActionVerificationAdapter(
            event_bus=bus,
            state_machine=sm,
            execution_verifier=FakeExecutionVerifier(is_verified=True),
            executor_fn=lambda a, p: {"exito": True},
        ):
            event = ActionProposed(
                action_name="open_application",
                parameters={"app_name": "notepad"},
                session_id="test_sess_10",
            )
            await bus.publish(event)

        assert SessionState.EXECUTING in visited_states
        assert SessionState.VERIFYING in visited_states
        assert SessionState.RESPONDING in visited_states

        # Orden riguroso de aparición
        idx_exec = visited_states.index(SessionState.EXECUTING)
        idx_verif = visited_states.index(SessionState.VERIFYING)
        idx_resp = visited_states.index(SessionState.RESPONDING)

        assert idx_exec < idx_verif < idx_resp

    asyncio.run(_run())


def test_11_no_false_positive_when_process_missing() -> None:
    """TEST 11: No falso positivo: Execution retorna éxito pero el proceso no existe -> FAILED."""
    async def _run() -> None:
        bus = EventBus()
        sm = StateMachine(context=StateContext(session_id="test_sess_11"))
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        # Launcher dijo "subprocess spawned", pero el proceso nunca apareció
        fake_verifier = FakeExecutionVerifier(
            is_verified=False,
            evidence_details={"searched_names": ["notepad.exe"], "found_pids": []},
        )

        def sneaky_executor(action: str, params: dict[str, Any]) -> dict[str, Any]:
            return {"exito": True, "mensaje": "Comando enviado"}

        results: list[VerificationResult] = []
        bus.subscribe(VerificationResult, lambda e: results.append(e))

        async with ActionVerificationAdapter(
            event_bus=bus,
            state_machine=sm,
            execution_verifier=fake_verifier,
            executor_fn=sneaky_executor,
        ):
            event = ActionProposed(
                action_name="open_application",
                parameters={"app_name": "notepad"},
                session_id="test_sess_11",
            )
            await bus.publish(event)

        assert len(results) == 1
        # ANTI-FALSE SUCCESS: Debe ser FAILED, no VERIFIED
        assert results[0].status == VerificationStatus.FAILED
        assert results[0].verified is False
        assert "No pude abrir" in (results[0].message or "")

    asyncio.run(_run())


def test_12_single_event_published_no_duplicates() -> None:
    """TEST 12: VerificationResult llega al Event Bus exactamente UNA vez."""
    async def _run() -> None:
        bus = EventBus()

        results: list[VerificationResult] = []
        bus.subscribe(VerificationResult, lambda e: results.append(e))

        adapter = ActionVerificationAdapter(
            event_bus=bus,
            execution_verifier=FakeExecutionVerifier(is_verified=True),
            executor_fn=lambda a, p: {"exito": True},
        )

        async with adapter:
            event = ActionProposed(
                action_name="open_application",
                parameters={"app_name": "calc"},
                session_id="test_sess_12",
            )
            await bus.publish(event)
            # Intentar publicar el mismo evento nuevamente
            await bus.publish(event)

        # Deduplicación garantiza exactamente 1
        assert len(results) == 1

    asyncio.run(_run())


def test_13_security_confirmation_blocks_immediate_execution() -> None:
    """TEST 13: Comprueba que acciones con requires_confirmation transicionan a CONFIRMING y no ejecutan."""
    async def _run() -> None:
        bus = EventBus()
        sm = StateMachine(context=StateContext(session_id="test_sess_13"))
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        mock_exec = MagicMock()
        results: list[VerificationResult] = []
        bus.subscribe(VerificationResult, lambda e: results.append(e))

        async with ActionVerificationAdapter(
            event_bus=bus,
            state_machine=sm,
            executor_fn=mock_exec,
        ):
            event = ActionProposed(
                action_name="delete_database",
                parameters={"target": "production"},
                session_id="test_sess_13",
                metadata={"requires_confirmation": True},
            )
            await bus.publish(event)

        assert sm.current_state == SessionState.CONFIRMING
        mock_exec.assert_not_called()
        assert len(results) == 0

    asyncio.run(_run())


def test_14_screenshot_verification(tmp_path: Any) -> None:
    """TEST 14: Verificación de captura de pantalla (comprueba archivo existente y válido)."""
    async def _run() -> None:
        bus = EventBus()
        test_img = tmp_path / "screenshot_test.png"
        test_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        results: list[VerificationResult] = []
        bus.subscribe(VerificationResult, lambda e: results.append(e))

        async with ActionVerificationAdapter(
            event_bus=bus,
            executor_fn=lambda a, p: {"exito": True, "path": str(test_img)},
        ):
            event = ActionProposed(
                action_name="screenshot",
                parameters={"path": str(test_img)},
                session_id="test_sess_14",
            )
            await bus.publish(event)

        assert len(results) == 1
        assert results[0].status == VerificationStatus.VERIFIED
        assert results[0].verified is True
        assert results[0].evidence["file_exists"] is True
        assert results[0].evidence["size_bytes"] > 0

    asyncio.run(_run())


def test_15_end_to_end_integration_utterance_to_response() -> None:
    """TEST 15 / INTEGRACIÓN: Simula el flujo completo de voz a verificación y respuesta:

    UtteranceFinal
      ↓
    Fast Router
      ↓
    IntentClassified
      ↓
    ActionProposed
      ↓
    Execution
      ↓
    Verification
      ↓
    VerificationResult
      ↓
    SpeakRequested
    """
    async def _run() -> None:
        bus = EventBus()
        sm = StateMachine(context=StateContext(session_id="e2e_session"))
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)

        router = FastRouter()
        fake_verifier = FakeExecutionVerifier(
            is_verified=True,
            evidence_details={"pids": [1122], "matched_names": ["notepad.exe"]},
        )

        intents: list[IntentClassified] = []
        actions: list[ActionProposed] = []
        verifs: list[VerificationResult] = []
        speaks: list[SpeakRequested] = []

        bus.subscribe(IntentClassified, lambda e: intents.append(e))
        bus.subscribe(ActionProposed, lambda e: actions.append(e))
        bus.subscribe(VerificationResult, lambda e: verifs.append(e))
        bus.subscribe(SpeakRequested, lambda e: speaks.append(e))

        async def on_utterance(event: UtteranceFinal) -> None:
            # 1. State machine -> ROUTING
            if sm.can_transition_to(SessionState.ROUTING):
                sm.transition_to(SessionState.ROUTING)

            # 2. Fast Router
            decision = router.route(event.text)
            if decision.category.value == "COMMAND":
                intent_event = IntentClassified(
                    intent=decision.intent,
                    confidence=decision.confidence,
                    slots=decision.parameters,
                    raw_text=event.text,
                    session_id=event.session_id,
                )
                await bus.publish(intent_event)

                action_event = ActionProposed(
                    action_name=decision.target_skill or decision.intent,
                    parameters=decision.parameters,
                    session_id=event.session_id,
                    metadata={"intent": decision.intent},
                )
                await bus.publish(action_event)

        bus.subscribe(UtteranceFinal, on_utterance)

        def mock_executor(action: str, params: dict[str, Any]) -> dict[str, Any]:
            return {"exito": True, "action": action, "pid": 1122}

        async with ActionVerificationAdapter(
            event_bus=bus,
            state_machine=sm,
            execution_verifier=fake_verifier,
            executor_fn=mock_executor,
        ):
            # Disparar locución de usuario
            await bus.publish(
                UtteranceFinal(
                    text="abre bloc de notas",
                    session_id="e2e_session",
                )
            )

        # Verificaciones del flujo E2E
        assert len(intents) == 1
        assert intents[0].intent == "open_application"
        assert str(intents[0].slots.get("app_name")).lower() == "notepad"

        assert len(actions) == 1
        assert actions[0].action_name in ("windows.apps", "open_application")
        assert actions[0].session_id == "e2e_session"

        assert len(verifs) == 1
        assert verifs[0].status == VerificationStatus.VERIFIED
        assert verifs[0].verified is True
        assert verifs[0].session_id == "e2e_session"

        assert len(speaks) == 1
        assert "Bloc de notas está abierto" in speaks[0].text
        assert sm.current_state == SessionState.RESPONDING

    asyncio.run(_run())
