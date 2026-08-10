"""Pruebas del gestor de ciclo de vida ServerLifecycleManager (Subetapa 05.1)."""

from __future__ import annotations

import pytest

from server.errors import MCPServerStateError
from server.lifecycle import LifecycleState, ServerLifecycleManager


def test_lifecycle_normal_flow() -> None:
    mgr = ServerLifecycleManager()
    assert mgr.state == LifecycleState.STOPPED
    assert mgr.is_running is False
    assert mgr.uptime_seconds == 0.0

    mgr.initialize()
    assert mgr.state == LifecycleState.STOPPED

    mgr.start()
    assert mgr.state == LifecycleState.RUNNING
    assert mgr.is_running is True
    assert mgr.uptime_seconds >= 0.0

    mgr.shutdown()
    assert mgr.state == LifecycleState.STOPPED
    assert mgr.is_running is False


def test_lifecycle_repeated_calls() -> None:
    mgr = ServerLifecycleManager()

    # Inicialización repetida es segura e idempotente
    mgr.initialize()
    mgr.initialize()
    assert mgr.state == LifecycleState.STOPPED

    mgr.start()
    # Iniciar repetidamente es seguro
    mgr.start()
    assert mgr.state == LifecycleState.RUNNING

    # Detener repetidamente es seguro
    mgr.shutdown()
    mgr.shutdown()
    assert mgr.state == LifecycleState.STOPPED


def test_lifecycle_failed_state_transition() -> None:
    mgr = ServerLifecycleManager()
    mgr.set_failed("Simulated catastrophic crash")
    assert mgr.state == LifecycleState.FAILED

    with pytest.raises(MCPServerStateError):
        mgr.start()
