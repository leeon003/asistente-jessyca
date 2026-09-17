"""Frontera de Seguridad para la Capa de Integraciones (Security Boundary).

Garantiza que ninguna llamada hacia un Integration Adapter pueda omitir las políticas de
seguridad globales, listas negras, niveles de riesgo (RiskLevel) ni comprobación de permisos.
Actúa como guardián estricto antes de cualquier ejecución externa.
"""

from __future__ import annotations

from typing import Any

from core.execution.execution_verifier import ExecutionStatus
from core.integration.adapter import IntegrationAdapter
from core.integration.models import (
    IntegrationCapability,
    IntegrationContext,
    IntegrationExecutionResult,
)
from core.logger import get_logger
from core.security import (
    RiskLevel,
    SecurityDecision,
    SecurityManager,
    SecurityStatus,
    ToolSecurityProfile,
)

logger = get_logger("jessyca.integration.security")

SENSITIVE_KEYS = {
    "password",
    "token",
    "auth_token",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "credential",
    "private_key",
}


def sanitize_context_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    """Filtra y ofusca campos sensibles antes de registrarlos en auditoría o logs."""
    sanitized: dict[str, Any] = {}
    for k, v in parameters.items():
        if any(s in k.lower() for s in SENSITIVE_KEYS):
            sanitized[k] = "***REDACTED***"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_context_parameters(v)
        else:
            sanitized[k] = v
    return sanitized


class IntegrationSecurityBoundary:
    """Frontera y validador de seguridad para ejecuciones de integración."""

    def __init__(self, security_manager: SecurityManager | None = None) -> None:
        self._security_manager = security_manager or SecurityManager()

    @property
    def security_manager(self) -> SecurityManager:
        return self._security_manager

    def evaluate_execution(
        self,
        adapter: IntegrationAdapter,
        capability: IntegrationCapability,
        context: IntegrationContext,
    ) -> tuple[bool, SecurityDecision | None]:
        """Evalúa si la ejecución de una capacidad de un adapter está autorizada.

        Args:
            adapter: El IntegrationAdapter involucrado.
            capability: La IntegrationCapability solicitada.
            context: Contexto de ejecución y parámetros.

        Returns:
            Tuple (is_allowed: bool, decision: SecurityDecision).
        """
        tool_identifier = f"{adapter.name}.{capability.name}"
        profile = ToolSecurityProfile(
            name=tool_identifier,
            category=adapter.name,
            risk_level=capability.required_risk_level,
            required_permissions=capability.required_permissions,
            requires_confirmation=(capability.required_risk_level in (RiskLevel.DANGEROUS, RiskLevel.CRITICAL)),
        )

        safe_args = sanitize_context_parameters(context.parameters)
        decision = self._security_manager.evaluate(
            profile=profile,
            user=context.user_id,
            arguments=safe_args,
            action="execute_integration_capability",
        )

        if not decision.is_allowed:
            logger.warning(
                f"[SECURITY_BOUNDARY] Ejecución denegada para '{tool_identifier}'. "
                f"Estado: {decision.status}. Razón: {decision.reason}"
            )
            return False, decision

        logger.debug(f"[SECURITY_BOUNDARY] Ejecución autorizada para '{tool_identifier}'.")
        return True, decision

    def create_denied_result(
        self,
        capability_name: str,
        decision: SecurityDecision,
        duration_ms: float = 0.0,
    ) -> IntegrationExecutionResult:
        """Construye un IntegrationExecutionResult formal para ejecuciones denegadas."""
        return IntegrationExecutionResult(
            executed=False,
            verified=False,
            verification_required=False,
            status=ExecutionStatus.DENIED,
            error=f"Seguridad denegó la ejecución: {decision.reason}",
            duration_ms=duration_ms,
            metadata={
                "security_status": decision.status.value if isinstance(decision.status, SecurityStatus) else str(decision.status),
                "action": decision.action.value if hasattr(decision.action, "value") else str(decision.action),
                "capability": capability_name,
            },
        )
