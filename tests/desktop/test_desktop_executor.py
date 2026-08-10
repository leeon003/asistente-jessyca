"""Pruebas de WindowsDesktopToolExecutor (Subetapa 08.1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from tools.desktop.backend import FakeDesktopCaptureBackend
from tools.desktop.desktop_service import DesktopService
from tools.desktop.executor import WindowsDesktopToolExecutor


def test_windows_desktop_tool_executor_executes_take_screenshot() -> None:
    service = DesktopService(backend=FakeDesktopCaptureBackend())
    executor = WindowsDesktopToolExecutor(desktop_service=service)

    req = ExecutionRequest(
        request_id="desktop-req-1",
        tool_name="windows.desktop",
        operation="take_screenshot",
        parameters={"width": 800, "height": 600, "format": "PNG"},
        context=RequestContext(user="test_user"),
    )

    evidence = AuthorizationEvidence(
        evidence_id="ev-desktop-1",
        request_id="desktop-req-1",
        decision=PermissionDecision.ALLOW,
        policy_rules_evaluated=("rule-desktop",),
        user_confirmed=True,
        evaluation_timestamp=datetime.now(UTC),
        risk_level=SecurityLevel.WARNING,
        action_fingerprint="fp-desktop-123",
        is_valid=True,
    )

    result = executor.execute(req, evidence)

    assert result.status == ExecutionStatus.SUCCESS
    assert result.output["metadata"]["width"] == 800


def test_windows_desktop_tool_executor_rejects_unsupported_operation() -> None:
    executor = WindowsDesktopToolExecutor()

    req = ExecutionRequest(
        request_id="desktop-req-2",
        tool_name="windows.desktop",
        operation="unsupported_op",
        parameters={},
        context=RequestContext(user="test_user"),
    )
    evidence = AuthorizationEvidence(
        evidence_id="ev-desktop-2",
        request_id="desktop-req-2",
        decision=PermissionDecision.ALLOW,
        policy_rules_evaluated=(),
        user_confirmed=True,
        evaluation_timestamp=datetime.now(UTC),
        risk_level=SecurityLevel.LOW,
        action_fingerprint="fp-desktop-456",
        is_valid=True,
    )

    with pytest.raises(ValueError):
        executor.execute(req, evidence)
