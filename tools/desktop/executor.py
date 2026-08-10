"""Ejecutor real seguro de herramientas de escritorio (WindowsDesktopToolExecutor - Subetapa 08.1).

Ejecuta la operación de captura de pantalla únicamente tras recibir una ExecutionRequest y AuthorizationEvidence
válidas y verificadas por la frontera de seguridad.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionTarget,
    DesktopActionType,
)
from core.desktop_models import OCRRequest, ScreenshotRequest
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.ui_inspection_models import UIElementRequest
from server.boundary import ExecutionResult, ExecutionStatus
from server.evidence import AuthorizationEvidence
from server.execution_request import ExecutionRequest
from server.executor import IToolExecutor
from tools.desktop.automation_service import DesktopAutomationService
from tools.desktop.desktop_service import DesktopService
from tools.desktop.ocr_service import OCRService
from tools.desktop.ui_inspection_service import UIInspectionService

logger = get_logger("jessyca.tools.desktop.executor")


class WindowsDesktopToolExecutor(IToolExecutor):
    """Ejecutor real seguro para la herramienta de visión, capturas, OCR, inspección UI y automatización de escritorio (`windows.desktop`)."""

    def __init__(
        self,
        desktop_service: DesktopService | None = None,
        ocr_service: OCRService | None = None,
        ui_service: UIInspectionService | None = None,
        automation_service: DesktopAutomationService | None = None,
    ) -> None:
        self.service = desktop_service or DesktopService()
        self.ocr_service = ocr_service or OCRService()
        self.ui_service = ui_service or UIInspectionService()
        self.automation_service = automation_service or DesktopAutomationService()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def execute(
        self,
        request: ExecutionRequest,
        evidence: AuthorizationEvidence,
    ) -> ExecutionResult:
        """Ejecuta la operación de escritorio, visión, inspección UI o automatización autorizada por el pipeline."""
        start_time = datetime.now(UTC)
        op = request.operation.lower()
        params = request.parameters
        req_id = request.request_id

        logger.info(f"[DESKTOP EXECUTOR] Ejecutando '{request.tool_name}.{op}' para request [{req_id[:8]}]")

        if op in ("take_screenshot", "screenshot"):
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
            width = int(params["width"]) if "width" in params and params["width"] is not None else None
            height = int(params["height"]) if "height" in params and params["height"] is not None else None
            fmt = str(params.get("format", "PNG"))
            qual = int(params.get("quality", 85))

            shot_req = ScreenshotRequest(x=x, y=y, width=width, height=height, format=fmt, quality=qual)
            res_dict = self.service.take_screenshot(shot_req, request_id=req_id).to_dict()
            msg = "Captura de pantalla realizada exitosamente."

        elif op in ("ocr_screen", "ocr"):
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
            width = int(params["width"]) if "width" in params and params["width"] is not None else None
            height = int(params["height"]) if "height" in params and params["height"] is not None else None
            lang = str(params.get("language", "eng"))
            img_b64 = str(params["image_base64"]) if "image_base64" in params and params["image_base64"] is not None else None

            ocr_req = OCRRequest(x=x, y=y, width=width, height=height, language=lang, image_base64=img_b64)
            res_dict = self.ocr_service.process_ocr(ocr_req, request_id=req_id).to_dict()
            msg = "Reconocimiento OCR realizado y sanitizado exitosamente."

        elif op in ("inspect_ui_element", "inspect_ui", "ui_inspect"):
            win_title = str(params["window_title"]) if "window_title" in params and params["window_title"] is not None else None
            ctrl_type = str(params["control_type"]) if "control_type" in params and params["control_type"] is not None else None
            m_depth = int(params.get("max_depth", 20))
            m_elems = int(params.get("max_elements", 1000))

            ui_req = UIElementRequest(window_title=win_title, control_type=ctrl_type, max_depth=m_depth, max_elements=m_elems)
            res_dict = self.ui_service.inspect_ui_elements(ui_req, request_id=req_id).to_dict()
            msg = "Inspección visual de elementos UI realizada exitosamente."

        elif op in ("get_active_window", "active_window"):
            res_dict = self.ui_service.get_active_window(request_id=req_id).to_dict()
            msg = "Consulta de ventana activa realizada exitosamente."

        elif op in ("list_windows", "windows"):
            wins = self.ui_service.list_windows(request_id=req_id)
            res_dict = {"windows": [w.to_dict() for w in wins], "count": len(wins)}
            msg = "Listado de ventanas realizado exitosamente."

        elif op in ("click_element", "type_text", "focus_window", "drag_and_drop"):
            action_type = DesktopActionType.from_str(op)

            t_auto_id = str(params["automation_id"]) if "automation_id" in params and params["automation_id"] is not None else None
            t_name = str(params["name"]) if "name" in params and params["name"] is not None else None
            t_ctrl_type = str(params["control_type"]) if "control_type" in params and params["control_type"] is not None else None
            t_pid = int(params["process_id"]) if "process_id" in params and params["process_id"] is not None else None
            t_hwnd = int(params["window_handle"]) if "window_handle" in params and params["window_handle"] is not None else None
            t_x = int(params["x"]) if "x" in params and params["x"] is not None else None
            t_y = int(params["y"]) if "y" in params and params["y"] is not None else None
            t_w = int(params["width"]) if "width" in params and params["width"] is not None else None
            t_h = int(params["height"]) if "height" in params and params["height"] is not None else None

            target = DesktopActionTarget(
                automation_id=t_auto_id,
                name=t_name,
                control_type=t_ctrl_type,
                process_id=t_pid,
                window_handle=t_hwnd,
                x=t_x,
                y=t_y,
                width=t_w,
                height=t_h,
            )

            typed_text = str(params["text"]) if "text" in params and params["text"] is not None else None
            d_x = int(params["dest_x"]) if "dest_x" in params and params["dest_x"] is not None else None
            d_y = int(params["dest_y"]) if "dest_y" in params and params["dest_y"] is not None else None
            dur = float(params.get("duration_ms", 100.0))

            action_req = DesktopActionRequest(
                action_type=action_type,
                target=target,
                text=typed_text,
                dest_x=d_x,
                dest_y=d_y,
                duration_ms=dur,
            )

            res_dict = self.automation_service.execute_action(action_req, evidence, request_id=req_id).to_dict()
            msg = f"Acción de automatización '{op}' ejecutada exitosamente."

        else:
            raise ValueError(f"Operación de escritorio no soportada: '{op}'")

        duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

        return ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            request_id=req_id,
            tool_name=request.tool_name,
            operation=op,
            output=res_dict,
            message=msg,
            duration_ms=duration,
            timestamp=datetime.now(UTC),
        )
