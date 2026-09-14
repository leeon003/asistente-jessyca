"""Pruebas unitarias completas para el Event Bus tipado de JESSYCA 4.0 (Fase 65).

Cubre todos los requerimientos obligatorios:
- Publicación y suscripción tipada
- Múltiples suscriptores
- Diferentes tipos de eventos
- Handlers asíncronos (async def)
- Cancelación de suscripción (unsubscribe)
- Aislamiento de excepciones en suscriptores (fault tolerance)
- Preservación íntegra de metadatos y datos de eventos
- Operación autónoma sin hardware real (sin micrófono, GPU, TTS, Ollama ni Windows UI)
- Despacho polimórfico por herencia de eventos
- Demostración local: UtteranceFinal(text="abre Chrome", confidence=0.94)
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime

import pytest

from core.bus import EventBus, get_event_bus, reset_event_bus
from core.events import (
    ActionExecuted,
    ActionProposed,
    AudioCaptured,
    ClarificationRequested,
    ErrorOccurred,
    Event,
    IntentClassified,
    SpeakRequested,
    UserInterrupted,
    UtteranceFinal,
    VerificationResult,
    WakeWordDetected,
)


@pytest.fixture(autouse=True)
def clean_bus() -> Generator[None, None, None]:
    """Asegura un estado limpio del Singleton global antes y después de cada test."""
    reset_event_bus()
    yield
    reset_event_bus()




# ---------------------------------------------------------------------------
# Test 1: Publicar un evento y comprobar que un subscriber lo recibe
# ---------------------------------------------------------------------------
def test_1_publish_and_subscriber_receives() -> None:
    """Verifica que al publicar un evento, el subscriber registrado lo recibe correctamente."""
    bus = EventBus()
    received: list[UtteranceFinal] = []

    def handler(event: UtteranceFinal) -> None:
        received.append(event)

    bus.subscribe(UtteranceFinal, handler)
    assert bus.get_subscriber_count(UtteranceFinal) == 1

    event = UtteranceFinal(text="abre Chrome", confidence=0.94)
    bus.publish(event)

    assert len(received) == 1
    assert received[0] is event
    assert received[0].text == "abre Chrome"
    assert received[0].confidence == 0.94


# ---------------------------------------------------------------------------
# Test 2: Comprobar múltiples subscribers para el mismo evento
# ---------------------------------------------------------------------------
def test_2_multiple_subscribers_for_same_event() -> None:
    """Verifica que múltiples suscriptores para el mismo evento son todos notificados."""
    bus = EventBus()
    tracker_a: list[str] = []
    tracker_b: list[str] = []
    tracker_c: list[str] = []

    def subscriber_a(event: WakeWordDetected) -> None:
        tracker_a.append(event.wake_word)

    def subscriber_b(event: WakeWordDetected) -> None:
        tracker_b.append(event.wake_word)

    def subscriber_c(event: WakeWordDetected) -> None:
        tracker_c.append(event.wake_word)

    bus.subscribe(WakeWordDetected, subscriber_a)
    bus.subscribe(WakeWordDetected, subscriber_b)
    bus.subscribe(WakeWordDetected, subscriber_c)

    assert bus.get_subscriber_count(WakeWordDetected) == 3

    event = WakeWordDetected(wake_word="jessyca", confidence=0.98)
    bus.publish(event)

    assert tracker_a == ["jessyca"]
    assert tracker_b == ["jessyca"]
    assert tracker_c == ["jessyca"]


# ---------------------------------------------------------------------------
# Test 3: Comprobar diferentes tipos de eventos
# ---------------------------------------------------------------------------
def test_3_different_event_types_isolation() -> None:
    """Verifica que los suscriptores solo reciban los tipos de eventos a los que se suscribieron."""
    bus = EventBus()
    utterances: list[str] = []
    actions: list[str] = []
    speaks: list[str] = []

    bus.subscribe(UtteranceFinal, lambda e: utterances.append(e.text))
    bus.subscribe(ActionExecuted, lambda e: actions.append(e.action_name))
    bus.subscribe(SpeakRequested, lambda e: speaks.append(e.text))

    # Publicar cada evento
    bus.publish(UtteranceFinal(text="hola"))
    bus.publish(ActionExecuted(action_name="open_browser", success=True))
    bus.publish(SpeakRequested(text="Abriendo navegador"))

    assert utterances == ["hola"]
    assert actions == ["open_browser"]
    assert speaks == ["Abriendo navegador"]


# ---------------------------------------------------------------------------
# Test 4: Comprobar handlers async
# ---------------------------------------------------------------------------
def test_4_async_handlers_execution() -> None:
    """Verifica que los handlers asíncronos (async def) sean ejecutados y esperados adecuadamente."""
    async def _run() -> None:
        bus = EventBus()
        executed_async: list[str] = []

        async def async_handler_1(event: ActionProposed) -> None:
            await asyncio.sleep(0.01)
            executed_async.append(f"async1:{event.action_name}")

        async def async_handler_2(event: ActionProposed) -> None:
            await asyncio.sleep(0.01)
            executed_async.append(f"async2:{event.action_name}")

        def sync_handler(event: ActionProposed) -> None:
            executed_async.append(f"sync:{event.action_name}")

        bus.subscribe(ActionProposed, async_handler_1)
        bus.subscribe(ActionProposed, sync_handler)
        bus.subscribe(ActionProposed, async_handler_2)

        event = ActionProposed(action_name="search_files", parameters={"pattern": "*.py"})
        await bus.publish(event)

        assert "sync:search_files" in executed_async
        assert "async1:search_files" in executed_async
        assert "async2:search_files" in executed_async
        assert len(executed_async) == 3

    asyncio.run(_run())



# ---------------------------------------------------------------------------
# Test 5: Comprobar unsubscribe
# ---------------------------------------------------------------------------
def test_5_unsubscribe_behavior() -> None:
    """Verifica que des-suscribir un handler impida que reciba eventos posteriores."""
    bus = EventBus()
    log: list[str] = []

    def handler_1(event: UserInterrupted) -> None:
        log.append("h1")

    def handler_2(event: UserInterrupted) -> None:
        log.append("h2")

    bus.subscribe(UserInterrupted, handler_1)
    bus.subscribe(UserInterrupted, handler_2)
    assert bus.get_subscriber_count(UserInterrupted) == 2

    bus.publish(UserInterrupted(reason="barge_in"))
    assert log == ["h1", "h2"]

    # Des-suscribir handler_1
    removed = bus.unsubscribe(UserInterrupted, handler_1)
    assert removed is True
    assert bus.get_subscriber_count(UserInterrupted) == 1

    # Des-suscribir de nuevo debe devolver False
    assert bus.unsubscribe(UserInterrupted, handler_1) is False

    # Publicar de nuevo: solo handler_2 debe recibirlo
    bus.publish(UserInterrupted(reason="timeout"))
    assert log == ["h1", "h2", "h2"]


# ---------------------------------------------------------------------------
# Test 6: Comprobar que un handler que lanza excepción no destruye el EventBus
# ---------------------------------------------------------------------------
def test_6_handler_exception_isolation() -> None:
    """Verifica la tolerancia a fallos: una excepción en un subscriber no afecta a los demás ni destruye el bus."""
    bus = EventBus()
    execution_order: list[str] = []

    def bad_handler(event: ErrorOccurred) -> None:
        execution_order.append("bad")
        raise RuntimeError("Fallo simulado en suscriptor")

    def good_handler_1(event: ErrorOccurred) -> None:
        execution_order.append("good1")

    def good_handler_2(event: ErrorOccurred) -> None:
        execution_order.append("good2")

    bus.subscribe(ErrorOccurred, good_handler_1)
    bus.subscribe(ErrorOccurred, bad_handler)
    bus.subscribe(ErrorOccurred, good_handler_2)

    # La publicación no debe propagar la excepción
    event = ErrorOccurred(error_message="Test error", error_type="SimulatedError")
    bus.publish(event)

    # Todos los suscriptores deben haber sido invocados a pesar del fallo
    assert execution_order == ["good1", "bad", "good2"]

    # El bus debe seguir completamente funcional para futuros eventos
    next_received: list[str] = []
    bus.subscribe(UtteranceFinal, lambda e: next_received.append(e.text))
    bus.publish(UtteranceFinal(text="siguiente comando"))
    assert next_received == ["siguiente comando"]


# ---------------------------------------------------------------------------
# Test 7: Comprobar que el evento conserva correctamente sus datos
# ---------------------------------------------------------------------------
def test_7_event_data_integrity() -> None:
    """Verifica que todos los campos del evento, UUIDs, timestamps y datos específicos se preservan."""
    bus = EventBus()
    captured_events: list[Event] = []

    bus.subscribe(VerificationResult, lambda e: captured_events.append(e))

    before = datetime.now(UTC)
    details_payload = {"risk_score": 0.1, "verified_by": "security_kernel"}
    ver_event = VerificationResult(
        action_name="launch_app",
        verified=True,
        status="PASSED",
        details=details_payload,
    )
    after = datetime.now(UTC)

    bus.publish(ver_event)

    assert len(captured_events) == 1
    event = captured_events[0]
    assert isinstance(event, VerificationResult)
    assert event.action_name == "launch_app"
    assert event.verified is True
    assert event.status == "PASSED"
    assert event.details == details_payload
    assert event.event_type == "VerificationResult"

    # Verificar identificador único universal
    assert event.event_id is not None
    assert len(event.event_id) >= 32

    # Verificar timestamp UTC
    assert before <= event.timestamp <= after


# ---------------------------------------------------------------------------
# Test 8: Comprobar que el EventBus funciona sin hardware real
# ---------------------------------------------------------------------------
def test_8_hardware_free_execution() -> None:
    """Verifica que todos los 11 eventos iniciales funcionan perfectamente sin micrófono, GPU, TTS ni Windows."""
    bus = EventBus()
    counts: dict[str, int] = {}

    all_events: list[Event] = [
        WakeWordDetected(wake_word="jessyca", confidence=0.99),
        AudioCaptured(audio_data=b"\x00\x01\x02\x03", sample_rate=16000, channels=1, duration_ms=100),
        UtteranceFinal(text="silencio", confidence=0.95),
        IntentClassified(intent="system:mute", confidence=0.9),
        ActionProposed(action_name="mute_speakers"),
        ActionExecuted(action_name="mute_speakers", success=True),
        VerificationResult(action_name="mute_speakers", verified=True),
        SpeakRequested(text="Silenciando altavoces"),
        UserInterrupted(reason="user_voice"),
        ClarificationRequested(question="¿Desea apagar o silenciar?"),
        ErrorOccurred(error_message="Device busy", error_type="AudioDeviceError"),
    ]

    for ev in all_events:
        ev_cls = type(ev)
        bus.subscribe(ev_cls, lambda e: counts.update({e.event_type: counts.get(e.event_type, 0) + 1}))

    for ev in all_events:
        bus.publish(ev)

    assert len(counts) == 11
    for ev in all_events:
        assert counts[ev.event_type] == 1


# ---------------------------------------------------------------------------
# Test 9: Despacho polimórfico (Suscripción a Event base recibe todo)
# ---------------------------------------------------------------------------
def test_9_polymorphic_dispatch() -> None:
    """Verifica que un suscriptor registrado en la clase base Event recibe cualquier evento derivado."""
    bus = EventBus()
    all_seen: list[str] = []

    def global_audit_subscriber(event: Event) -> None:
        all_seen.append(event.event_type)

    bus.subscribe(Event, global_audit_subscriber)

    bus.publish(UtteranceFinal(text="test 1"))
    bus.publish(ActionProposed(action_name="test 2"))
    bus.publish(ClarificationRequested(question="test 3"))

    assert all_seen == ["UtteranceFinal", "ActionProposed", "ClarificationRequested"]


# ---------------------------------------------------------------------------
# Test 10: Demostración local requerida por la Fase 65
# ---------------------------------------------------------------------------
def test_10_local_demonstration() -> None:
    """Demostración local requerida:

    Evento publicado:
        UtteranceFinal(text="abre Chrome", confidence=0.94)
    Subscriber recibe:
        "abre Chrome"
    """
    bus = EventBus()
    received_text: str | None = None

    def on_utterance(event: UtteranceFinal) -> None:
        nonlocal received_text
        received_text = event.text

    bus.subscribe(UtteranceFinal, on_utterance)

    bus.publish(UtteranceFinal(text="abre Chrome", confidence=0.94))

    assert received_text == "abre Chrome"


# ---------------------------------------------------------------------------
# Test 11: Validaciones de tipos y Singleton global
# ---------------------------------------------------------------------------
def test_11_type_validations_and_singleton() -> None:
    """Verifica validaciones de argumentos inválidos y el singleton global."""
    bus = EventBus()

    # event_type debe ser subclase de Event
    with pytest.raises(TypeError, match="subclase de Event"):
        bus.subscribe(str, lambda e: None)  # type: ignore[type-var]



    # handler debe ser invocable
    with pytest.raises(TypeError, match="invocable"):
        bus.subscribe(UtteranceFinal, "no_es_callable")  # type: ignore[arg-type]

    # publish debe recibir una instancia de Event
    with pytest.raises(TypeError, match="instancia de Event"):
        bus.publish("evento_no_valido")  # type: ignore[arg-type]

    # Singleton global
    b1 = get_event_bus()
    b2 = get_event_bus()
    assert b1 is b2

    reset_event_bus()
    b3 = get_event_bus()
    assert b3 is not b1
