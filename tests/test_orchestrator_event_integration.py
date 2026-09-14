"""Tests unitarios y de integración para la Fase 68.

Valida la integración de Orchestrator con Event Bus y State Machine:
- Test 1: UtteranceFinal llega al Orchestrator.
- Test 2: El texto original se conserva.
- Test 3: session_id se conserva.
- Test 4: IntentClassified se publica correctamente.
- Test 5: ActionProposed se publica correctamente.
- Test 6: Respuesta conversacional se procesa correctamente.
- Test 7: ClarificationRequested funciona correctamente.
- Test 8: Una excepción del Orchestrator no destruye el Event Bus.
- Test 9: La State Machine conserva un estado válido después de un error.
- Test 10: No existen handlers duplicados.
- Test 11: Dos mensajes consecutivos pueden procesarse dentro de la misma sesión.
- Test 12 / Test 13: Pruebas de integración de comandos ("abre bloc de notas") y conversación ("¿qué es la gravedad?").
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

from core.bus import EventBus
from core.events.base import (
    ActionProposed,
    ClarificationRequested,
    ErrorOccurred,
    IntentClassified,
    SpeakRequested,
    UtteranceFinal,
)
from core.orchestrator_adapter import OrchestratorAdapter
from core.state.machine import StateMachine
from core.state.states import SessionState


class DummyResponse:
    """Objeto representativo de una respuesta de JessycaLocalAgent."""

    def __init__(
        self,
        intent: str = "unknown",
        response_text: str = "",
        spoken_text: str = "",
        selected_skill: str = "auto",
        requires_clarification: bool = False,
        clarification_question: str | None = None,
        requires_confirmation: bool = False,
        output_data: Any = None,
    ) -> None:
        self.intent = intent
        self.response_text = response_text
        self.spoken_text = spoken_text
        self.selected_skill = selected_skill
        self.requires_clarification = requires_clarification
        self.clarification_question = clarification_question
        self.requires_confirmation = requires_confirmation
        self.output_data = output_data or {}


def test_01_utterance_final_llega_al_orchestrator() -> None:
    """Test 1: Verifica que el evento UtteranceFinal llega al Orchestrator."""

    async def _test() -> None:
        bus = EventBus()
        called_with = []

        def dummy_orchestrator(text: str) -> str:
            called_with.append(text)
            return "Hola"

        adapter = OrchestratorAdapter(orchestrator=dummy_orchestrator, event_bus=bus)
        adapter.start()

        event = UtteranceFinal(text="prueba de voz", session_id="ses-01")
        await bus.publish(event)

        assert len(called_with) == 1
        assert called_with[0] == "prueba de voz"
        adapter.stop()

    asyncio.run(_test())


def test_02_texto_original_se_conserva() -> None:
    """Test 2: Verifica que el texto original se conserva en los eventos emitidos."""

    async def _test() -> None:
        bus = EventBus()
        classified_events: list[IntentClassified] = []
        bus.subscribe(IntentClassified, lambda e: classified_events.append(e))

        def dummy_orchestrator(text: str) -> str:
            return "Entendido"

        adapter = OrchestratorAdapter(orchestrator=dummy_orchestrator, event_bus=bus)
        adapter.start()

        original_text = "¿Qué hora es en Tokio?"
        await bus.publish(UtteranceFinal(text=original_text, session_id="ses-02"))

        assert len(classified_events) == 1
        assert classified_events[0].raw_text == original_text
        adapter.stop()

    asyncio.run(_test())


def test_03_session_id_se_conserva() -> None:
    """Test 3: Verifica que el session_id se conserva a lo largo del flujo."""

    async def _test() -> None:
        bus = EventBus()
        spoken_events: list[SpeakRequested] = []
        classified_events: list[IntentClassified] = []
        bus.subscribe(SpeakRequested, lambda e: spoken_events.append(e))
        bus.subscribe(IntentClassified, lambda e: classified_events.append(e))

        def dummy_orchestrator(text: str) -> str:
            return "Respuesta de prueba"

        adapter = OrchestratorAdapter(orchestrator=dummy_orchestrator, event_bus=bus)
        adapter.start()

        test_session_id = "session-custom-abc-123"
        await bus.publish(UtteranceFinal(text="Hola", session_id=test_session_id))

        assert len(classified_events) == 1
        assert classified_events[0].session_id == test_session_id
        assert len(spoken_events) == 1
        assert spoken_events[0].session_id == test_session_id
        adapter.stop()

    asyncio.run(_test())


def test_04_intent_classified_se_publica_correctamente() -> None:
    """Test 4: Verifica que IntentClassified se publica con intent y metadatos correctos."""

    async def _test() -> None:
        bus = EventBus()
        classified_events: list[IntentClassified] = []
        bus.subscribe(IntentClassified, lambda e: classified_events.append(e))

        mock_resp = DummyResponse(
            intent="consultar_clima",
            response_text="El clima está soleado",
            spoken_text="El clima está soleado",
        )
        mock_agent = MagicMock()
        mock_agent.interact.return_value = mock_resp

        adapter = OrchestratorAdapter(orchestrator=mock_agent, event_bus=bus)
        adapter.start()

        await bus.publish(UtteranceFinal(text="¿cómo está el clima?", session_id="ses-04"))

        assert len(classified_events) == 1
        assert classified_events[0].intent == "consultar_clima"
        assert classified_events[0].raw_text == "¿cómo está el clima?"
        assert classified_events[0].session_id == "ses-04"
        adapter.stop()

    asyncio.run(_test())


def test_05_action_proposed_se_publica_correctamente() -> None:
    """Test 5: Verifica que ActionProposed se publica correctamente al determinar una acción."""

    async def _test() -> None:
        bus = EventBus()
        action_events: list[ActionProposed] = []
        bus.subscribe(ActionProposed, lambda e: action_events.append(e))

        sm = StateMachine()
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        mock_resp = DummyResponse(
            intent="abrir_aplicacion",
            selected_skill="apps_skill",
            output_data={"app_name": "notepad"},
            response_text="Abriendo el bloc de notas.",
        )
        mock_agent = MagicMock()
        mock_agent.interact.return_value = mock_resp

        adapter = OrchestratorAdapter(orchestrator=mock_agent, event_bus=bus, state_machine=sm)
        adapter.start()

        await bus.publish(UtteranceFinal(text="abre bloc de notas", session_id="ses-05"))

        assert len(action_events) == 1
        assert action_events[0].action_name == "apps_skill"
        assert action_events[0].parameters == {"app_name": "notepad"}
        assert action_events[0].session_id == "ses-05"
        # State machine debe transicionar a EXECUTING
        assert sm.current_state.value == SessionState.EXECUTING.value
        adapter.stop()

    asyncio.run(_test())


def test_06_conversacion_normal_produce_speak_requested() -> None:
    """Test 6: Verifica que una consulta conversacional produce SpeakRequested y estado RESPONDING."""

    async def _test() -> None:
        bus = EventBus()
        spoken_events: list[SpeakRequested] = []
        bus.subscribe(SpeakRequested, lambda e: spoken_events.append(e))

        sm = StateMachine()
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        mock_resp = DummyResponse(
            intent="chit_chat",
            selected_skill="auto",
            response_text="¡Hola! Estoy muy bien, gracias por preguntar.",
            spoken_text="¡Hola! Estoy muy bien, gracias por preguntar.",
        )
        mock_agent = MagicMock()
        mock_agent.interact.return_value = mock_resp

        adapter = OrchestratorAdapter(orchestrator=mock_agent, event_bus=bus, state_machine=sm)
        adapter.start()

        await bus.publish(UtteranceFinal(text="¿Cómo estás?", session_id="ses-06"))

        assert len(spoken_events) == 1
        assert spoken_events[0].text == "¡Hola! Estoy muy bien, gracias por preguntar."
        assert spoken_events[0].session_id == "ses-06"
        assert sm.current_state.value == SessionState.RESPONDING.value
        adapter.stop()

    asyncio.run(_test())


def test_07_clarification_requested_funciona_correctamente() -> None:
    """Test 7: Verifica que una solicitud de aclaración produce ClarificationRequested y estado CLARIFYING."""

    async def _test() -> None:
        bus = EventBus()
        clarif_events: list[ClarificationRequested] = []
        bus.subscribe(ClarificationRequested, lambda e: clarif_events.append(e))

        sm = StateMachine()
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        mock_resp = DummyResponse(
            intent="abrir_navegador",
            requires_clarification=True,
            clarification_question="¿Deseas abrir Chrome o Edge?",
            response_text="¿Deseas abrir Chrome o Edge?",
        )
        mock_agent = MagicMock()
        mock_agent.interact.return_value = mock_resp

        adapter = OrchestratorAdapter(orchestrator=mock_agent, event_bus=bus, state_machine=sm)
        adapter.start()

        await bus.publish(UtteranceFinal(text="abre el navegador", session_id="ses-07"))

        assert len(clarif_events) == 1
        assert clarif_events[0].question == "¿Deseas abrir Chrome o Edge?"
        assert clarif_events[0].original_text == "abre el navegador"
        assert clarif_events[0].session_id == "ses-07"
        assert sm.current_state.value == SessionState.CLARIFYING.value
        adapter.stop()

    asyncio.run(_test())


def test_08_excepcion_orchestrator_no_destruye_event_bus() -> None:
    """Test 8: Verifica que una excepción en el Orchestrator publica ErrorOccurred sin tumbar el bus."""

    async def _test() -> None:
        bus = EventBus()
        error_events: list[ErrorOccurred] = []
        bus.subscribe(ErrorOccurred, lambda e: error_events.append(e))

        def failing_orchestrator(text: str) -> str:
            raise RuntimeError("Fallo simulado en el motor de inferencia")

        adapter = OrchestratorAdapter(orchestrator=failing_orchestrator, event_bus=bus)
        adapter.start()

        # No debe lanzar excepción
        await bus.publish(UtteranceFinal(text="haz algo", session_id="ses-08"))

        assert len(error_events) == 1
        assert "Fallo simulado" in error_events[0].error_message
        assert error_events[0].error_type == "RuntimeError"
        assert error_events[0].session_id == "ses-08"

        # El Event Bus debe seguir funcionando para eventos posteriores
        normal_calls: list[str] = []
        bus.subscribe(UtteranceFinal, lambda e: normal_calls.append(e.text))
        await bus.publish(UtteranceFinal(text="siguiente evento", session_id="ses-08-b"))
        assert "siguiente evento" in normal_calls

        adapter.stop()

    asyncio.run(_test())


def test_09_state_machine_conserva_estado_valido_tras_error() -> None:
    """Test 9: Verifica que la State Machine regresa a un estado canónico válido tras un error."""

    async def _test() -> None:
        bus = EventBus()
        sm = StateMachine()
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        def failing_orchestrator(text: str) -> str:
            raise ValueError("Parámetro inválido simulado")

        adapter = OrchestratorAdapter(orchestrator=failing_orchestrator, event_bus=bus, state_machine=sm)
        adapter.start()

        await bus.publish(UtteranceFinal(text="orden fallida", session_id="ses-09"))

        # El State Machine debe haber recuperado a IDLE
        assert sm.current_state.value == SessionState.IDLE.value
        # Debe ser capaz de iniciar un nuevo ciclo
        assert sm.can_transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.WAKEWORD)
        assert sm.current_state.value == SessionState.WAKEWORD.value

        adapter.stop()

    asyncio.run(_test())


def test_10_no_existen_handlers_duplicados() -> None:
    """Test 10: Verifica que llamadas múltiples a start() no duplican las suscripciones."""

    async def _test() -> None:
        bus = EventBus()
        call_count = [0]

        def dummy_orchestrator(text: str) -> str:
            call_count[0] += 1
            return "ok"

        adapter = OrchestratorAdapter(orchestrator=dummy_orchestrator, event_bus=bus)
        adapter.start()
        adapter.start()
        adapter.start()

        await bus.publish(UtteranceFinal(text="un solo mensaje", session_id="ses-10"))

        assert call_count[0] == 1

        adapter.stop()
        await bus.publish(UtteranceFinal(text="después de stop", session_id="ses-10"))
        assert call_count[0] == 1

    asyncio.run(_test())


def test_11_dos_mensajes_consecutivos_dentro_de_la_misma_sesion() -> None:
    """Test 11: Verifica que dos mensajes consecutivos pertenecen a la misma sesión."""

    async def _test() -> None:
        bus = EventBus()
        received_sessions: list[str | None] = []

        bus.subscribe(IntentClassified, lambda e: received_sessions.append(e.session_id))

        def dummy_orchestrator(text: str) -> str:
            return f"Procesado: {text}"

        adapter = OrchestratorAdapter(orchestrator=dummy_orchestrator, event_bus=bus)
        adapter.start()

        session_shared = "ses-dialogo-persistente-999"

        # Mensaje 1
        await bus.publish(UtteranceFinal(text="Jessyca, abre Chrome", session_id=session_shared))
        # Mensaje 2
        await bus.publish(UtteranceFinal(text="¿Cómo estás?", session_id=session_shared))

        assert len(received_sessions) == 2
        assert received_sessions[0] == session_shared
        assert received_sessions[1] == session_shared

        adapter.stop()

    asyncio.run(_test())


def test_12_integracion_simulada_accion_notepad() -> None:
    """Test 12: Simulación completa hardware-free de orden de acción: 'abre bloc de notas'."""

    async def _test() -> None:
        bus = EventBus()
        sm = StateMachine()

        action_proposals: list[ActionProposed] = []
        intent_classifications: list[IntentClassified] = []
        bus.subscribe(ActionProposed, lambda e: action_proposals.append(e))
        bus.subscribe(IntentClassified, lambda e: intent_classifications.append(e))

        def orchestrator_action(text: str) -> dict[str, Any]:
            if "bloc de notas" in text:
                return {
                    "intent": "open_application",
                    "action": "apps_skill",
                    "parameters": {"app": "notepad"},
                    "type": "action",
                }
            return {"intent": "unknown", "text": "No comprendido"}

        adapter = OrchestratorAdapter(orchestrator=orchestrator_action, event_bus=bus, state_machine=sm)
        adapter.start()

        # Simular llegada de transcripción final desde STT
        await bus.publish(UtteranceFinal(text="abre bloc de notas", session_id="ses-integ-1"))

        assert len(intent_classifications) == 1
        assert intent_classifications[0].intent == "open_application"
        assert intent_classifications[0].raw_text == "abre bloc de notas"

        assert len(action_proposals) == 1
        assert action_proposals[0].action_name == "apps_skill"
        assert action_proposals[0].parameters == {"app": "notepad"}
        assert action_proposals[0].session_id == "ses-integ-1"
        assert sm.current_state.value == SessionState.EXECUTING.value

        adapter.stop()

    asyncio.run(_test())


def test_13_integracion_simulada_conversacion_gravedad() -> None:
    """Test 13: Simulación completa hardware-free de consulta conversacional: '¿qué es la gravedad?'."""

    async def _test() -> None:
        bus = EventBus()
        sm = StateMachine()

        speech_requests: list[SpeakRequested] = []
        intent_classifications: list[IntentClassified] = []
        bus.subscribe(SpeakRequested, lambda e: speech_requests.append(e))
        bus.subscribe(IntentClassified, lambda e: intent_classifications.append(e))

        def orchestrator_conversation(text: str) -> dict[str, Any]:
            if "gravedad" in text:
                return {
                    "intent": "general_knowledge",
                    "spoken_text": "La gravedad es un fenómeno natural por el cual los objetos con masa son atraídos entre sí.",
                }
            return {"intent": "unknown", "spoken_text": "No lo sé"}

        adapter = OrchestratorAdapter(orchestrator=orchestrator_conversation, event_bus=bus, state_machine=sm)
        adapter.start()

        # Simular llegada de transcripción final
        await bus.publish(UtteranceFinal(text="¿qué es la gravedad?", session_id="ses-integ-2"))

        assert len(intent_classifications) == 1
        assert intent_classifications[0].intent == "general_knowledge"

        assert len(speech_requests) == 1
        assert "La gravedad es un fenómeno natural" in speech_requests[0].text
        assert speech_requests[0].session_id == "ses-integ-2"
        assert sm.current_state.value == SessionState.RESPONDING.value

        adapter.stop()

    asyncio.run(_test())
