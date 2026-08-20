"""Servicio seguro de visión y capturas de escritorio (DesktopService - Subetapa 08.1).

GARANTÍA ABSOLUTA DE PRIVACIDAD:
El AuditLogger y el EventBus reciben ÚNICAMENTE METADATOS de la captura (ancho, alto, recuento de píxeles,
duración, backend). NUNCA registran datos binarios de la imagen ni cadenas Base64.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.desktop_models import ScreenshotRequest, ScreenshotResult
from core.desktop_security import DesktopSecurityManager
from core.event_bus import get_event_bus
from core.logger import get_logger
from tools.desktop.backend import (
    IDesktopCaptureBackend,
    WindowsDesktopCaptureBackend,
)

logger = get_logger("jessyca.tools.desktop.service")


class DesktopService:
    """Servicio de operaciones seguras de visión y captura de pantalla de escritorio."""

    def __init__(
        self,
        backend: IDesktopCaptureBackend | None = None,
        security_manager: DesktopSecurityManager | None = None,
    ) -> None:
        self.backend = backend or WindowsDesktopCaptureBackend()
        self.security_manager = security_manager or DesktopSecurityManager()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def take_screenshot(self, request: ScreenshotRequest, request_id: str | None = None) -> ScreenshotResult:
        """Valida y ejecuta una captura de pantalla segura del escritorio."""
        req_id = request_id or "desktop-req-unknown"
        start_time = datetime.now(UTC)

        self.event_bus.publish("desktop:capture_requested", {"request_id": req_id, "format": request.format})

        # 1. Validar parámetros de captura con DesktopSecurityManager (FAIL-SAFE DENY)
        validated_req = self.security_manager.validate_request(request)
        self.event_bus.publish("desktop:capture_validated", {"request_id": req_id, "validated": True})

        # 2. Invocación segura del backend de captura desacoplado
        self.event_bus.publish("desktop:capture_started", {"request_id": req_id})
        result = self.backend.capture_screenshot(validated_req)

        duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

        # 3. Auditoría y eventos (ÚNICAMENTE METADATOS, CERO BYTES DE IMAGEN / CERO BASE64)
        meta_dict = result.metadata.to_dict()
        meta_dict["duration_ms"] = duration

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.DESKTOP_CAPTURE_SUCCEEDED,
                request_id=req_id,
                tool_name="windows.desktop",
                operation="take_screenshot",
                duration_ms=duration,
                reason="Captura de pantalla realizada exitosamente.",
                metadata=meta_dict,
            )
        )

        self.event_bus.publish("desktop:capture_completed", {"request_id": req_id, "metadata": meta_dict})
        return result
