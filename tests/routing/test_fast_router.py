"""Tests unitarios, de integración y benchmark para el Fast Router de JESSYCA (Fase 69).

Valida:
1. Comandos de aplicaciones (abre Chrome, abre el bloc de notas).
2. Comandos de control de hardware (sube el volumen, baja el volumen, toma una captura).
3. Conversación normal (¿Cómo estás?, Buenos días).
4. Preguntas conceptuales y LLM (¿Qué es la gravedad?, Explícame física básica).
5. Prevención estricta de falsos positivos (¿Qué significa la palabra abrir?, ¿Qué es un navegador?).
6. Casos ambiguos (abre eso, cierra) sin ejecución directa.
7. Comandos destructivos (apaga la computadora, elimina archivo) con confirmación requerida.
8. Integración con Event Bus y State Machine.
9. Benchmark de latencia de clasificación determinista local.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

from core.bus import EventBus
from core.events.base import (
    ActionProposed,
    ClarificationRequested,
    IntentClassified,
    SpeakRequested,
    UtteranceFinal,
)
from core.orchestrator_adapter import OrchestratorAdapter
from core.routing import FastRouter, RouteCategory
from core.state.machine import StateMachine
from core.state.states import SessionState

# ── 1. TESTS DE COMANDOS (COMMAND) ───────────────────────────────────────────

def test_01_command_abre_chrome() -> None:
    """Verifica que 'abre Chrome' se clasifica como COMMAND / open_application / Chrome."""
    router = FastRouter()
    decision = router.route("abre Chrome")

    assert decision.category == RouteCategory.COMMAND
    assert decision.intent == "open_application"
    assert decision.target_skill == "windows.apps"
    assert decision.parameters.get("app_name") == "chrome"
    assert decision.confidence >= 0.85
    assert decision.requires_confirmation is False


def test_02_command_abre_bloc_de_notas() -> None:
    """Verifica que 'abre el bloc de notas' se clasifica como COMMAND / open_application / Notepad."""
    router = FastRouter()
    decision = router.route("abre el bloc de notas")

    assert decision.category == RouteCategory.COMMAND
    assert decision.intent == "open_application"
    assert decision.target_skill == "windows.apps"
    assert decision.parameters.get("app_name") == "notepad"
    assert decision.confidence >= 0.85


def test_03_command_sube_el_volumen() -> None:
    """Verifica que 'sube el volumen' se clasifica como COMMAND / volume_up / windows.audio."""
    router = FastRouter()
    decision = router.route("sube el volumen")

    assert decision.category == RouteCategory.COMMAND
    assert decision.intent == "volume_up"
    assert decision.target_skill == "windows.audio"
    assert decision.confidence >= 0.90


def test_04_command_baja_el_volumen() -> None:
    """Verifica que 'baja el volumen' se clasifica como COMMAND / volume_down / windows.audio."""
    router = FastRouter()
    decision = router.route("baja el volumen")

    assert decision.category == RouteCategory.COMMAND
    assert decision.intent == "volume_down"
    assert decision.target_skill == "windows.audio"
    assert decision.confidence >= 0.90


def test_05_command_toma_una_captura() -> None:
    """Verifica que 'toma una captura' se clasifica como COMMAND / screenshot / windows.screenshot."""
    router = FastRouter()
    decision = router.route("toma una captura")

    assert decision.category == RouteCategory.COMMAND
    assert decision.intent == "screenshot"
    assert decision.target_skill == "windows.screenshot"
    assert decision.confidence >= 0.95


# ── 2. TESTS DE CONVERSACIÓN (CONVERSATION) ───────────────────────────────────

def test_06_conversation_como_estas() -> None:
    """Verifica que '¿Cómo estás?' se clasifica como CONVERSATION con respuesta local."""
    router = FastRouter()
    decision = router.route("¿Cómo estás?")

    assert decision.category == RouteCategory.CONVERSATION
    assert decision.confidence >= 0.90
    assert decision.suggested_response is not None
    assert len(decision.suggested_response) > 5


def test_07_conversation_buenos_dias() -> None:
    """Verifica que 'Buenos días' se clasifica como CONVERSATION."""
    router = FastRouter()
    decision = router.route("Buenos días")

    assert decision.category == RouteCategory.CONVERSATION
    assert decision.intent == "greeting"
    assert decision.suggested_response is not None


# ── 3. TESTS DE PREGUNTAS / LLM (QUESTION) ───────────────────────────────────

def test_08_question_que_es_la_gravedad() -> None:
    """Verifica que '¿Qué es la gravedad?' se clasifica como QUESTION / LLM."""
    router = FastRouter()
    decision = router.route("¿Qué es la gravedad?")

    assert decision.category == RouteCategory.QUESTION
    assert decision.intent == "knowledge_query"
    assert decision.confidence >= 0.90


def test_09_question_explicame_fisica_basica() -> None:
    """Verifica que 'Explícame física básica' se clasifica como QUESTION / LLM."""
    router = FastRouter()
    decision = router.route("Explícame física básica")

    assert decision.category == RouteCategory.QUESTION
    assert decision.confidence >= 0.90


# ── 4. TESTS DE COMPLEJIDAD (COMPLEX) ─────────────────────────────────────────

def test_10_complex_request() -> None:
    """Verifica que una solicitud extensa y compleja se clasifica como COMPLEX."""
    router = FastRouter()
    prompt = (
        "Genera un script en Python que descargue los datos de clima, analice la variación mensual, "
        "calcule la media móvil y genere un gráfico comparativo guardándolo en disco."
    )
    decision = router.route(prompt)

    assert decision.category == RouteCategory.COMPLEX
    assert decision.confidence >= 0.85


# ── 5. PREVENCIÓN DE FALSOS POSITIVOS ────────────────────────────────────────

def test_11_false_positive_que_significa_abrir() -> None:
    """Verifica que '¿Qué significa la palabra abrir?' NO se clasifica como open_application."""
    router = FastRouter()
    decision = router.route("¿Qué significa la palabra abrir?")

    assert decision.category != RouteCategory.COMMAND
    assert decision.intent != "open_application"
    assert decision.category == RouteCategory.QUESTION


def test_12_false_positive_que_es_un_navegador() -> None:
    """Verifica que '¿Qué es un navegador?' NO se clasifica como open_browser ni open_application."""
    router = FastRouter()
    decision = router.route("¿Qué es un navegador?")

    assert decision.category != RouteCategory.COMMAND
    assert decision.intent != "open_application"
    assert decision.category == RouteCategory.QUESTION


# ── 6. CASOS AMBIGUOS (AMBIGUOUS) ─────────────────────────────────────────────

def test_13_ambiguous_abre_eso() -> None:
    """Verifica que 'abre eso' se clasifica como AMBIGUOUS y no ejecuta directamente ninguna app."""
    router = FastRouter()
    decision = router.route("abre eso")

    assert decision.category == RouteCategory.AMBIGUOUS
    assert decision.suggested_response is not None
    assert "¿Qué aplicación" in decision.suggested_response


def test_14_ambiguous_cierra_sin_target() -> None:
    """Verifica que 'cierra' sin target se clasifica como AMBIGUOUS y no ejecuta acciones a ciegas."""
    router = FastRouter()
    decision = router.route("cierra")

    assert decision.category == RouteCategory.AMBIGUOUS
    assert decision.suggested_response is not None


# ── 7. COMANDOS DESTRUCTIVOS Y SEGURIDAD (SECURITY) ──────────────────────────

def test_15_destructive_apaga_la_computadora() -> None:
    """Verifica que 'apaga la computadora' activa requires_confirmation = True."""
    router = FastRouter()
    decision = router.route("apaga la computadora")

    assert decision.category == RouteCategory.COMMAND
    assert decision.intent == "system_shutdown"
    assert decision.requires_confirmation is True


def test_16_destructive_elimina_archivo() -> None:
    """Verifica que 'elimina el archivo temp.txt' activa requires_confirmation = True."""
    router = FastRouter()
    decision = router.route("elimina el archivo temp.txt")

    assert decision.category == RouteCategory.COMMAND
    assert decision.intent == "delete_file"
    assert decision.requires_confirmation is True
    assert "temp.txt" in str(decision.parameters.get("path"))


# ── 8. INTEGRACIÓN CON EVENT BUS Y STATE MACHINE ──────────────────────────────

def test_17_event_bus_integration_utterance_to_intent_classified() -> None:
    """Test Event Bus: UtteranceFinal -> Fast Router -> IntentClassified con un solo evento y datos íntegros."""

    async def _test() -> None:
        bus = EventBus()
        classified_events: list[IntentClassified] = []
        action_events: list[ActionProposed] = []

        bus.subscribe(IntentClassified, lambda e: classified_events.append(e))
        bus.subscribe(ActionProposed, lambda e: action_events.append(e))

        router = FastRouter(event_bus=bus)
        router.start()

        test_session = "session-fast-bus-42"
        await bus.publish(UtteranceFinal(text="abre Chrome", session_id=test_session))

        # Verificar exactamente 1 evento de clasificación
        assert len(classified_events) == 1
        assert classified_events[0].intent == "open_application"
        assert classified_events[0].raw_text == "abre Chrome"
        assert classified_events[0].session_id == test_session
        assert classified_events[0].confidence >= 0.85

        # Verificar evento de acción propuesto
        assert len(action_events) == 1
        assert action_events[0].action_name == "windows.apps"
        assert action_events[0].parameters.get("app_name") == "chrome"
        assert action_events[0].session_id == test_session

        router.stop()

    asyncio.run(_test())


def test_18_state_machine_transitions_command_and_conversation() -> None:
    """Verifica que la State Machine transiciona a EXECUTING para COMMAND y a RESPONDING para CONVERSATION."""

    async def _test() -> None:
        bus = EventBus()
        sm = StateMachine()

        # Preparar State Machine en ROUTING
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        router = FastRouter(event_bus=bus, state_machine=sm)
        router.start()

        spoken_events: list[SpeakRequested] = []
        bus.subscribe(SpeakRequested, lambda e: spoken_events.append(e))

        # 1. Comando -> transiciona a EXECUTING
        await bus.publish(UtteranceFinal(text="sube el volumen", session_id="ses-sm-1"))
        assert sm.current_state.value == SessionState.EXECUTING.value

        # Reset y regreso a ROUTING para el segundo mensaje
        sm.transition_to(SessionState.RESPONDING)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        # 2. Conversación -> transiciona a RESPONDING y emite SpeakRequested
        await bus.publish(UtteranceFinal(text="¿Cómo estás?", session_id="ses-sm-1"))
        assert sm.current_state.value == SessionState.RESPONDING.value
        assert len(spoken_events) == 1
        assert "¡Hola! Estoy muy bien" in spoken_events[0].text

        router.stop()

    asyncio.run(_test())


def test_19_state_machine_ambiguous_transitions_to_clarifying() -> None:
    """Verifica que un comando ambiguo emite ClarificationRequested y transiciona a CLARIFYING."""

    async def _test() -> None:
        bus = EventBus()
        sm = StateMachine()
        clarif_events: list[ClarificationRequested] = []
        bus.subscribe(ClarificationRequested, lambda e: clarif_events.append(e))

        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        router = FastRouter(event_bus=bus, state_machine=sm)
        router.start()

        await bus.publish(UtteranceFinal(text="abre eso", session_id="ses-clarif-1"))

        assert len(clarif_events) == 1
        assert clarif_events[0].original_text == "abre eso"
        assert sm.current_state.value == SessionState.CLARIFYING.value

        router.stop()

    asyncio.run(_test())


# ── 9. BENCHMARK SIMPLE DE RENDIMIENTO LOCAL ──────────────────────────────────

def test_20_benchmark_fast_router_latency() -> None:
    """Mide que la clasificación local es ultrarrápida (< 5 ms) y no invoca red ni LLM."""
    router = FastRouter()

    # Warm-up
    router.route("abre Chrome")

    # Medición de 100 clasificaciones de comando
    t0 = time.perf_counter()
    iterations = 100
    for _ in range(iterations):
        res = router.route("abre Chrome")
        assert res.category == RouteCategory.COMMAND

    total_time_ms = (time.perf_counter() - t0) * 1000.0
    avg_latency_ms = total_time_ms / iterations

    # Debe ser inferior a 1 ms en entorno local moderno
    assert avg_latency_ms < 5.0, f"Latencia promedio demasiado alta: {avg_latency_ms:.3f} ms"

    # Verificación de que preguntas conceptuales se dirigen a QUESTION sin costo LLM previo
    t_q0 = time.perf_counter()
    q_res = router.route("Explícame la relatividad de Einstein")
    t_q_ms = (time.perf_counter() - t_q0) * 1000.0

    assert q_res.category == RouteCategory.QUESTION
    assert t_q_ms < 5.0, f"Latencia de enrutamiento a LLM demasiado alta: {t_q_ms:.3f} ms"


def test_21_orchestrator_adapter_with_fast_router_integration() -> None:
    """Verifica la integración completa: FastRouter resuelve comandos locales sin llamar al Orchestrator/LLM."""

    async def _test() -> None:
        bus = EventBus()
        sm = StateMachine()
        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        mock_orchestrator = MagicMock()
        adapter = OrchestratorAdapter(
            orchestrator=mock_orchestrator,
            event_bus=bus,
            state_machine=sm,
            fast_router=FastRouter(),
        )
        adapter.start()

        actions: list[ActionProposed] = []
        bus.subscribe(ActionProposed, lambda e: actions.append(e))

        # 1. Enviar comando local: FastRouter debe resolverlo sin llamar a mock_orchestrator
        await bus.publish(UtteranceFinal(text="abre Chrome", session_id="ses-adapter-fast"))

        assert len(actions) == 1
        assert actions[0].action_name == "windows.apps"
        assert actions[0].parameters.get("app_name") == "chrome"
        assert sm.current_state.value == SessionState.EXECUTING.value
        # El orquestador / LLM NO debió haber sido invocado
        assert mock_orchestrator.interact.call_count == 0
        assert mock_orchestrator.call_count == 0

        # Reset a ROUTING
        sm.transition_to(SessionState.RESPONDING)
        sm.transition_to(SessionState.LISTENING)
        sm.transition_to(SessionState.TRANSCRIBING)
        sm.transition_to(SessionState.ROUTING)

        # 2. Enviar pregunta: FastRouter la delega al Orchestrator
        mock_orchestrator.interact.return_value = MagicMock(
            intent="knowledge_query",
            requires_clarification=False,
            requires_confirmation=False,
            selected_skill="auto",
            spoken_text="La gravedad es una fuerza fundamental.",
            response_text="La gravedad es una fuerza fundamental.",
        )
        await bus.publish(UtteranceFinal(text="¿Qué es la gravedad?", session_id="ses-adapter-fast"))

        # Ahora el Orchestrator SÍ debió haber sido invocado
        assert mock_orchestrator.interact.call_count == 1

        adapter.stop()

    asyncio.run(_test())

