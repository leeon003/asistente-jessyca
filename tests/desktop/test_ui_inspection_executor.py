"""Pruebas de la integración de inspect_ui_element en WindowsDesktopToolExecutor (Subetapa 08.3)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from tools.desktop.executor import WindowsDesktopToolExecutor
from tools.desktop.ui_backend import FakeUIInspectionBackend
from tools.desktop.ui_inspection_service import UIInspectionService


def test_windows_desktop_tool_executor_executes_inspect_ui_element() -> None:
    ui_service = UIInspectionService(backend=FakeUIInspectionBackend())
    executor = WindowsDesktopToolExecutor(ui_service=ui_service)

    req = ExecutionRequest(
        request_id="ui-req-exec-1",
        tool_name="windows.desktop",
        operation="inspect_ui_element",
        parameters={"window_title": "Main Window", "max_depth": 5},
        context=RequestContext(user="test_user"),
    )

    evidence = AuthorizationEvidence(
        evidence_id="ev-ui-1",
        request_id="ui-req-exec-1",
        decision=PermissionDecision.ALLOW,
        policy_rules_evaluated=("rule-ui",),
        user_confirmed=True,
        evaluation_timestamp=datetime.now(UTC),
        risk_level=SecurityLevel.WARNING,
        action_fingerprint="fp-ui-123",
        is_valid=True,
    )

    result = executor.execute(req, evidence)

    assert result.status == ExecutionStatus.SUCCESS
    assert "tree" in result.output
    assert result.output["metadata"]["element_count"] >= 1
