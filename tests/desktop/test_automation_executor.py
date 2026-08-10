"""Pruebas de la integración de acciones de automatización en WindowsDesktopToolExecutor (Subetapa 08.4)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.desktop_automation_models import generate_action_fingerprint
from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from tools.desktop.automation_backend import FakeDesktopAutomationBackend
from tools.desktop.automation_service import DesktopAutomationService
from tools.desktop.executor import WindowsDesktopToolExecutor


def test_windows_desktop_tool_executor_executes_click_element() -> None:
    backend = FakeDesktopAutomationBackend()
    aut_service = DesktopAutomationService(backend=backend)
    aut_service.emergency_stop.deactivate()
    executor = WindowsDesktopToolExecutor(automation_service=aut_service)

    target_dict = {
        "automation_id": "BtnSubmit",
        "name": None,
        "control_type": None,
        "process_id": None,
        "window_handle": None,
        "x": 100,
        "y": 200,
        "width": None,
        "height": None,
    }
    fp = generate_action_fingerprint("windows.desktop", "click_element", target_dict, {}, "aut-exec-1")

    req = ExecutionRequest(
        request_id="aut-exec-1",
        tool_name="windows.desktop",
        operation="click_element",
        parameters={"automation_id": "BtnSubmit", "x": 100, "y": 200},
        context=RequestContext(user="test_user"),
    )

    evidence = AuthorizationEvidence(
        evidence_id="ev-exec-1",
        request_id="aut-exec-1",
        decision=PermissionDecision.ALLOW,
        policy_rules_evaluated=("rule-1",),
        user_confirmed=True,
        evaluation_timestamp=datetime.now(UTC),
        risk_level=SecurityLevel.DANGEROUS,
        action_fingerprint=fp,
        is_valid=True,
    )

    result = executor.execute(req, evidence)

    assert result.status == ExecutionStatus.SUCCESS
    assert result.output["success"] is True
