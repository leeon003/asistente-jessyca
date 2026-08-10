"""Pruebas dedicadas para Application Control Boundary y Single-Instance Policy (Subetapa 11.1)."""

from __future__ import annotations

import pytest

from core.application_boundary import ApplicationControlBoundary
from core.application_models import (
    ApplicationNotFoundError,
    ApplicationState,
)
from core.application_session_manager import ApplicationSessionManager, FakeApplicationAdapter
from core.emergency_stop import EmergencyStopTriggeredError, get_emergency_stop_manager


def test_launch_new_instance() -> None:
    adapter = FakeApplicationAdapter()
    mgr = ApplicationSessionManager(adapter=adapter, single_instance_enforced=True)

    session = mgr.launch_app("bloc de notas")
    assert session is not None
    assert session.app_id == "notepad"
    assert session.state == ApplicationState.RUNNING
    assert len(adapter.launch_history) == 1


def test_existing_instance_reuse_and_focus() -> None:
    adapter = FakeApplicationAdapter()
    mgr = ApplicationSessionManager(adapter=adapter, single_instance_enforced=True)

    # 1. Primer lanzamiento
    sess1 = mgr.launch_app("bloc de notas")
    assert len(adapter.launch_history) == 1

    # 2. Segundo lanzamiento con Single-Instance activo: DEBE REUTILIZAR Y ENFOCAR
    sess2 = mgr.launch_app("bloc de notas")
    assert sess2.session_id == sess1.session_id
    assert sess2.state == ApplicationState.FOCUSED

    # CRÍTICO: NO debe haber creado una segunda entrada en la historia de lanzamiento del SO
    assert len(adapter.launch_history) == 1
    assert len(adapter.focus_calls) == 1


def test_duplicate_launch_prevention() -> None:
    adapter = FakeApplicationAdapter()
    mgr = ApplicationSessionManager(adapter=adapter, single_instance_enforced=True)

    # Lanzar 5 veces seguidas la misma aplicación
    sessions = [mgr.launch_app("notepad") for _ in range(5)]

    # Todas las llamadas deben retornar la misma sesión inicial
    assert len({s.session_id for s in sessions}) == 1
    assert len(adapter.launch_history) == 1


def test_multi_instance_allowed_when_policy_disabled() -> None:
    adapter = FakeApplicationAdapter()
    # Desactivar la política Single-Instance
    mgr = ApplicationSessionManager(adapter=adapter, single_instance_enforced=False)

    sess1 = mgr.launch_app("bloc de notas")
    sess2 = mgr.launch_app("bloc de notas")

    # Al estar deshabilitada la política, se permiten múltiples sesiones distintas
    assert sess1.session_id != sess2.session_id
    assert len(adapter.launch_history) == 2


def test_multi_instance_allowed_for_multi_instance_app() -> None:
    adapter = FakeApplicationAdapter()
    mgr = ApplicationSessionManager(adapter=adapter, single_instance_enforced=True)

    # CMD tiene supports_single_instance=False por defecto
    sess1 = mgr.launch_app("cmd")
    sess2 = mgr.launch_app("cmd")

    assert sess1.session_id != sess2.session_id
    assert len(adapter.launch_history) == 2


def test_invalid_application_not_found() -> None:
    adapter = FakeApplicationAdapter()
    mgr = ApplicationSessionManager(adapter=adapter)

    with pytest.raises(ApplicationNotFoundError):
        mgr.launch_app("non_existent_app_xyz")


def test_focus_existing_window() -> None:
    adapter = FakeApplicationAdapter()
    mgr = ApplicationSessionManager(adapter=adapter)

    sess = mgr.launch_app("calculadora")
    focused = mgr.focus_app("calculadora")

    assert focused.session_id == sess.session_id
    assert focused.state == ApplicationState.FOCUSED


def test_emergency_stop_blocks_application_control() -> None:
    adapter = FakeApplicationAdapter()
    mgr = ApplicationSessionManager(adapter=adapter)
    em = get_emergency_stop_manager()
    boundary = ApplicationControlBoundary(session_manager=mgr, emergency_stop_manager=em)

    em.trigger_stop("Emergency stop test for ApplicationBoundary", source="test")
    try:
        with pytest.raises(EmergencyStopTriggeredError):
            boundary.execute_application_control("launch", "bloc de notas")
    finally:
        em.reset("cleanup")


def test_security_pipeline_enforcement_and_boundary() -> None:
    adapter = FakeApplicationAdapter()
    mgr = ApplicationSessionManager(adapter=adapter)
    boundary = ApplicationControlBoundary(session_manager=mgr)

    res = boundary.execute_application_control("launch", "bloc de notas", request_id="req-test-app-boundary")
    assert res["success"] is True
    assert res["action"] == "launch"
    assert res["app_alias"] == "bloc de notas"
