"""Servicio seguro de automatización de acciones de escritorio (DesktopAutomationService - Subetapa 08.4).

GARANTÍA ABSOLUTA DE PRIVACIDAD Y SEGURIDAD:
El AuditLogger y el EventBus reciben ÚNICAMENTE METADATOS de la acción (tipo de acción, resumen del target,
fingerprint, tiempo de procesamiento, backend).
INVARIANTE CRÍTICO: NUNCA registran el texto escrito en acciones type_text ni credenciales introducidas.
"""

from __future__ import annotations

from datetime import UTC, datetime

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.desktop_automation_models import (
    DesktopActionMetadata,
    DesktopActionRequest,
    DesktopActionResult,
)
from core.desktop_automation_security import DesktopAutomationSecurityManager
from core.emergency_stop import get_emergency_stop_manager
from core.event_bus import get_event_bus
from core.logger import get_logger
from server.evidence import AuthorizationEvidence
from tools.desktop.automation_backend import (
    FakeDesktopAutomationBackend,
    IDesktopAutomationBackend,
    WindowsDesktopAutomationBackend,
)

logger = get_logger("jessyca.tools.desktop.automation_service")


class DesktopAutomationService:
    """Servicio de orquestación y frontera de automatización de acciones sobre el escritorio."""

    def __init__(
        self,
        backend: IDesktopAutomationBackend | None = None,
        security_manager: DesktopAutomationSecurityManager | None = None,
    ) -> None:
        settings = AppSettings()
        self.backend = backend or WindowsDesktopAutomationBackend()
        self.security_manager = security_manager or DesktopAutomationSecurityManager()
        self.emergency_stop = get_emergency_stop_manager()
        self.max_actions = settings.DESKTOP_AUTOMATION_MAX_ACTIONS
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def execute_action(
        self,
        request: DesktopActionRequest,
        evidence: AuthorizationEvidence,
        request_id: str | None = None,
    ) -> DesktopActionResult:
        """Valida la autorización, huella criptográfica y realiza la ejecución de la acción UI."""
        req_id = request_id or evidence.request_id or "automation-req-unknown"
        start_time = datetime.now(UTC)

        self.event_bus.publish("desktop:action_requested", {"request_id": req_id, "action_type": request.action_type.value})

        # 1. VERIFICACIÓN CRÍTICA DE PARADA DE EMERGENCIA
        if self.emergency_stop.is_active():
            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.DESKTOP_ACTION_EMERGENCY_STOP,
                    request_id=req_id,
                    tool_name="windows.desktop",
                    operation=request.action_type.value,
                    duration_ms=0.0,
                    reason="Acción bloqueada por Parada de Emergencia activa.",
                    metadata={"status": "DENIED_EMERGENCY_STOP"},
                )
            )
            self.event_bus.publish("desktop:action_emergency_stop", {"request_id": req_id})
            raise RuntimeError("PARADA DE EMERGENCIA ACTIVA: Operación bloqueada de forma estricta.")

        # 2. Validación de parámetros y huella SHA-256 (Fingerprint Verification)
        validated_req = self.security_manager.validate_request(request)
        self.security_manager.verify_fingerprint(validated_req, evidence.action_fingerprint, req_id)
        self.security_manager.verify_target_freshness(validated_req)

        self.event_bus.publish("desktop:action_validated", {"request_id": req_id, "validated": True})

        # 3. Invocación segura del backend desacoplado
        self.event_bus.publish("desktop:action_started", {"request_id": req_id, "action_type": request.action_type.value})
        result = self.backend.execute_action(validated_req, request_id=req_id)

        duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

        # 4. Auditoría y eventos (ÚNICAMENTE METADATOS, CERO TEXTO DE TYPE_TEXT EN LOGS)
        audit_meta = result.metadata.to_dict()
        if request.text is not None:
            audit_meta["text_length"] = len(request.text)
            audit_meta["text_redacted"] = True

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.DESKTOP_ACTION_SUCCEEDED,
                request_id=req_id,
                tool_name="windows.desktop",
                operation=request.action_type.value,
                duration_ms=duration,
                reason="Acción gráfica de escritorio ejecutada exitosamente.",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("desktop:action_completed", {"request_id": req_id, "metadata": audit_meta})
        return result
