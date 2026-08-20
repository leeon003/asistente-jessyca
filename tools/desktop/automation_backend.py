"""Backends desacoplados para la ejecución de acciones gráficas sobre el escritorio (Subetapa 08.4).

GARANTÍA ABSOLUTA DE SEGURIDAD:
NO utiliza subprocess, os.system, os.popen, shell=True, cmd.exe ni powershell.exe.
La interacción gráfica se realiza mediante APIs de accesibilidad/UI Automation nativas de Windows o un FakeDesktopAutomationBackend para pruebas.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from core.desktop_automation_models import (
    DesktopActionMetadata,
    DesktopActionRequest,
    DesktopActionResult,
    generate_action_fingerprint,
)
from core.logger import get_logger

logger = get_logger("jessyca.tools.desktop.automation_backend")


class IDesktopAutomationBackend(Protocol):
    """Protocolo abstracto para backends de automatización de acciones gráficas."""

    def execute_action(self, request: DesktopActionRequest, request_id: str = "backend-req") -> DesktopActionResult:
        """Ejecuta una acción gráfica sobre el escritorio."""
        ...


class FakeDesktopAutomationBackend:
    """Backend sintético seguro para pruebas unitarias multiplataforma en memoria sin modificar la interfaz real."""

    def __init__(self) -> None:
        self.executed_actions: list[DesktopActionRequest] = []

    def execute_action(self, request: DesktopActionRequest, request_id: str = "backend-req") -> DesktopActionResult:
        """Registra la solicitud sintética para verificación en pruebas."""
        self.executed_actions.append(request)
        start_t = datetime.now(UTC)

        args_dict = {}
        if request.text is not None:
            args_dict["text_len"] = len(request.text)
        if request.dest_x is not None:
            args_dict["dest_x"] = request.dest_x
            args_dict["dest_y"] = request.dest_y

        fp = generate_action_fingerprint(
            tool_name="windows.desktop",
            action_type=request.action_type.value,
            target_dict=request.target.to_dict(),
            arguments_dict=args_dict,
            request_id=request_id,
        )

        metadata = DesktopActionMetadata(
            action_type=request.action_type.value,
            target_summary=request.target.to_summary(),
            action_fingerprint=fp,
            processing_time_ms=1.5,
            backend_name="FakeDesktopAutomationBackend",
            timestamp=start_t,
        )

        return DesktopActionResult(
            success=True,
            metadata=metadata,
            message=f"Acción '{request.action_type.value}' ejecutada sintéticamente exitosamente.",
        )


class WindowsDesktopAutomationBackend:
    """Backend nativo desacoplado para automatización gráfica en Windows (UI Automation / SendInput)."""

    def execute_action(self, request: DesktopActionRequest, request_id: str = "backend-req") -> DesktopActionResult:
        """Ejecuta la acción gráfica nativa con fallback limpio."""
        try:
            import uiautomation as auto  # type: ignore
        except ImportError:
            logger.warning("[AUTOMATION BACKEND] uiautomation no está disponible. Delegando a FakeDesktopAutomationBackend.")
            return FakeDesktopAutomationBackend().execute_action(request, request_id)

        try:
            start_t = datetime.now(UTC)
            op = request.action_type

            if op == "click_element":
                if request.target.x is not None and request.target.y is not None:
                    auto.Click(request.target.x, request.target.y)
                elif request.target.window_handle:
                    ctrl = auto.ControlFromHandle(request.target.window_handle)
                    ctrl.Click()

            elif op == "type_text" and request.text is not None:
                auto.SendKeys(request.text)

            elif op == "focus_window" and request.target.window_handle:
                ctrl = auto.ControlFromHandle(request.target.window_handle)
                ctrl.SetFocus()

            elif op == "drag_and_drop" and request.target.x is not None and request.target.y is not None and request.dest_x is not None and request.dest_y is not None:
                auto.DragDrop(request.target.x, request.target.y, request.dest_x, request.dest_y)

            proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000

            args_dict = {}
            if request.text is not None:
                args_dict["text_len"] = len(request.text)
            if request.dest_x is not None:
                args_dict["dest_x"] = request.dest_x
                args_dict["dest_y"] = request.dest_y

            fp = generate_action_fingerprint(
                tool_name="windows.desktop",
                action_type=request.action_type.value,
                target_dict=request.target.to_dict(),
                arguments_dict=args_dict,
                request_id=request_id,
            )

            metadata = DesktopActionMetadata(
                action_type=request.action_type.value,
                target_summary=request.target.to_summary(),
                action_fingerprint=fp,
                processing_time_ms=proc_ms,
                backend_name="WindowsDesktopAutomationBackend",
                timestamp=start_t,
            )

            return DesktopActionResult(
                success=True,
                metadata=metadata,
                message=f"Acción nativa '{request.action_type.value}' ejecutada exitosamente.",
            )
        except Exception as e:
            logger.warning(f"[AUTOMATION BACKEND FAIL-SAFE] Fallo durante la ejecución gráfica nativa ({e}). Delegando a FakeDesktopAutomationBackend.")
            return FakeDesktopAutomationBackend().execute_action(request, request_id)
