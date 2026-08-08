"""Pruebas unitarias completas del Event Bus interno."""

from __future__ import annotations

import asyncio

from core.event_bus import Event, EventBus, EventPriority, get_event_bus


def test_subscribe_and_publish_sync() -> None:
    bus = EventBus()
    received_events = []

    def handler(event: Event) -> None:
        received_events.append(event)

    sub_id = bus.subscribe("test:event", handler)
    assert sub_id is not None
    assert bus.get_listener_count("test:event") == 1

    bus.publish("test:event", {"key": "val1"})
    assert len(received_events) == 1
    assert received_events[0].name == "test:event"
    assert received_events[0].payload == {"key": "val1"}


def test_priority_execution_order() -> None:
    bus = EventBus()
    order = []

    def low_handler(event: Event) -> None:
        order.append("LOW")

    def normal_handler(event: Event) -> None:
        order.append("NORMAL")

    def highest_handler(event: Event) -> None:
        order.append("HIGHEST")

    # Registrar en orden arbitrario
    bus.subscribe("order:test", low_handler, priority=EventPriority.LOW)
    bus.subscribe("order:test", normal_handler, priority=EventPriority.NORMAL)
    bus.subscribe("order:test", highest_handler, priority=EventPriority.HIGHEST)

    bus.publish("order:test")
    # El orden DEBE ser HIGHEST -> NORMAL -> LOW
    assert order == ["HIGHEST", "NORMAL", "LOW"]


def test_unsubscribe_by_id_and_handler() -> None:
    bus = EventBus()
    records = []

    def h1(event: Event) -> None:
        records.append("h1")

    def h2(event: Event) -> None:
        records.append("h2")

    sub1_id = bus.subscribe("unsub:test", h1)
    _sub2_id = bus.subscribe("unsub:test", h2)

    assert bus.get_listener_count("unsub:test") == 2

    # Des-suscribir h1 por ID
    assert bus.unsubscribe(sub1_id) is True
    assert bus.get_listener_count("unsub:test") == 1

    bus.publish("unsub:test")
    assert records == ["h2"]

    # Des-suscribir h2 por handler
    assert bus.unsubscribe(h2) is True
    assert bus.get_listener_count("unsub:test") == 0


def test_fault_tolerance_failing_listener() -> None:
    """Verifica que un listener que lanza una excepción no impida la ejecución de los demás listeners."""
    bus = EventBus()
    execution = []

    def failing_listener(event: Event) -> None:
        execution.append("failing")
        raise RuntimeError("Fallo forzado intencional en listener")

    def successful_listener(event: Event) -> None:
        execution.append("success")

    # failing con mayor prioridad para ejecutarse primero
    bus.subscribe("fault:test", failing_listener, priority=EventPriority.HIGHEST)
    bus.subscribe("fault:test", successful_listener, priority=EventPriority.LOW)

    # Publicar no debe lanzar excepción
    bus.publish("fault:test")

    # Ambos listeners deben haber sido llamados
    assert execution == ["failing", "success"]


def test_async_publish_and_listeners() -> None:
    async def _run() -> None:
        bus = EventBus()
        logs = []

        async def async_handler(event: Event) -> None:
            await asyncio.sleep(0.01)
            logs.append(f"async_{event.payload.get('idx')}")

        def sync_handler(event: Event) -> None:
            logs.append(f"sync_{event.payload.get('idx')}")

        bus.subscribe("async:event", async_handler, priority=EventPriority.HIGHEST)
        bus.subscribe("async:event", sync_handler, priority=EventPriority.LOW)

        await bus.publish_async("async:event", {"idx": 1})
        assert logs == ["async_1", "sync_1"]

    asyncio.run(_run())


def test_global_singleton_event_bus() -> None:
    b1 = get_event_bus()
    b2 = get_event_bus()
    assert b1 is b2
