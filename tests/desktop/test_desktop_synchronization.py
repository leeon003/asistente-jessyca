"""Pruebas dedicadas para la capa de sincronización explícita DesktopSynchronizer (Subetapa 08.4)."""

from __future__ import annotations

import threading

from core.desktop_synchronization import (
    DesktopSynchronizer,
    FakeClock,
    SynchronizationStatus,
)
from core.emergency_stop import CancellationToken, get_emergency_stop_manager
from tools.desktop.ui_backend import FakeUIInspectionBackend


def test_sync_immediate_condition_success() -> None:
    clock = FakeClock()
    synchronizer = DesktopSynchronizer(clock=clock)

    res = synchronizer.wait_until(condition=lambda: True, timeout_seconds=2.0)
    assert res.success is True
    assert res.status == SynchronizationStatus.SUCCESS
    assert res.poll_count == 1


def test_sync_condition_after_multiple_polls() -> None:
    clock = FakeClock()
    synchronizer = DesktopSynchronizer(clock=clock)

    polls = 0

    def multi_poll_condition() -> bool:
        nonlocal polls
        polls += 1
        return polls >= 3

    res = synchronizer.wait_until(condition=multi_poll_condition, timeout_seconds=5.0, poll_interval_seconds=0.5)
    assert res.success is True
    assert res.status == SynchronizationStatus.SUCCESS
    assert res.poll_count == 3
    assert len(clock.sleep_calls) == 2  # 2 retardos entre los 3 polls


def test_sync_timeout() -> None:
    clock = FakeClock()
    synchronizer = DesktopSynchronizer(clock=clock)

    # Condición que NUNCA se cumple
    res = synchronizer.wait_until(condition=lambda: False, timeout_seconds=1.0, poll_interval_seconds=0.2)
    assert res.success is False
    assert res.status == SynchronizationStatus.TIMEOUT
    assert res.poll_count >= 5


def test_sync_cancellation() -> None:
    clock = FakeClock()
    synchronizer = DesktopSynchronizer(clock=clock)

    event = threading.Event()
    token = CancellationToken(event=event)

    # Cancelar antes de iniciar
    event.set()

    res = synchronizer.wait_until(condition=lambda: False, timeout_seconds=5.0, cancellation_token=token)
    assert res.success is False
    assert res.status == SynchronizationStatus.CANCELLED


def test_sync_emergency_stop() -> None:
    clock = FakeClock()
    em = get_emergency_stop_manager()
    synchronizer = DesktopSynchronizer(emergency_stop_manager=em, clock=clock)

    em.trigger_stop("Emergency stop test for Synchronizer", source="test")
    try:
        res = synchronizer.wait_until(condition=lambda: True, timeout_seconds=5.0)
        assert res.success is False
        assert res.status == SynchronizationStatus.ABORTED_BY_EMERGENCY_STOP
    finally:
        em.reset("cleanup")


def test_sync_provider_exception() -> None:
    clock = FakeClock()
    synchronizer = DesktopSynchronizer(clock=clock)

    def faulty_condition() -> bool:
        raise ValueError("Simulated UI Provider Error")

    res = synchronizer.wait_until(condition=faulty_condition, timeout_seconds=2.0)
    assert res.success is False
    assert res.status == SynchronizationStatus.PROVIDER_ERROR
    assert "Simulated UI Provider Error" in res.reason


def test_sync_wait_for_window_and_element() -> None:
    clock = FakeClock()
    backend = FakeUIInspectionBackend()
    synchronizer = DesktopSynchronizer(clock=clock)

    # Esperar ventana activa sintética "Jessyca MCP Application Window"
    res_win = synchronizer.wait_for_window("Jessyca MCP Application Window", timeout_seconds=2.0, ui_backend=backend)
    assert res_win.success is True
    assert res_win.status == SynchronizationStatus.SUCCESS

    # Esperar elemento sintético "BtnClose"
    res_elem = synchronizer.wait_for_element(
        window_title="Jessyca",
        control_type="Button",
        element_name="Close",
        timeout_seconds=2.0,
        ui_backend=backend,
    )
    assert res_elem.success is True
    assert res_elem.status == SynchronizationStatus.SUCCESS
