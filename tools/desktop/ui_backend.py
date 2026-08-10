"""Backends desacoplados para la inspección visual de elementos UI (Subetapa 08.3).

GARANTÍA ABSOLUTA DE SEGURIDAD:
NO realiza NINGUNA acción sobre la interfaz (ZERO UI ACTIONS: CERO click, CERO teclado, CERO movimiento de mouse).
NO utiliza subprocess, os.system, os.popen, shell=True, cmd.exe ni powershell.exe.
La inspección se realiza mediante la API nativa de Windows UI Automation o mediante FakeUIInspectionBackend para pruebas.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from core.desktop_models import ScreenshotRequest
from core.logger import get_logger
from core.ui_inspection_models import (
    UIControlType,
    UIElementBounds,
    UIElementInfo,
    UIElementRequest,
    UIElementTree,
    UIInspectionMetadata,
    UIInspectionResult,
    WindowInfo,
)

logger = get_logger("jessyca.tools.desktop.ui_backend")


class IUIInspectionBackend(Protocol):
    """Protocolo abstracto para backends de inspección visual de elementos UI."""

    def inspect_ui(self, request: UIElementRequest) -> UIInspectionResult:
        """Inspecciona y retorna la jerarquía de elementos UI visibles."""
        ...

    def get_active_window(self) -> WindowInfo:
        """Obtiene la información inmutable de la ventana activa actualmente en primer plano."""
        ...

    def list_windows(self) -> tuple[WindowInfo, ...]:
        """Lista todas las ventanas principales visibles en el escritorio."""
        ...


class FakeUIInspectionBackend:
    """Backend sintético seguro para pruebas multiplataforma y entornos headless sin sesión gráfica de Windows."""

    def __init__(self, mock_tree: UIElementTree | None = None) -> None:
        self.mock_tree = mock_tree

    def inspect_ui(self, request: UIElementRequest) -> UIInspectionResult:
        """Genera un árbol sintético completo de elementos UI para pruebas deterministas."""
        if self.mock_tree:
            root = self.mock_tree.root
        else:
            # Construir jerarquía sintética estándar
            btn_close = UIElementInfo(
                automation_id="BtnClose",
                name="Close Window",
                control_type=UIControlType.BUTTON,
                class_name="Button",
                bounds=UIElementBounds(x=780, y=10, width=20, height=20),
                is_enabled=True,
                is_offscreen=False,
                has_keyboard_focus=False,
                process_id=1234,
                framework_id="Win32",
            )
            input_field = UIElementInfo(
                automation_id="TxtInput",
                name="Command Input (api_key=sk_test_secret123)",
                control_type=UIControlType.EDIT,
                class_name="Edit",
                bounds=UIElementBounds(x=50, y=100, width=300, height=30),
                is_enabled=True,
                is_offscreen=False,
                has_keyboard_focus=True,
                process_id=1234,
                framework_id="Win32",
            )
            chk_sec = UIElementInfo(
                automation_id="ChkSecure",
                name="Enable Security Mode",
                control_type=UIControlType.CHECKBOX,
                class_name="Button",
                bounds=UIElementBounds(x=50, y=150, width=200, height=25),
                is_enabled=True,
                is_offscreen=False,
                has_keyboard_focus=False,
                process_id=1234,
                framework_id="Win32",
            )
            root = UIElementInfo(
                automation_id="MainWindow_101",
                name=request.window_title or "Jessyca MCP Application Window",
                control_type=UIControlType.WINDOW,
                class_name="Window",
                bounds=UIElementBounds(x=0, y=0, width=800, height=600),
                is_enabled=True,
                is_offscreen=False,
                has_keyboard_focus=False,
                process_id=1234,
                framework_id="Win32",
                children=(btn_close, input_field, chk_sec),
            )

        elements_flat: list[UIElementInfo] = []
        max_depth = 0

        def traverse(node: UIElementInfo, depth: int) -> None:
            nonlocal max_depth
            if depth > max_depth:
                max_depth = depth
            elements_flat.append(node)
            for child in node.children:
                traverse(child, depth + 1)

        traverse(root, 1)

        metadata = UIInspectionMetadata(
            element_count=len(elements_flat),
            max_depth_reached=max_depth,
            processing_time_ms=3.5,
            backend_name="FakeUIInspectionBackend",
            timestamp=datetime.now(UTC),
        )

        return UIInspectionResult(
            tree=UIElementTree(root=root),
            elements_flat=tuple(elements_flat),
            metadata=metadata,
            truncated=False,
        )

    def get_active_window(self) -> WindowInfo:
        """Obtiene la ventana activa sintética para pruebas."""
        return WindowInfo(
            hwnd=1001,
            title="Jessyca MCP Application Window",
            class_name="Window",
            process_id=1234,
            bounds=UIElementBounds(x=0, y=0, width=800, height=600),
            is_active=True,
            is_minimized=False,
            is_maximized=False,
            is_visible=True,
            timestamp=datetime.now(UTC),
        )

    def list_windows(self) -> tuple[WindowInfo, ...]:
        """Lista las ventanas sintéticas para pruebas."""
        win1 = self.get_active_window()
        win2 = WindowInfo(
            hwnd=1002,
            title="Calculator",
            class_name="CalcFrame",
            process_id=5678,
            bounds=UIElementBounds(x=100, y=100, width=300, height=400),
            is_active=False,
            is_minimized=False,
            is_maximized=False,
            is_visible=True,
            timestamp=datetime.now(UTC),
        )
        return (win1, win2)


class WindowsUIAutomationBackend:
    """Backend nativo desacoplado para inspección UI de Windows mediante UI Automation."""

    def get_active_window(self) -> WindowInfo:
        """Obtiene la información inmutable de la ventana activa usando APIs de Win32 o uiautomation."""
        try:
            import uiautomation as auto  # type: ignore
            win = auto.GetForegroundControl()
            rect = win.BoundingRectangle
            x = max(0, rect.left) if rect else 0
            y = max(0, rect.top) if rect else 0
            w = max(1, rect.width()) if rect else 1
            h = max(1, rect.height()) if rect else 1

            return WindowInfo(
                hwnd=win.NativeWindowHandle or 0,
                title=win.Name or "Active Window",
                class_name=win.ClassName or "Window",
                process_id=win.ProcessId or 0,
                bounds=UIElementBounds(x=x, y=y, width=w, height=h),
                is_active=True,
                is_minimized=False,
                is_maximized=False,
                is_visible=True,
                timestamp=datetime.now(UTC),
            )
        except Exception as e:
            logger.warning(f"[UI BACKEND FAIL-SAFE] Fallo al consultar ventana activa nativa ({e}). Delegando a FakeUIInspectionBackend.")
            return FakeUIInspectionBackend().get_active_window()

    def list_windows(self) -> tuple[WindowInfo, ...]:
        """Lista todas las ventanas visibles principales usando APIs nativas."""
        try:
            import uiautomation as auto  # type: ignore
            root = auto.GetRootControl()
            wins: list[WindowInfo] = []

            for child in root.GetChildren():
                if child.ControlTypeName == "Window" and not child.IsOffscreen:
                    rect = child.BoundingRectangle
                    x = max(0, rect.left) if rect else 0
                    y = max(0, rect.top) if rect else 0
                    w = max(1, rect.width()) if rect else 1
                    h = max(1, rect.height()) if rect else 1

                    wins.append(
                        WindowInfo(
                            hwnd=child.NativeWindowHandle or 0,
                            title=child.Name or "Window",
                            class_name=child.ClassName or "Window",
                            process_id=child.ProcessId or 0,
                            bounds=UIElementBounds(x=x, y=y, width=w, height=h),
                            is_active=child.HasKeyboardFocus,
                            is_minimized=False,
                            is_maximized=False,
                            is_visible=True,
                            timestamp=datetime.now(UTC),
                        )
                    )

            return tuple(wins) if wins else FakeUIInspectionBackend().list_windows()
        except Exception as e:
            logger.warning(f"[UI BACKEND FAIL-SAFE] Fallo al listar ventanas nativas ({e}). Delegando a FakeUIInspectionBackend.")
            return FakeUIInspectionBackend().list_windows()

    def inspect_ui(self, request: UIElementRequest) -> UIInspectionResult:
        """Inspecciona los elementos visuales utilizando Windows UI Automation con fallback limpio."""
        try:
            import uiautomation as auto  # type: ignore
        except ImportError:
            logger.warning("[UI BACKEND] uiautomation no está disponible. Delegando a FakeUIInspectionBackend.")
            return FakeUIInspectionBackend().inspect_ui(request)

        try:
            start_t = datetime.now(UTC)
            root_ctrl = auto.GetRootControl()

            if request.window_title:
                win_ctrl = auto.WindowControl(searchDepth=2, Name=request.window_title)
                if win_ctrl.Exists(maxSearchSeconds=1):
                    root_ctrl = win_ctrl

            elements_flat: list[UIElementInfo] = []

            def build_info(ctrl: auto.Control, depth: int) -> UIElementInfo:
                rect = ctrl.BoundingRectangle
                x = max(0, rect.left) if rect else 0
                y = max(0, rect.top) if rect else 0
                w = max(1, rect.width()) if rect else 1
                h = max(1, rect.height()) if rect else 1

                bounds = UIElementBounds(x=x, y=y, width=w, height=h)
                ctype = UIControlType.from_str(ctrl.ControlTypeName)

                children_list: list[UIElementInfo] = []
                if depth < request.max_depth and len(elements_flat) < request.max_elements:
                    for child in ctrl.GetChildren():
                        if len(elements_flat) >= request.max_elements:
                            break
                        children_list.append(build_info(child, depth + 1))

                info = UIElementInfo(
                    automation_id=ctrl.AutomationId or "",
                    name=ctrl.Name or "",
                    control_type=ctype,
                    class_name=ctrl.ClassName or "",
                    bounds=bounds,
                    is_enabled=ctrl.IsEnabled,
                    is_offscreen=ctrl.IsOffscreen,
                    has_keyboard_focus=ctrl.HasKeyboardFocus,
                    process_id=ctrl.ProcessId or 0,
                    framework_id=ctrl.FrameworkId or "",
                    children=tuple(children_list),
                )
                elements_flat.append(info)
                return info

            root_info = build_info(root_ctrl, 1)
            proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000

            metadata = UIInspectionMetadata(
                element_count=len(elements_flat),
                max_depth_reached=request.max_depth,
                processing_time_ms=proc_ms,
                backend_name="WindowsUIAutomationBackend",
                timestamp=datetime.now(UTC),
            )

            return UIInspectionResult(
                tree=UIElementTree(root=root_info),
                elements_flat=tuple(elements_flat),
                metadata=metadata,
                truncated=len(elements_flat) >= request.max_elements,
            )
        except Exception as e:
            logger.warning(f"[UI BACKEND FAIL-SAFE] Fallo durante la inspección nativa UI ({e}). Delegando a FakeUIInspectionBackend.")
            return FakeUIInspectionBackend().inspect_ui(request)
