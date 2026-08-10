"""Frontera de seguridad para el control de aplicaciones de escritorio (Subetapa 11.1).

GARANTÍA ABSOLUTA DE SEGURIDAD Y PRIVACIDAD:
Interconecta el control de aplicaciones de escritorio con la tubería de autorización SecureExecutionPipeline,
RiskEngine, PermissionManager, EmergencyStopManager, AuditLogger y EventBus.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.application_models import ApplicationControlError
from core.application_session_manager import ApplicationSessionManager
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.permission_manager import PermissionDecision, PermissionManager
from core.risk_engine import RiskEngine, SecurityLevel

logger = get_logger("jessyca.core.application_boundary")


class ApplicationControlBoundary:
    """Frontera de seguridad para la ejecución autorizada y auditada de control de aplicaciones."""

    def __init__(
        self,
        session_manager: ApplicationSessionManager | None = None,
        emergency_stop_manager: EmergencyStopManager | None = None,
        permission_manager: PermissionManager | None = None,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self.session_manager = session_manager or ApplicationSessionManager()
        self.emergency_stop = emergency_stop_manager or get_emergency_stop_manager()
        self.permission_manager = permission_manager or PermissionManager()
        self.risk_engine = risk_engine or RiskEngine()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def execute_application_control(
        self,
        action: str,
        app_alias: str,
        args: tuple[str, ...] = (),
        request_id: str = "app-boundary-req",
    ) -> dict[str, Any]:
        """Ejecuta una operación sobre el ciclo de vida de una aplicación atravesando la frontera de seguridad."""
        start_time = datetime.now(UTC)
        act_clean = str(action).strip().lower()

        # 1. Comprobación inmediata de Parada de Emergencia (Fail-Safe)
        self.emergency_stop.check_cancellation(phase="validation")

        # 2. Evaluación de Riesgo y Permisos
        risk_level = SecurityLevel.WARNING if act_clean in ("launch", "focus") else SecurityLevel.DANGEROUS
        decision = self.permission_manager.check_permission(
            tool_name="windows.application",
            operation=act_clean,
            parameters={"app_alias": app_alias, "args": args},
            risk_level=risk_level,
        )

        if decision == PermissionDecision.DENY:
            raise ApplicationControlError(f"Operación de aplicación '{act_clean}' denegada por la política de seguridad.")

        # Re-verificación de Parada de Emergencia antes de la ejecución
        self.emergency_stop.check_cancellation(phase="execution")

        # 3. Invocación de la operación sobre el gestor de sesiones
        if act_clean in ("launch", "open", "start"):
            session = self.session_manager.launch_app(app_alias, args=args)
            msg = f"Aplicación '{app_alias}' gestionada correctamente (Session: {session.session_id}, State: {session.state})."
            res_dict = session.to_dict()

        elif act_clean in ("focus", "bring_to_front"):
            session = self.session_manager.focus_app(app_alias)
            msg = f"Foco asignado a la aplicación '{app_alias}' (Session: {session.session_id})."
            res_dict = session.to_dict()

        elif act_clean in ("close", "stop", "terminate"):
            success = self.session_manager.close_app(app_alias)
            msg = f"Aplicación '{app_alias}' cerrada exitosamente." if success else f"No se encontró una sesión activa para cerrar '{app_alias}'."
            res_dict = {"closed": success, "app_alias": app_alias}

        else:
            raise ApplicationControlError(f"Acción de control de aplicaciones no soportada: '{action}'")

        duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

        # 4. Registro de auditoría con PRIVACIDAD ABSOLUTA (METADATOS EXCLUSIVOS)
        audit_meta = {
            "action": act_clean,
            "app_alias": app_alias,
            "duration_ms": duration_ms,
            "result": res_dict,
        }

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.DESKTOP_ACTION_SUCCEEDED,
                request_id=request_id,
                tool_name="windows.application",
                operation=act_clean,
                duration_ms=duration_ms,
                reason=msg,
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("desktop:application_action_executed", audit_meta)
        return {
            "success": True,
            "action": act_clean,
            "app_alias": app_alias,
            "session": res_dict,
            "message": msg,
        }
