"""Motor de políticas y evaluación de riesgo para acciones proactivas (proactive_policy.py - Fase 27).

Implementa la cadena formal de evaluación:
EVENT VALIDATION -> POLICY -> RISK -> PERMISSION -> ACTION DECISION

INVARIANTE DE SEGURIDAD ABSOLUTA:
JESSYCA jamás ejecuta acciones sensibles o destructivas (MEDIUM, HIGH, CRITICAL)
de forma proactiva sin solicitar confirmación interactiva humana.
"""

from __future__ import annotations

from core.logger import get_logger
from core.permission_manager import (
    PermissionDecision,
    PermissionManager,
)
from core.proactive.proactive_models import (
    ProactiveActionType,
    ProactiveEvent,
    ProactiveEventType,
    ProactivePolicyDecision,
)
from core.risk_engine import RiskEngine
from core.security_architecture import (
    SecurityContext,
    SecurityLevel,
    SecurityRequest,
    ToolSecurityMetadata,
)

logger = get_logger("jessyca.proactive.policy")


class ProactivePolicyEngine:
    """Motor de decisión que evalúa el riesgo y autorización de eventos proactivos."""

    def __init__(
        self,
        risk_engine: RiskEngine | None = None,
        permission_manager: PermissionManager | None = None,
    ) -> None:
        self.risk_engine = risk_engine or RiskEngine()
        self.permission_manager = permission_manager or PermissionManager()

    def evaluate_event(self, event: ProactiveEvent) -> ProactivePolicyDecision:
        """Evalúa un evento proactivo determinando el nivel de riesgo y la acción autorizada."""
        # 1. Si no hay herramienta propuesta (evento puramente informativo o notificación)
        if not event.proposed_tool:
            return self._evaluate_informational_event(event)

        # 2. Si hay herramienta propuesta -> Evaluar a través de la frontera de seguridad
        return self._evaluate_tool_action_event(event)

    def _evaluate_informational_event(self, event: ProactiveEvent) -> ProactivePolicyDecision:
        """Evalúa eventos informativos sin ejecución de herramientas."""
        if event.event_type == ProactiveEventType.TASK_COMPLETED:
            msg = f"La tarea '{event.payload.get('task_id', 'desconocida')}' terminó exitosamente."
            if event.summary:
                msg += f" {event.summary}"
            return ProactivePolicyDecision(
                event_id=event.event_id,
                action_type=ProactiveActionType.NOTIFY_USER,
                risk_level=SecurityLevel.SAFE,
                allowed=True,
                reason="Notificación de finalización de tarea.",
                user_message=msg,
                confirmation_required=False,
            )

        if event.event_type == ProactiveEventType.TASK_FAILED:
            msg = f"La tarea '{event.payload.get('task_id', 'desconocida')}' falló o fue cancelada."
            if event.summary:
                msg += f" Detalle: {event.summary}"
            return ProactivePolicyDecision(
                event_id=event.event_id,
                action_type=ProactiveActionType.NOTIFY_USER,
                risk_level=SecurityLevel.SAFE,
                allowed=True,
                reason="Notificación de fallo o cancelación de tarea.",
                user_message=msg,
                confirmation_required=False,
            )

        if event.event_type in (ProactiveEventType.SYSTEM_ERROR, ProactiveEventType.HEALTH_ALERT):
            msg = f"Alerta del sistema detectada: {event.summary}"
            return ProactivePolicyDecision(
                event_id=event.event_id,
                action_type=ProactiveActionType.NOTIFY_USER,
                risk_level=SecurityLevel.SAFE,
                allowed=True,
                reason="Notificación de diagnóstico/alerta de salud del sistema.",
                user_message=msg,
                confirmation_required=False,
            )

        # Notificación genérica permitida
        return ProactivePolicyDecision(
            event_id=event.event_id,
            action_type=ProactiveActionType.NOTIFY_USER,
            risk_level=SecurityLevel.SAFE,
            allowed=True,
            reason="Notificación informativa proactiva.",
            user_message=event.summary or "Notificación del asistente.",
            confirmation_required=False,
        )

    def _evaluate_tool_action_event(self, event: ProactiveEvent) -> ProactivePolicyDecision:
        """Evalúa un evento que propone ejecutar una acción/herramienta del sistema operativo."""
        tool_name = str(event.proposed_tool).strip()

        # Construir solicitud formal de seguridad para RiskEngine
        sec_context = SecurityContext(
            user="proactive_assistant",
            tool_name=tool_name,
            parameters=dict(event.tool_parameters),
        )
        sec_meta = ToolSecurityMetadata(
            tool_name=tool_name,
            category=tool_name.split(".")[0] if "." in tool_name else "system",
            risk_level=SecurityLevel.SAFE,  # Base para evaluación de RiskEngine
        )
        sec_req = SecurityRequest(context=sec_context, metadata=sec_meta)

        # 1. Evaluar riesgo en RiskEngine
        risk_assessment = self.risk_engine.evaluate_risk(sec_req)
        effective_risk = risk_assessment.risk_level

        # 2. Evaluar permisos en PermissionManager
        perm_decision = self.permission_manager.check_permission(
            tool_name=tool_name,
            risk_level=effective_risk,
        )

        # Si el PermissionManager deniega explícitamente -> SUPPRESS / DENY
        if perm_decision == PermissionDecision.DENY:
            logger.warning(
                f"[PROACTIVE SECURITY DENIAL] Herramienta '{tool_name}' denegada por permisos para evento '{event.event_id}'."
            )
            return ProactivePolicyDecision(
                event_id=event.event_id,
                action_type=ProactiveActionType.SUPPRESS,
                risk_level=effective_risk,
                allowed=False,
                reason=f"Acción proactiva '{tool_name}' denegada por PermissionManager (DENY).",
                user_message=f"Acción '{tool_name}' bloqueada por política de seguridad.",
                confirmation_required=False,
            )

        # 3. REGLA INMUTABLE: Acciones de riesgo MEDIUM, HIGH o CRITICAL JAMÁS se auto-ejecutan desatendidas
        if effective_risk in (SecurityLevel.MEDIUM, SecurityLevel.HIGH, SecurityLevel.CRITICAL) or perm_decision == PermissionDecision.REQUIRE_CONFIRMATION:
            confirm_msg = (
                f"Detecté una acción que requiere tu confirmación: '{tool_name}'. "
                f"Propósito: {event.summary or 'Mantenimiento del sistema'}. ¿Deseas autorizarla?"
            )
            logger.info(
                f"[PROACTIVE CONFIRMATION REQUIRED] Evento '{event.event_id}' con riesgo '{effective_risk.value}' requiere confirmación humana."
            )
            return ProactivePolicyDecision(
                event_id=event.event_id,
                action_type=ProactiveActionType.REQUEST_CONFIRMATION,
                risk_level=effective_risk,
                allowed=True,
                reason="Acción sensible o de riesgo medio/alto detectada proactivamente.",
                user_message=confirm_msg,
                confirmation_required=True,
                details={"tool_name": tool_name, "parameters": event.tool_parameters},
            )

        # 4. Acciones de riesgo SAFE / LOW permitidas desatendidamente
        return ProactivePolicyDecision(
            event_id=event.event_id,
            action_type=ProactiveActionType.SAFE_EXECUTE,
            risk_level=effective_risk,
            allowed=True,
            reason=f"Acción segura ({effective_risk.value}) autorizada para ejecución proactiva.",
            user_message=f"Ejecutando acción segura proactiva: '{tool_name}'.",
            confirmation_required=False,
            details={"tool_name": tool_name, "parameters": event.tool_parameters},
        )
