"""Herramientas MCP de visión y automatización de escritorio (Subetapa 08.1).

Implementa WindowsTakeScreenshotTool integrada con BaseMCPTool y ToolRegistry.
"""

from __future__ import annotations

from typing import Any

from core.desktop_models import OCRRequest, ScreenshotRequest
from core.security_architecture import SecurityLevel
from core.ui_inspection_models import UIElementRequest
from tools.base import BaseMCPTool, ToolMetadata
from tools.desktop.automation_service import DesktopAutomationService
from tools.desktop.desktop_service import DesktopService
from tools.desktop.ocr_service import OCRService
from tools.desktop.ui_inspection_service import UIInspectionService


class WindowsTakeScreenshotTool(BaseMCPTool):
    """Herramienta MCP para realizar una captura de pantalla segura del escritorio (`windows.desktop`)."""

    def __init__(self, service: DesktopService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.desktop",
                description="Captura de pantalla segura del escritorio de Windows.",
                category="desktop",
                risk_level=SecurityLevel.WARNING,
            )
        )
        self.service = service or DesktopService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        x = int(parameters.get("x", 0))
        y = int(parameters.get("y", 0))
        width = int(parameters["width"]) if "width" in parameters and parameters["width"] is not None else None
        height = int(parameters["height"]) if "height" in parameters and parameters["height"] is not None else None
        fmt = str(parameters.get("format", "PNG"))
        qual = int(parameters.get("quality", 85))

        req = ScreenshotRequest(x=x, y=y, width=width, height=height, format=fmt, quality=qual)
        return self.service.take_screenshot(req).to_dict()


class WindowsOCRScreenTool(BaseMCPTool):
    """Herramienta MCP para realizar extracción OCR segura de texto desde capturas del escritorio."""

    def __init__(self, service: OCRService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.desktop",
                description="Reconocimiento OCR seguro de texto desde regiones del escritorio de Windows.",
                category="desktop",
                risk_level=SecurityLevel.WARNING,
            )
        )
        self.ocr_service = service or OCRService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        x = int(parameters.get("x", 0))
        y = int(parameters.get("y", 0))
        width = int(parameters["width"]) if "width" in parameters and parameters["width"] is not None else None
        height = int(parameters["height"]) if "height" in parameters and parameters["height"] is not None else None
        lang = str(parameters.get("language", "eng"))
        img_b64 = str(parameters["image_base64"]) if "image_base64" in parameters and parameters["image_base64"] is not None else None

        req = OCRRequest(x=x, y=y, width=width, height=height, language=lang, image_base64=img_b64)
        return self.ocr_service.process_ocr(req).to_dict()


class WindowsInspectUIElementTool(BaseMCPTool):
    """Herramienta MCP para realizar inspección visual segura de elementos UI del escritorio (`windows.desktop`)."""

    def __init__(self, service: UIInspectionService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.desktop",
                description="Inspección visual y consulta de jerarquía de elementos UI del escritorio de Windows.",
                category="desktop",
                risk_level=SecurityLevel.WARNING,
            )
        )
        self.ui_service = service or UIInspectionService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        win_title = str(parameters["window_title"]) if "window_title" in parameters and parameters["window_title"] is not None else None
        ctrl_type = str(parameters["control_type"]) if "control_type" in parameters and parameters["control_type"] is not None else None
        m_depth = int(parameters.get("max_depth", 20))
        m_elems = int(parameters.get("max_elements", 1000))

        req = UIElementRequest(window_title=win_title, control_type=ctrl_type, max_depth=m_depth, max_elements=m_elems)
        return self.ui_service.inspect_ui_elements(req).to_dict()


class WindowsClickElementTool(BaseMCPTool):
    """Herramienta MCP para realizar clic guiado sobre un elemento UI del escritorio (`windows.desktop`)."""

    def __init__(self, service: DesktopAutomationService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.desktop",
                description="Ejecución controlada de clic sobre un elemento UI del escritorio.",
                category="desktop",
                risk_level=SecurityLevel.DANGEROUS,
            )
        )
        self.automation_service = service or DesktopAutomationService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        # Las herramientas ejecutan a través de WindowsDesktopToolExecutor dentro del pipeline
        raise NotImplementedError("Las herramientas MCP de automatización deben ejecutarse a través de WindowsDesktopToolExecutor dentro del SecureExecutionPipeline.")


class WindowsTypeTextTool(BaseMCPTool):
    """Herramienta MCP para realizar escritura de texto sobre un elemento UI (`windows.desktop`)."""

    def __init__(self, service: DesktopAutomationService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.desktop",
                description="Escritura controlada de texto sobre un elemento UI del escritorio.",
                category="desktop",
                risk_level=SecurityLevel.DANGEROUS,
            )
        )
        self.automation_service = service or DesktopAutomationService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Las herramientas MCP de automatización deben ejecutarse a través de WindowsDesktopToolExecutor dentro del SecureExecutionPipeline.")


class WindowsFocusWindowTool(BaseMCPTool):
    """Herramienta MCP para enfocar y activar una ventana del escritorio (`windows.desktop`)."""

    def __init__(self, service: DesktopAutomationService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.desktop",
                description="Enfoque y activación de una ventana del escritorio de Windows.",
                category="desktop",
                risk_level=SecurityLevel.WARNING,
            )
        )
        self.automation_service = service or DesktopAutomationService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Las herramientas MCP de automatización deben ejecutarse a través de WindowsDesktopToolExecutor dentro del SecureExecutionPipeline.")


class WindowsDragAndDropTool(BaseMCPTool):
    """Herramienta MCP para realizar arrastrar y soltar entre coordenadas (`windows.desktop`)."""

    def __init__(self, service: DesktopAutomationService | None = None) -> None:
        super().__init__(
            metadata=ToolMetadata(
                name="windows.desktop",
                description="Arrastrar y soltar entre coordenadas acotadas del escritorio.",
                category="desktop",
                risk_level=SecurityLevel.DANGEROUS,
            )
        )
        self.automation_service = service or DesktopAutomationService()

    def execute_tool(self, parameters: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Las herramientas MCP de automatización deben ejecutarse a través de WindowsDesktopToolExecutor dentro del SecureExecutionPipeline.")
