"""Pruebas dedicadas para la Parada de Emergencia / Fail-Safe global (Subetapa 08.4)."""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime
import pytest

from core.audit_logger import MemoryAuditSink
from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionTarget,
    DesktopActionType,
)
from core.emergency_stop import (
    CancellationToken,
    EmergencyStopManager,
    EmergencyStopState,
    EmergencyStopTriggeredError,
    FakeEmergencyStopController,
    get_emergency_stop_manager,
)
from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel
from server.evidence import AuthorizationEvidence
from tools.desktop.automation_backend import FakeDesktopAutomationBackend
from tools.desktop.automation_service import DesktopAutomationService


def test_emergency_stop_state_transitions() -> None:
    em = get_emergency_stop_manager()
    em.reset("test_init")
    assert em.is_stopped() is False
    assert em.get_status()["state"] == "RUNNING"

    em.trigger_stop(reason="User panic corner", source="user_mouse")
    assert em.is_stopped() is True
    assert em.get_status()["state"] == "STOPPED"
    assert em.get_status()["activation_count"] >= 1

    em.reset("test_completed")
    assert em.is_stopped() is False
    assert em.get_status()["state"] == "RUNNING"


def test_emergency_stop_cancellation_token_wait() -> None:
    token = CancellationToken()
    assert token.is_cancellation_requested() is False

    # Espera normal sin cancelación
    is_cancelled = token.wait_or_cancelled(0.01)
    assert is_cancelled is False

    # Activar cancelación
    token._event.set()
    assert token.is_cancellation_requested() is True
    assert token.wait_or_cancelled(0.01) is True


def test_emergency_stop_double_stop_idempotency() -> None:
    em = get_emergency_stop_manager()
    em.reset("test_init")

    em.trigger_stop("First stop", source="test")
    count_1 = em.get_status()["activation_count"]

    # Segunda llamada idempotente
    em.trigger_stop("Second stop", source="test")
    count_2 = em.get_status()["activation_count"]

    assert count_1 == count_2
    assert em.is_stopped() is True

    em.reset("test_cleanup")


def test_emergency_stop_phase_cancellation_checks() -> None:
    em = get_emergency_stop_manager()
    em.reset("test_init")

    # En RUNNING, las verificaciones por fase no lanzan excepción
    em.check_cancellation("validation")
    em.check_cancellation("execution")
    em.check_cancellation("verification")

    # En STOPPED, se lanza EmergencyStopTriggeredError
    em.trigger_stop("Phase test stop", source="test")

    with pytest.raises(EmergencyStopTriggeredError) as exc_val:
        em.check_cancellation("validation")
    assert "validation" in str(exc_val.value)

    with pytest.raises(EmergencyStopTriggeredError) as exc_exec:
        em.check_cancellation("execution")
    assert "execution" in str(exc_exec.value)

    em.reset("test_cleanup")


def test_fake_emergency_stop_controller() -> None:
    fake_ctrl = FakeEmergencyStopController()
    assert fake_ctrl.is_stopped() is False

    fake_ctrl.set_phase_stop("waiting")
    with pytest.raises(EmergencyStopTriggeredError) as exc:
        fake_ctrl.check_cancellation("waiting")
    assert "waiting" in str(exc.value)

    # Otras fases pasan sin detenerse
    fake_ctrl.check_cancellation("validation")


def test_emergency_stop_concurrency_and_race_conditions() -> None:
    em = get_emergency_stop_manager()
    em.reset("test_init")

    def stop_worker(worker_id: int) -> bool:
        em.trigger_stop(f"Stop from worker {worker_id}", source=f"worker_{worker_id}")
        return em.is_stopped()

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as tp:
        futures = [tp.submit(stop_worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
    assert em.is_stopped() is True
    em.reset("test_cleanup")


def test_emergency_stop_audit_metadata_privacy() -> None:
    sink = MemoryAuditSink()
    em = get_emergency_stop_manager()
    em.audit_logger.add_sink(sink)
    em.reset("test_init")

    em.trigger_stop("Audit test stop", source="audit_test")
    events = sink.get_events(tool_name="system.emergency_stop")
    assert len(events) >= 1

    ev = events[-1]
    assert ev.metadata["source"] == "audit_test"
    assert ev.metadata["state"] == "STOPPED"
    em.reset("test_cleanup")


def test_emergency_stop_blocks_service_execution() -> None:
    service = DesktopAutomationService(backend=FakeDesktopAutomationBackend())
    em = get_emergency_stop_manager()

    em.trigger_stop("Testing Emergency Stop blocking", source="unit_test")

    req = DesktopActionRequest(
        action_type=DesktopActionType.CLICK_ELEMENT,
        target=DesktopActionTarget(x=10, y=10),
    )

    try:
        with pytest.raises(Exception) as exc_info:
            dummy_ev = AuthorizationEvidence(
                request_id="req-em",
                correlation_id="corr-em",
                tool_name="windows.desktop",
                operation="click_element",
                risk_assessment=None,
                policy_result=None,
                permission_result=None,
                confirmation_result=None,
                action_fingerprint="dummy",
                evidence_id="ev-em",
            )
            service.execute_action(req, dummy_ev, request_id="req-em")

        assert "EMERGENCY" in str(exc_info.value).upper() or "PARADA" in str(exc_info.value).upper()
    finally:
        em.reset("test_cleanup")
