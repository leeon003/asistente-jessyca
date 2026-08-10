"""Pruebas de integración del SecureExecutionPipeline para la operación ocr_screen (Subetapa 08.2)."""

from __future__ import annotations

from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from server.pipeline import SecureExecutionPipeline
from tools.desktop.executor import WindowsDesktopToolExecutor
from tools.desktop.ocr_backend import FakeOCRBackend
from tools.desktop.ocr_service import OCRService


def test_secure_execution_pipeline_desktop_ocr_screen() -> None:
    pipeline = SecureExecutionPipeline()

    fake_ocr = OCRService(backend=FakeOCRBackend())
    pipeline.boundary.register_executor("windows.desktop", WindowsDesktopToolExecutor(ocr_service=fake_ocr))

    req = ExecutionRequest(
        request_id="pipeline-ocr-101",
        tool_name="windows.desktop",
        operation="ocr_screen",
        parameters={"width": 1024, "height": 768, "language": "eng"},
        context=RequestContext(user="operator"),
    )

    result = pipeline.execute_request(req)

    assert result.status == ExecutionStatus.SUCCESS
    assert result.output["metadata"]["region_count"] >= 1
