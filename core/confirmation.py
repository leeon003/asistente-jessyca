"""Mecanismo estructurado de solicitudes de confirmación para Jessyca Windows MCP.

Proporciona la creación, almacenamiento, consulta y resolución interactiva de solicitudes de confirmación
para operaciones de alto impacto (ej. 'Esta acción eliminará 25 archivos. ¿Deseas continuar?'),
con integración directa en el EventBus y SecurityManager.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.event_bus import EventBus, get_event_bus
from core.logger import get_logger
from core.security import (
    PermissionAction,
    RiskLevel,
    SecurityDecision,
    SecurityManager,
    ToolSecurityProfile,
)

if TYPE_CHECKING:
    pass

logger = get_logger("jessyca.confirmation")


@dataclass
class ConfirmationRequest:
    """Solicitud estructurada de confirmación para ser presentada al usuario o cliente MCP."""

    request_id: str
    tool_name: str
    message: str
    risk_level: RiskLevel
    impact_summary: dict[str, Any] = field(default_factory=dict)
    available_actions: list[PermissionAction] = field(
        default_factory=lambda: [
            PermissionAction.ALLOW_ONCE,
            PermissionAction.ALWAYS_ALLOW,
            PermissionAction.DENY,
        ]
    )
    status: str = "pending"  # "pending", "approved", "rejected"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ConfirmationResponse:
    """Respuesta del usuario a una solicitud de confirmación estructurada."""

    request_id: str
    selected_action: PermissionAction
    user_id: str = "user"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class ConfirmationManager:
    """Gestor central de solicitudes de confirmación estructuradas."""

    def __init__(
        self,
        security_manager: SecurityManager | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.security_manager = security_manager or SecurityManager()
        self.event_bus = event_bus or get_event_bus()
        self._pending_requests: dict[str, ConfirmationRequest] = {}
        self._resolved_requests: dict[str, ConfirmationRequest] = {}

    def create_request(
        self,
        tool_name: str,
        message: str,
        risk_level: RiskLevel = RiskLevel.DANGEROUS,
        impact_summary: dict[str, Any] | None = None,
        available_actions: list[PermissionAction] | None = None,
    ) -> ConfirmationRequest:
        """Crea y registra una nueva solicitud de confirmación estructurada.

        Args:
            tool_name: Nombre de la herramienta que requiere confirmación.
            message: Mensaje legible estructurado (ej. "Esta acción eliminará 25 archivos. ¿Deseas continuar?").
            risk_level: Nivel de riesgo asignado.
            impact_summary: Resumen explicativo del impacto (ej. {"file_count": 25, "action": "delete"}).
            available_actions: Opciones de acción disponibles para el usuario.

        Returns:
            ConfirmationRequest creado.
        """
        request_id = str(uuid.uuid4())
        actions = available_actions or [
            PermissionAction.ALLOW_ONCE,
            PermissionAction.ALWAYS_ALLOW,
            PermissionAction.DENY,
        ]

        req = ConfirmationRequest(
            request_id=request_id,
            tool_name=tool_name,
            message=message,
            risk_level=risk_level,
            impact_summary=impact_summary or {},
            available_actions=actions,
            status="pending",
        )

        self._pending_requests[request_id] = req
        logger.info(f"Solicitud de confirmación [{request_id}] creada para '{tool_name}': \"{message}\"")

        # Emitir evento en el EventBus
        self.event_bus.publish(
            "confirmation:requested",
            {
                "request_id": request_id,
                "tool_name": tool_name,
                "message": message,
                "risk_level": risk_level.value,
                "impact_summary": req.impact_summary,
            },
        )

        return req

    def get_pending_request(self, request_id: str) -> ConfirmationRequest | None:
        """Obtiene una solicitud de confirmación pendiente por su ID."""
        return self._pending_requests.get(request_id)

    def list_pending_requests(self) -> list[ConfirmationRequest]:
        """Obtiene la lista de todas las solicitudes de confirmación pendientes de respuesta."""
        return list(self._pending_requests.values())

    def resolve_request(
        self,
        request_id: str,
        selected_action: PermissionAction,
        profile: ToolSecurityProfile | None = None,
        user_id: str = "user",
    ) -> SecurityDecision:
        """Resuelve una solicitud de confirmación aplicando la acción elegida por el usuario.

        Args:
            request_id: ID único de la solicitud de confirmación.
            selected_action: Acción seleccionada (ALLOW, DENY, ALLOW_ONCE, ALWAYS_ALLOW).
            profile: Perfil opcional de la herramienta. Si no se proporciona, crea uno derivado.
            user_id: Identificador del usuario que responde.

        Returns:
            SecurityDecision de la resolución de seguridad.
        """
        req = self._pending_requests.pop(request_id, None)
        if req is None:
            raise KeyError(f"No se encontró solicitud de confirmación pendiente con ID: '{request_id}'")

        if selected_action in (PermissionAction.ALLOW, PermissionAction.ALLOW_ONCE, PermissionAction.ALWAYS_ALLOW):
            req.status = "approved"
        else:
            req.status = "rejected"

        self._resolved_requests[request_id] = req

        sec_profile = profile or ToolSecurityProfile(
            name=req.tool_name,
            category="general",
            risk_level=req.risk_level,
        )

        decision = self.security_manager.process_user_action(sec_profile, selected_action, user=user_id)
        decision.confirmation_request = req

        logger.info(
            f"Solicitud de confirmación [{request_id}] resuelta con acción '{selected_action.value}' (Estado: {req.status})."
        )

        # Emitir evento en el EventBus
        self.event_bus.publish(
            "confirmation:resolved",
            {
                "request_id": request_id,
                "tool_name": req.tool_name,
                "action": selected_action.value,
                "status": req.status,
                "user_id": user_id,
            },
        )

        return decision
