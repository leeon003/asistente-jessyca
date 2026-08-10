"""Pruebas de integración del SecureExecutionPipeline para el dominio windows.desktop (Subetapa 08.1)."""

from __future__ import annotations

from server.execution_request import ExecutionRequest, RequestContext
from server.executor import ExecutionStatus
from server.pipeline import SecureExecutionPipeline
from tools.desktop.backend import FakeDesktopCaptureBackend
from tools.desktop.desktop_service import DesktopService
from tools.desktop.executor import WindowsDesktopToolExecutor


def test_secure_execution_pipeline_desktop_take_screenshot() -> None:
    pipeline = SecureExecutionPipeline()

    # Reemplazar el ejecutor por defecto de windows.desktop con FakeBackend para pruebas deterministas
    fake_service = DesktopService(backend=FakeDesktopCaptureBackend())
    pipeline.boundary.register_executor("windows.desktop", WindowsDesktopToolExecutor(desktop_service=fake_service))

    req = ExecutionRequest(
        request_id="pipeline-desktop-101",
        tool_name="windows.desktop",
        operation="take_screenshot",
        parameters={"width": 640, "height": 480},
        context=RequestContext(user="operator"),
    )

    result = pipeline.execute_request(req)

    assert result.status == ExecutionStatus.SUCCESS
    assert result.output["metadata"]["width"] == 640
    assert result.output["metadata"]["height"] == 480
