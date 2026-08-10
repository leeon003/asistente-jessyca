"""Pruebas de la integración de ocr_screen en WindowsDesktopToolExecutor (Subetapa 08.2)."""

from __future__ import annotations

from datetime import UTC, datetime

from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from tools.desktop.executor import WindowsDesktopToolExecutor
from tools.desktop.ocr_backend import FakeOCRBackend
from tools.desktop.ocr_service import OCRService


def test_windows_desktop_tool_executor_executes_ocr_screen() -> None:
    ocr_service = OCRService(backend=FakeOCRBackend())
    executor = WindowsDesktopToolExecutor(ocr_service=ocr_service)

    req = ExecutionRequest(
        request_id="ocr-req-exec-1",
        tool_name="windows.desktop",
        operation="ocr_screen",
        parameters={"width": 800, "height": 600, "language": "eng"},
        context=RequestContext(user="test_user"),
    )

    evidence = AuthorizationEvidence(
        evidence_id="ev-ocr-1",
        request_id="ocr-req-exec-1",
        decision=PermissionDecision.ALLOW,
        policy_rules_evaluated=("rule-ocr",),
        user_confirmed=True,
        evaluation_timestamp=datetime.now(UTC),
        risk_level=SecurityLevel.WARNING,
        action_fingerprint="fp-ocr-123",
        is_valid=True,
    )

    result = executor.execute(req, evidence)

    assert result.status == ExecutionStatus.SUCCESS
    assert "recognized_text" in result.output
    assert result.output["metadata"]["char_count"] > 0
