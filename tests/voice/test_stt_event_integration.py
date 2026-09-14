"""Pruebas unitarias completas para la integración STT + Event Bus + State Machine (Fase 67).

Cubre todos los requerimientos obligatorios:
- Test 1: STT devuelve texto válido -> UtteranceFinal publicado en Event Bus.
- Test 2: UtteranceFinal contiene el texto exacto.
- Test 3: El evento conserva el session_id de la State Machine.
- Test 4: Transcripción válida provoca: LISTENING → TRANSCRIBING → ROUTING.
- Test 5: Transcripción vacía / whitespace no genera UtteranceFinal.
- Test 6: Excepción en STT manejada, ErrorOccurred publicado, estado recuperado sin caídas.
- Test 7: Múltiples transcripciones consecutivas en la misma sesión conservan el mismo session_id.
- Test 8: Event Bus recibe y despacha correctamente a suscriptores.
- Test 9: Cero efectos secundarios sobre otros componentes.
- Soporte para transcripciones síncronas y asíncronas.
- 100% libre de dependencias de hardware real (micrófono, GPU, Ollama, TTS, Windows UI).
"""

from __future__ import annotations

import asyncio
from typing import Any

from core.bus import EventBus
from core.events import ErrorOccurred, Event, UtteranceFinal
from core.state import SessionState, StateMachine
from services.voice.stt_event_adapter import STTEventAdapter
from services.voice.stt_service import MockSTTService, TranscriptResult


def get_state(sm: StateMachine) -> SessionState:
    """Helper para evitar false type narrowing de mypy en tests."""
    return sm.current_state


# ---------------------------------------------------------------------------
# Test 1: STT devuelve texto válido -> UtteranceFinal publicado

# ---------------------------------------------------------------------------
def test_1_valid_stt_publishes_utterance_final() -> None:
    """Verifica que al recibir audio con texto válido se publique UtteranceFinal en el Event Bus."""
    bus = EventBus()
    sm = StateMachine()
    stt = MockSTTService(predefined_transcription="abre el navegador")
    adapter = STTEventAdapter(stt_service=stt, event_bus=bus, state_machine=sm)

    received_events: list[UtteranceFinal] = []
    bus.subscribe(UtteranceFinal, lambda e: received_events.append(e))

    sm.transition_to(SessionState.WAKEWORD)
    sm.transition_to(SessionState.LISTENING)

    result = adapter.process_audio(b"\x00" * 3200)

    assert result is not None
    assert len(received_events) == 1
    assert received_events[0] is result


# ---------------------------------------------------------------------------
# Test 2: UtteranceFinal contiene el texto correcto
# ---------------------------------------------------------------------------
def test_2_utterance_final_contains_correct_text() -> None:
    """Verifica que UtteranceFinal transporte el texto y confianza provistos por el STT."""
    bus = EventBus()
    sm = StateMachine()
    stt = MockSTTService(predefined_transcription="silencia los altavoces")
    adapter = STTEventAdapter(stt_service=stt, event_bus=bus, state_machine=sm)

    sm.transition_to(SessionState.WAKEWORD)
    sm.transition_to(SessionState.LISTENING)

    event = adapter.process_audio(b"\x00" * 3200)

    assert event is not None
    assert event.text == "silencia los altavoces"
    assert event.confidence == 0.95
    assert event.language == "es"


# ---------------------------------------------------------------------------
# Test 3: El evento conserva session_id
# ---------------------------------------------------------------------------
def test_3_utterance_final_preserves_session_id() -> None:
    """Verifica que el session_id provenga fielmente de la State Machine activa."""
    bus = EventBus()
    sm = StateMachine()
    expected_session_id = sm.session_id

    stt = MockSTTService(predefined_transcription="enciende la luz")
    adapter = STTEventAdapter(stt_service=stt, event_bus=bus, state_machine=sm)

    sm.transition_to(SessionState.WAKEWORD)
    sm.transition_to(SessionState.LISTENING)

    event = adapter.process_audio(b"\x00" * 3200)

    assert event is not None
    assert event.session_id == expected_session_id
    assert event.session_id == sm.session_id


# ---------------------------------------------------------------------------
# Test 4: Transición de estados: LISTENING → TRANSCRIBING → ROUTING
# ---------------------------------------------------------------------------
def test_4_state_machine_transition_flow() -> None:
    """Verifica la secuencia canónica de transiciones durante la transcripción exitosa."""
    bus = EventBus()
    sm = StateMachine()
    stt = MockSTTService(predefined_transcription="revisa la memoria")
    adapter = STTEventAdapter(stt_service=stt, event_bus=bus, state_machine=sm)

    observed_states: list[str] = []
    sm.on_enter(SessionState.TRANSCRIBING, lambda ctx: observed_states.append("TRANSCRIBING"))
    sm.on_enter(SessionState.ROUTING, lambda ctx: observed_states.append("ROUTING"))

    # Iniciar en LISTENING
    sm.transition_to(SessionState.WAKEWORD)
    sm.transition_to(SessionState.LISTENING)
    assert sm.current_state == SessionState.LISTENING

    adapter.process_audio(b"\x00" * 3200)

    # Debe haber pasado por TRANSCRIBING y quedado en ROUTING
    assert observed_states == ["TRANSCRIBING", "ROUTING"]
    assert get_state(sm) == SessionState.ROUTING
    assert sm.previous_state == SessionState.TRANSCRIBING



# ---------------------------------------------------------------------------
# Test 5: Transcripción vacía no genera evento válido
# ---------------------------------------------------------------------------
def test_5_empty_transcription_handling() -> None:
    """Verifica que audios vacíos, silencios o whitespaces no emitan UtteranceFinal ni rompan el estado."""
    bus = EventBus()
    sm = StateMachine()
    stt = MockSTTService(predefined_transcription="   ")  # Solo espacios en blanco
    adapter = STTEventAdapter(stt_service=stt, event_bus=bus, state_machine=sm)

    published_events: list[Event] = []
    bus.subscribe(Event, lambda e: published_events.append(e))

    sm.transition_to(SessionState.WAKEWORD)
    sm.transition_to(SessionState.LISTENING)

    result = adapter.process_audio(b"\x00" * 3200)

    assert result is None
    # No debe publicarse UtteranceFinal
    assert len([e for e in published_events if isinstance(e, UtteranceFinal)]) == 0

    # Estado seguro recuperado (retorna a IDLE si no hay conversación continua)
    assert sm.current_state == SessionState.IDLE


# ---------------------------------------------------------------------------
# Test 6: STT lanza excepción -> manejada y ErrorOccurred publicado
# ---------------------------------------------------------------------------
def test_6_stt_exception_handling_and_recovery() -> None:
    """Verifica que una falla de hardware/modelo en STT se aísle, reporte y recupere el estado."""
    bus = EventBus()
    sm = StateMachine()
    stt = MockSTTService()
    stt.should_fail = True
    stt.failure_reason = "Fallo de inferencia en Whisper"

    adapter = STTEventAdapter(stt_service=stt, event_bus=bus, state_machine=sm)

    errors_received: list[ErrorOccurred] = []
    bus.subscribe(ErrorOccurred, lambda e: errors_received.append(e))

    sm.transition_to(SessionState.WAKEWORD)
    sm.transition_to(SessionState.LISTENING)

    # No debe lanzar excepción hacia arriba
    result = adapter.process_audio(b"\x00" * 3200)

    assert result is None
    assert len(errors_received) == 1
    assert "Fallo de inferencia en Whisper" in errors_received[0].error_message
    assert errors_received[0].details.get("session_id") == sm.session_id

    # La StateMachine no quedó en estado TRANSCRIBING corrupto
    assert sm.current_state in (SessionState.IDLE, SessionState.LISTENING)


# ---------------------------------------------------------------------------
# Test 7: Múltiples transcripciones consecutivas conservan session_id
# ---------------------------------------------------------------------------
def test_7_consecutive_transcriptions_preserve_session_id() -> None:
    """Verifica que en una conversación de múltiples turnos se mantenga el mismo session_id."""
    bus = EventBus()
    sm = StateMachine()
    stt = MockSTTService()
    adapter = STTEventAdapter(stt_service=stt, event_bus=bus, state_machine=sm)

    initial_session_id = sm.session_id
    captured_session_ids: list[str | None] = []

    bus.subscribe(UtteranceFinal, lambda e: captured_session_ids.append(e.session_id))

    # Turno 1
    sm.transition_to(SessionState.WAKEWORD)
    sm.transition_to(SessionState.LISTENING)
    stt.set_transcription("Primer comando")
    adapter.process_audio(b"\x00" * 3200)

    # Simular avance del orquestador: ROUTING → RESPONDING → LISTENING (conversación continua)
    sm.transition_to(SessionState.RESPONDING)
    sm.renew_follow_up()
    sm.transition_to(SessionState.LISTENING)

    # Turno 2
    stt.set_transcription("Segundo comando")
    adapter.process_audio(b"\x00" * 3200)

    assert len(captured_session_ids) == 2
    assert captured_session_ids[0] == initial_session_id
    assert captured_session_ids[1] == initial_session_id
    assert sm.session_id == initial_session_id


# ---------------------------------------------------------------------------
# Test 8: Event Bus recibe correctamente los eventos
# ---------------------------------------------------------------------------
def test_8_event_bus_delivery_verification() -> None:
    """Verifica que múltiples suscriptores tipados en el Event Bus reciban el evento."""
    bus = EventBus()
    sm = StateMachine()
    stt = MockSTTService(predefined_transcription="apaga la pantalla")
    adapter = STTEventAdapter(stt_service=stt, event_bus=bus, state_machine=sm)

    subscriber_a: list[str] = []
    subscriber_b: list[str] = []

    bus.subscribe(UtteranceFinal, lambda e: subscriber_a.append(e.text))
    bus.subscribe(UtteranceFinal, lambda e: subscriber_b.append(e.text))

    sm.transition_to(SessionState.WAKEWORD)
    sm.transition_to(SessionState.LISTENING)

    adapter.process_audio(b"\x00" * 3200)

    assert subscriber_a == ["apaga la pantalla"]
    assert subscriber_b == ["apaga la pantalla"]


# ---------------------------------------------------------------------------
# Test 9: Ausencia de efectos secundarios sobre otros componentes
# ---------------------------------------------------------------------------
def test_9_zero_side_effects_on_unrelated_components() -> None:
    """Verifica que procesar audio no genere eventos espurios ni afecte suscriptores de otros eventos."""
    bus = EventBus()
    sm = StateMachine()
    stt = MockSTTService(predefined_transcription="prueba de aislamiento")
    adapter = STTEventAdapter(stt_service=stt, event_bus=bus, state_machine=sm)

    unrelated_events: list[Any] = []
    bus.subscribe(ErrorOccurred, lambda e: unrelated_events.append(e))

    sm.transition_to(SessionState.WAKEWORD)
    sm.transition_to(SessionState.LISTENING)

    adapter.process_audio(b"\x00" * 3200)

    # No debe haber saltado ningún ErrorOccurred
    assert len(unrelated_events) == 0


# ---------------------------------------------------------------------------
# Test 10: Procesamiento de transcripciones directas (process_transcript)
# ---------------------------------------------------------------------------
def test_10_process_transcript_direct() -> None:
    """Verifica la integración cuando el audio ya fue transcrito (ej. modo_voz con CalibratedVoiceCaptureEngine)."""
    bus = EventBus()
    sm = StateMachine()
    adapter = STTEventAdapter(event_bus=bus, state_machine=sm)

    received: list[str] = []
    bus.subscribe(UtteranceFinal, lambda e: received.append(e.text))

    sm.transition_to(SessionState.WAKEWORD)
    sm.transition_to(SessionState.LISTENING)

    # Caso 1: String directo
    ev = adapter.process_transcript("abre la calculadora", confidence=0.92)
    assert ev is not None
    assert ev.text == "abre la calculadora"
    assert ev.confidence == 0.92
    assert sm.current_state == SessionState.ROUTING

    # Caso 2: Objeto TranscriptResult
    sm.transition_to(SessionState.RESPONDING)
    sm.transition_to(SessionState.LISTENING)

    tr = TranscriptResult(text="cierra el bloc de notas", confidence=0.88, language="es", duration_ms=250.0)
    ev2 = adapter.process_transcript(tr)
    assert ev2 is not None
    assert ev2.text == "cierra el bloc de notas"
    assert sm.current_state == SessionState.ROUTING


# ---------------------------------------------------------------------------
# Test 11: Procesamiento asíncrono (process_audio_async)
# ---------------------------------------------------------------------------
def test_11_async_processing_support() -> None:
    """Verifica el soporte para llamadas totalmente asíncronas con corrutinas."""
    async def _run() -> None:
        bus = EventBus()
        sm = StateMachine()
        stt = MockSTTService(predefined_transcription="mensaje asíncrono")
        adapter = STTEventAdapter(stt_service=stt, event_bus=bus, state_machine=sm)

        events: list[str] = []

        async def async_subscriber(e: UtteranceFinal) -> None:
            await asyncio.sleep(0.01)
            events.append(e.text)

        bus.subscribe(UtteranceFinal, async_subscriber)

        sm.transition_to(SessionState.WAKEWORD)
        sm.transition_to(SessionState.LISTENING)

        ev = await adapter.process_audio_async(b"\x00" * 3200)
        assert ev is not None
        assert events == ["mensaje asíncrono"]
        assert sm.current_state == SessionState.ROUTING

    asyncio.run(_run())
