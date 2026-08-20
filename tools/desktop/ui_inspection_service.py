"""Servicio seguro de inspección visual de elementos UI (UIInspectionService - Subetapa 08.3).

GARANTÍA ABSOLUTA DE PRIVACIDAD Y SEGURIDAD:
El AuditLogger y el EventBus reciben ÚNICAMENTE METADATOS de la inspección (conteo de elementos,
profundidad alcanzada, tiempo de procesamiento, backend).
NUNCA registran el árbol UI completo, cadenas crudas ni textos con secretos.
INSPECCIÓN PURA (READ-ONLY): CERO click, CERO teclado, CERO alteración de ventanas.
"""

from __future__ import annotations

from datetime import UTC, datetime

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.ocr_sanitizer import OCRTextSanitizer
from core.ui_inspection_models import (
    UIElementInfo,
    UIElementRequest,
    UIElementTree,
    UIInspectionMetadata,
    UIInspectionResult,
    WindowInfo,
)
from core.ui_inspection_security import UIInspectionSecurityManager
from tools.desktop.ui_backend import (
    IUIInspectionBackend,
    WindowsUIAutomationBackend,
)

logger = get_logger("jessyca.tools.desktop.ui_inspection_service")


class UIInspectionService:
    """Servicio de inspección y sanitización visual de elementos UI."""

    def __init__(
        self,
        backend: IUIInspectionBackend | None = None,
        security_manager: UIInspectionSecurityManager | None = None,
        sanitizer: OCRTextSanitizer | None = None,
    ) -> None:
        settings = AppSettings()
        self.backend = backend or WindowsUIAutomationBackend()
        self.security_manager = security_manager or UIInspectionSecurityManager()
        self.sanitizer = sanitizer or OCRTextSanitizer()
        self.max_elements = settings.UI_MAX_ELEMENTS
        self.max_tree_depth = settings.UI_MAX_TREE_DEPTH
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def inspect_ui_elements(
        self,
        request: UIElementRequest,
        request_id: str | None = None,
    ) -> UIInspectionResult:
        """Valida, consulta el backend UI, sanitiza nombres/secretos y trunca la respuesta si excede límites."""
        req_id = request_id or "ui-inspect-req-unknown"
        start_time = datetime.now(UTC)

        self.event_bus.publish("desktop:ui_inspection_requested", {"request_id": req_id, "window_title": request.window_title})

        # 1. Validación de parámetros con UIInspectionSecurityManager (FAIL-SAFE DENY)
        validated_req = self.security_manager.validate_request(request)
        self.event_bus.publish("desktop:ui_inspection_validated", {"request_id": req_id, "validated": True})

        # 2. Consulta de elementos UI mediante backend desacoplado (READ-ONLY)
        self.event_bus.publish("desktop:ui_inspection_started", {"request_id": req_id})
        raw_result = self.backend.inspect_ui(validated_req)

        # 3. Sanitización de textos/nombres de elementos y validación de bounding boxes
        total_redactions = 0
        elements_sanitized: list[UIElementInfo] = []

        def sanitize_node(node: UIElementInfo, depth: int) -> UIElementInfo | None:
            nonlocal total_redactions
            if depth > self.max_tree_depth or len(elements_sanitized) >= self.max_elements:
                return None

            clean_name, count_name = self.sanitizer.sanitize_text(node.name)
            clean_auto_id, count_id = self.sanitizer.sanitize_text(node.automation_id)
            total_redactions += count_name + count_id

            valid_bounds = self.security_manager.validate_bounds(node.bounds)

            sanitized_children: list[UIElementInfo] = []
            for child in node.children:
                c_node = sanitize_node(child, depth + 1)
                if c_node:
                    sanitized_children.append(c_node)

            info = UIElementInfo(
                automation_id=clean_auto_id,
                name=clean_name,
                control_type=node.control_type,
                class_name=node.class_name,
                bounds=valid_bounds,
                is_enabled=node.is_enabled,
                is_offscreen=node.is_offscreen,
                has_keyboard_focus=node.has_keyboard_focus,
                process_id=node.process_id,
                framework_id=node.framework_id,
                children=tuple(sanitized_children),
            )
            elements_sanitized.append(info)
            return info

        sanitized_root = sanitize_node(raw_result.tree.root, 1) or raw_result.tree.root
        duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

        sanitized_metadata = UIInspectionMetadata(
            element_count=len(elements_sanitized),
            max_depth_reached=min(raw_result.metadata.max_depth_reached, self.max_tree_depth),
            processing_time_ms=duration,
            backend_name=raw_result.metadata.backend_name,
            timestamp=datetime.now(UTC),
        )

        truncated = len(elements_sanitized) >= self.max_elements or raw_result.truncated

        final_result = UIInspectionResult(
            tree=UIElementTree(root=sanitized_root),
            elements_flat=tuple(elements_sanitized),
            metadata=sanitized_metadata,
            truncated=truncated,
        )

        # 4. Auditoría y eventos (ÚNICAMENTE METADATOS, CERO RAW UI TREE / CERO SECRETOS)
        audit_meta = sanitized_metadata.to_dict()
        audit_meta["redactions_count"] = total_redactions
        audit_meta["truncated"] = truncated

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.UI_INSPECTION_SUCCEEDED,
                request_id=req_id,
                tool_name="windows.desktop",
                operation="inspect_ui_element",
                duration_ms=duration,
                reason="Inspección visual de elementos UI realizada y sanitizada exitosamente.",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("desktop:ui_inspection_completed", {"request_id": req_id, "metadata": audit_meta})
        return final_result

    def get_active_window(self, request_id: str | None = None) -> WindowInfo:
        """Obtiene la ventana activa en primer plano sanitizando el título."""
        win = self.backend.get_active_window()
        clean_title, _ = self.sanitizer.sanitize_text(win.title)
        sanitized_win = WindowInfo(
            hwnd=win.hwnd,
            title=clean_title,
            class_name=win.class_name,
            process_id=win.process_id,
            bounds=win.bounds,
            is_active=win.is_active,
            is_minimized=win.is_minimized,
            is_maximized=win.is_maximized,
            is_visible=win.is_visible,
            timestamp=win.timestamp,
        )
        req_id = request_id or "win-active-req"
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.UI_INSPECTION_SUCCEEDED,
                request_id=req_id,
                tool_name="windows.desktop",
                operation="get_active_window",
                duration_ms=1.0,
                reason="Consulta de ventana activa realizada exitosamente.",
                metadata={"hwnd": win.hwnd, "process_id": win.process_id},
            )
        )
        return sanitized_win

    def list_windows(self, request_id: str | None = None) -> tuple[WindowInfo, ...]:
        """Lista todas las ventanas visibles principales sanitizando sus títulos."""
        raw_wins = self.backend.list_windows()
        sanitized_wins: list[WindowInfo] = []
        for win in raw_wins:
            clean_title, _ = self.sanitizer.sanitize_text(win.title)
            sanitized_wins.append(
                WindowInfo(
                    hwnd=win.hwnd,
                    title=clean_title,
                    class_name=win.class_name,
                    process_id=win.process_id,
                    bounds=win.bounds,
                    is_active=win.is_active,
                    is_minimized=win.is_minimized,
                    is_maximized=win.is_maximized,
                    is_visible=win.is_visible,
                    timestamp=win.timestamp,
                )
            )
        req_id = request_id or "win-list-req"
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.UI_INSPECTION_SUCCEEDED,
                request_id=req_id,
                tool_name="windows.desktop",
                operation="list_windows",
                duration_ms=1.0,
                reason="Listado de ventanas realizado exitosamente.",
                metadata={"window_count": len(sanitized_wins)},
            )
        )
        return tuple(sanitized_wins)
