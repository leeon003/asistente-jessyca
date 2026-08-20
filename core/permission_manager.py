"""Permission Manager para Jessyca Windows MCP (Subetapa 04.3).

Componente de evaluación de autorización desacoplado.
Su única responsabilidad es responder: "¿Esta operación está autorizada?"
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from core.logger import get_logger
from core.risk_engine import RiskAssessment
from core.security_architecture import (
    SecurityContext,
    SecurityLevel,
    ToolSecurityMetadata,
)
from core.types import JSONDict

logger = get_logger("jessyca.security.permission_manager")


class PermissionDecision(StrEnum):
    """Decisiones formales de autorización devueltas por el PermissionManager."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    ALLOW_ONCE = "ALLOW_ONCE"
    ALWAYS_ALLOW = "ALWAYS_ALLOW"


class PermissionSource(StrEnum):
    """Origen de la regla o justificación de autorización."""

    DEFAULT = "DEFAULT"
    TOOL = "TOOL"
    OPERATION = "OPERATION"
    SESSION = "SESSION"
    USER = "USER"
    SYSTEM = "SYSTEM"


@dataclass
class PermissionRequest:
    """Solicitud formal de autorización enviada al PermissionManager."""

    context: SecurityContext
    metadata: ToolSecurityMetadata
    risk_assessment: RiskAssessment
    tool_name: str
    operation: str
    parameters: JSONDict = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class PermissionResult:
    """Resultado formal retornado por la evaluación del PermissionManager."""

    decision: PermissionDecision
    is_allowed: bool
    reason: str
    source: PermissionSource = PermissionSource.DEFAULT
    expiration_ms: float | None = None
    correlation_id: str = ""
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class IPermissionManager(Protocol):
    """Protocolo/Interfaz abstracta para el gestor de permisos y autorizaciones (DIP)."""

    def evaluate_permission(self, request: PermissionRequest) -> PermissionResult:
        """Evalúa una solicitud de permiso y devuelve el resultado de autorización."""
        ...


class PermissionManager:
    """Gestor principal de evaluación de autorizaciones (Subetapa 04.3)."""

    def __init__(self) -> None:
        logger.info("Inicializando PermissionManager (Subetapa 04.3)...")

    def evaluate_permission(self, request: PermissionRequest) -> PermissionResult:
        """Evalúa deterministamente si la operación solicitada está autorizada.

        Aplica una estrategia Fail-Safe (DEFAULT DENY) ante entradas ambiguas o inválidas.
        NO realiza ejecuciones de herramientas ni interacciones con el usuario.
        """
        correlation_id = request.context.correlation_id if request.context else ""

        # 1. Estrategia Fail-Safe / Validación de estructura
        if not request.context or not request.metadata or not request.risk_assessment:
            logger.warning("Fail-Safe activado: Solicitud de autorización incompleta o inválida -> DENY")
            return PermissionResult(
                decision=PermissionDecision.DENY,
                is_allowed=False,
                reason="Fail-Safe: La solicitud carece de contexto, metadatos o análisis de riesgo válido.",
                source=PermissionSource.SYSTEM,
                correlation_id=correlation_id,
            )

        tool_name = request.tool_name or request.metadata.tool_name
        operation = request.operation or request.metadata.category
        risk = request.risk_assessment

        # Normalizar nivel de riesgo a string para comparación determinista
        risk_level_str = str(getattr(risk.risk_level, "value", risk.risk_level)).upper().strip()

        # 2. Evaluación por Nivel de Riesgo y Metadatos
        if risk_level_str == "CRITICAL" or request.metadata.requires_elevation:
            logger.info(f"Autorización denegada para '{tool_name}' [Riesgo: CRITICAL / Requiere Elevación]")
            return PermissionResult(
                decision=PermissionDecision.DENY,
                is_allowed=False,
                reason=f"La operación '{operation}' en '{tool_name}' requiere elevación de privilegios (UAC/Admin).",
                source=PermissionSource.SYSTEM,
                correlation_id=correlation_id,
            )

        if risk_level_str == "DANGEROUS" or request.metadata.requires_confirmation:
            logger.info(f"Autorización requiere confirmación para '{tool_name}' [Riesgo: DANGEROUS]")
            return PermissionResult(
                decision=PermissionDecision.REQUIRE_CONFIRMATION,
                is_allowed=False,
                reason=f"La operación '{operation}' en '{tool_name}' es potencialmente riesgosa y exige confirmación previa.",
                source=PermissionSource.SYSTEM,
                correlation_id=correlation_id,
            )

        if risk_level_str == "WARNING":
            # Si es una operación específica temporal de modificación
            if "delete" in operation.lower() or "write" in operation.lower():
                logger.info(f"Autorización temporal ALLOW_ONCE concedida para '{tool_name}'")
                return PermissionResult(
                    decision=PermissionDecision.ALLOW_ONCE,
                    is_allowed=True,
                    reason=f"Operación de riesgo moderado '{operation}' autorizada para un único uso.",
                    source=PermissionSource.OPERATION,
                    expiration_ms=60000.0,
                    correlation_id=correlation_id,
                )
            logger.info(f"Autorización ALLOW concedida para '{tool_name}' [Riesgo: WARNING]")
            return PermissionResult(
                decision=PermissionDecision.ALLOW,
                is_allowed=True,
                reason=f"Operación '{operation}' en '{tool_name}' autorizada en contexto moderado.",
                source=PermissionSource.OPERATION,
                correlation_id=correlation_id,
            )

        if risk_level_str in ("SAFE", "READ_ONLY"):
            logger.info(f"Autorización ALLOW por defecto para '{tool_name}' [Riesgo: SAFE]")
            return PermissionResult(
                decision=PermissionDecision.ALLOW,
                is_allowed=True,
                reason=f"Operación segura '{operation}' autorizada por defecto.",
                source=PermissionSource.DEFAULT,
                correlation_id=correlation_id,
            )

        # 3. Estrategia Fail-Safe Final ante niveles desconocidos
        logger.warning(f"Fail-Safe activado: Nivel de riesgo desconocido '{risk_level_str}' -> DENY")
        return PermissionResult(
            decision=PermissionDecision.DENY,
            is_allowed=False,
            reason=f"Fail-Safe: Nivel de riesgo irreconocible '{risk_level_str}'. Operación denegada.",
            source=PermissionSource.SYSTEM,
            correlation_id=correlation_id,
        )

    def check_permission(
        self,
        tool_name: str,
        operation: str = "execute",
        parameters: dict[str, Any] | None = None,
        risk_level: SecurityLevel | RiskLevel = SecurityLevel.SAFE,
        user: str = "user",
    ) -> PermissionDecision:
        """Método de conveniencia para verificar permisos directos."""
        from core.risk_engine import RiskAssessment
        from core.security_architecture import SecurityContext, ToolSecurityMetadata
        req = PermissionRequest(
            context=SecurityContext(user=user, tool_name=tool_name, parameters=parameters or {}),
            metadata=ToolSecurityMetadata(tool_name=tool_name, category=operation),
            risk_assessment=RiskAssessment(risk_level=risk_level),
            tool_name=tool_name,
            operation=operation,
        )
        res = self.evaluate_permission(req)
        return res.decision
