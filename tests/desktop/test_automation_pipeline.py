"""Pruebas de integración del SecureExecutionPipeline para operaciones de automatización (Subetapa 08.4)."""

from __future__ import annotations

from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from server.pipeline import SecureExecutionPipeline
from tools.desktop.automation_backend import FakeDesktopAutomationBackend
from tools.desktop.automation_service import DesktopAutomationService
from tools.desktop.executor import WindowsDesktopToolExecutor


def test_secure_execution_pipeline_desktop_focus_window() -> None:
    pipeline = SecureExecutionPipeline()

    aut_service = DesktopAutomationService(backend=FakeDesktopAutomationBackend())
    aut_service.emergency_stop.deactivate()

    pipeline.boundary.register_executor("windows.desktop", WindowsDesktopToolExecutor(automation_service=aut_service))

    req = ExecutionRequest(
        request_id="pipeline-aut-101",
        tool_name="windows.desktop",
        operation="focus_window",
        parameters={"window_handle": 123456},
        context=RequestContext(user="operator"),
    )

    result = pipeline.execute_request(req)

    assert result.status == ExecutionStatus.SUCCESS
    assert result.output["success"] is True
