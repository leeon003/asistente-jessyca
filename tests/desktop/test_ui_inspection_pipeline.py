"""Pruebas de integración del SecureExecutionPipeline para la operación inspect_ui_element (Subetapa 08.3)."""

from __future__ import annotations

from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from server.pipeline import SecureExecutionPipeline
from tools.desktop.executor import WindowsDesktopToolExecutor
from tools.desktop.ui_backend import FakeUIInspectionBackend
from tools.desktop.ui_inspection_service import UIInspectionService


def test_secure_execution_pipeline_desktop_inspect_ui_element() -> None:
    pipeline = SecureExecutionPipeline()

    fake_ui = UIInspectionService(backend=FakeUIInspectionBackend())
    pipeline.boundary.register_executor("windows.desktop", WindowsDesktopToolExecutor(ui_service=fake_ui))

    req = ExecutionRequest(
        request_id="pipeline-ui-101",
        tool_name="windows.desktop",
        operation="inspect_ui_element",
        parameters={"window_title": "App Window", "max_depth": 10},
        context=RequestContext(user="operator"),
    )

    result = pipeline.execute_request(req)

    assert result.status == ExecutionStatus.SUCCESS
    assert result.output["metadata"]["element_count"] >= 1
