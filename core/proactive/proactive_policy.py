"""Motor de políticas y evaluación de riesgo para acciones proactivas (proactive_policy.py - Fase 44).

Implementa la cadena formal de evaluación:
EVENT VALIDATION -> SECURITY POLICY -> RISK ENGINE -> PERMISSION MANAGER -> AUTONOMY POLICY -> ACTION DECISION

PRINCIPIO INMUTABLE:
PROACTIVE != UNCONTROLLED AUTONOMY
JESSYCA jamás ejecuta acciones sensibles o destructivas (MEDIUM, HIGH, CRITICAL)
de forma proactiva sin solicitar confirmación interactiva humana.
"""

from __future__ import annotations

from core.autonomy.autonomy_decision import AutonomyDecisionValue
from core.autonomy.autonomy_level import AutonomyLevel
from core.autonomy.autonomy_policy import AutonomyEvaluationContext, AutonomyPolicy
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
        autonomy_policy: AutonomyPolicy | None = None,
    ) -> None:
        self.risk_engine = risk_engine or RiskEngine()
        self.permission_manager = permission_manager or PermissionManager()
        self.autonomy_policy = autonomy_policy or AutonomyPolicy(permission_manager=self.permission_manager)

    def evaluate_event(
        self,
        event: ProactiveEvent,
        current_autonomy_level: AutonomyLevel = AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION,
    ) -> ProactivePolicyDecision:
        """Evalúa un evento proactivo determinando el nivel de riesgo y la acción autorizada."""
        # 1. Si no hay herramienta propuesta (evento puramente informativo o notificación)
        if not event.proposed_tool:
            return self._evaluate_informational_event(event)

        # 2. Si hay herramienta propuesta -> Evaluar a través de la frontera de seguridad y autonomía
        return self._evaluate_tool_action_event(event, current_autonomy_level)

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

        if event.event_type == ProactiveEventType.CALENDAR_UPCOMING:
            doc = event.payload.get("related_document")
            title = event.payload.get("meeting_title", "Reunión")
            if doc:
                msg = f"Tienes una reunión próximamente ('{title}') y existe un documento relacionado: '{doc}'."
            else:
                msg = f"Tienes una reunión próximamente: '{title}'."
            return ProactivePolicyDecision(
                event_id=event.event_id,
                action_type=ProactiveActionType.NOTIFY_USER,
                risk_level=SecurityLevel.SAFE,
                allowed=True,
                reason="Notificación informativa de calendario.",
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

    def _evaluate_tool_action_event(
        self,
        event: ProactiveEvent,
        current_autonomy_level: AutonomyLevel = AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION,
    ) -> ProactivePolicyDecision:
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

        # 3. Evaluar con AutonomyPolicy
        autonomy_ctx = AutonomyEvaluationContext(
            task_id=f"proactive-{event.event_id}",
            tool_name=tool_name,
            operation=tool_name.split(".")[-1] if "." in tool_name else "execute",
            parameters=dict(event.tool_parameters),
            task_source="proactive_assistant",
            is_scheduled=event.event_type == ProactiveEventType.SCHEDULED_TASK,
        )
        autonomy_decision = self.autonomy_policy.evaluate(
            context=autonomy_ctx,
            current_level=current_autonomy_level,
        )

        if autonomy_decision.decision == AutonomyDecisionValue.DENY:
            logger.warning(
                f"[PROACTIVE AUTONOMY DENIAL] Acción '{tool_name}' denegada por AutonomyPolicy: {autonomy_decision.reason}"
            )
            return ProactivePolicyDecision(
                event_id=event.event_id,
                action_type=ProactiveActionType.SUPPRESS,
                risk_level=effective_risk,
                allowed=False,
                reason=f"Acción '{tool_name}' no autorizada por AutonomyPolicy: {autonomy_decision.reason}",
                user_message=f"Acción '{tool_name}' no permitida bajo la política de autonomía actual.",
                confirmation_required=False,
            )

        # 4. REGLA INMUTABLE: Acciones de riesgo MEDIUM, HIGH o CRITICAL, o si AutonomyPolicy/Risk exige confirmación
        if (
            effective_risk in (SecurityLevel.MEDIUM, SecurityLevel.HIGH, SecurityLevel.CRITICAL)
            or perm_decision == PermissionDecision.REQUIRE_CONFIRMATION
            or autonomy_decision.requires_confirmation
            or autonomy_decision.decision in (AutonomyDecisionValue.REQUIRE_CONFIRMATION, AutonomyDecisionValue.REQUIRE_REVIEW)
        ):
            # Caso especial amigable (ejemplo de calendario / documento)
            if event.event_type == ProactiveEventType.CALENDAR_UPCOMING and event.payload.get("related_document"):
                doc_name = event.payload.get("related_document")
                confirm_msg = f"Encontré el documento relacionado ('{doc_name}'). ¿Quieres que lo abra?"
                action_type = ProactiveActionType.SUGGEST_ACTION
            else:
                confirm_msg = (
                    f"Detecté una acción que requiere tu confirmación: '{tool_name}'. "
                    f"Propósito: {event.summary or 'Mantenimiento del sistema'}. ¿Deseas autorizarla?"
                )
                action_type = ProactiveActionType.REQUEST_CONFIRMATION

            logger.info(
                f"[PROACTIVE CONFIRMATION REQUIRED] Evento '{event.event_id}' ({tool_name}, riesgo: {effective_risk.value}) requiere confirmación/propuesta humana."
            )
            return ProactivePolicyDecision(
                event_id=event.event_id,
                action_type=action_type,
                risk_level=effective_risk,
                allowed=True,
                reason="Acción proactiva que requiere confirmación o propuesta al usuario.",
                user_message=confirm_msg,
                confirmation_required=True,
                details={"tool_name": tool_name, "parameters": event.tool_parameters},
            )

        # 5. Acciones de riesgo SAFE / LOW permitidas desatendidamente
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
