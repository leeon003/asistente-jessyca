"""Arquitectura Base de Seguridad (Subetapa 04.1) para Jessyca Windows MCP.

Define los modelos de dominio, niveles de seguridad, decisiones de autorización,
contextos de ejecución y el contrato abstracto ISecurityEvaluator desacoplado.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from core.logger import get_logger
from core.types import JSONDict

logger = get_logger("jessyca.security.architecture")


class SecurityLevel(StrEnum):
    """Niveles formales de riesgo e impacto para herramientas MCP."""

    SAFE = "SAFE"             # Operaciones seguras sin efectos colaterales graves
    WARNING = "WARNING"       # Operaciones de modificación moderada que requieren atención
    DANGEROUS = "DANGEROUS"   # Operaciones de alto impacto que requieren confirmación interactiva
    CRITICAL = "CRITICAL"     # Operaciones críticas que exigen elevación de privilegios UAC/Admin
    LOW = "SAFE"
    MEDIUM = "WARNING"
    HIGH = "DANGEROUS"


class SecurityDecisionType(StrEnum):
    """Decisiones posibles tras la evaluación de seguridad de una solicitud."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    REQUIRE_ELEVATED_AUTHORIZATION = "REQUIRE_ELEVATED_AUTHORIZATION"


@dataclass
class SecurityContext:
    """Contexto de seguridad que transporta los metadatos de la sesión y el entorno de ejecución."""

    user: str = "system"
    tool_name: str = ""
    parameters: JSONDict = field(default_factory=dict)
    session_id: str = ""
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    environment: str = "windows"

    def __post_init__(self) -> None:
        if not self.user.strip():
            raise ValueError("El campo 'user' en SecurityContext no puede estar vacío.")


@dataclass
class ToolSecurityMetadata:
    """Metadatos de seguridad declarados por cada herramienta MCP."""

    tool_name: str
    category: str = "general"
    risk_level: SecurityLevel = SecurityLevel.SAFE
    requires_confirmation: bool = False
    requires_elevation: bool = False
    allowed_operations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tool_name.strip():
            raise ValueError("El campo 'tool_name' en ToolSecurityMetadata no puede estar vacío.")


@dataclass
class SecurityRequest:
    """Solicitud formal de evaluación enviada a la capa de seguridad."""

    context: SecurityContext
    metadata: ToolSecurityMetadata
    action: str = "execute"
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class SecurityDecision:
    """Decisión detallada resultante del análisis de seguridad."""

    decision_type: SecurityDecisionType
    reason: str
    requires_user_confirmation: bool = False
    requires_elevation: bool = False

    def __bool__(self) -> bool:
        return self.decision_type == SecurityDecisionType.ALLOW


@dataclass
class SecurityResult:
    """Resultado consolidado devuelto por la evaluación de seguridad."""

    is_allowed: bool
    decision: SecurityDecision
    request_id: str
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class ISecurityEvaluator(Protocol):
    """Protocolo/Interfaz abstracta para el evaluador central de seguridad (DIP)."""

    def evaluate(self, request: SecurityRequest) -> SecurityResult:
        """Evalúa una solicitud de seguridad y devuelve el resultado consolidado."""
        ...


class BaseSecurityManager:
    """Implementación base desacoplada de la arquitectura del Security Manager (Subetapa 04.1)."""

    def __init__(self) -> None:
        logger.info("Inicializando BaseSecurityManager (Arquitectura Base 04.1)...")

    def evaluate(self, request: SecurityRequest) -> SecurityResult:
        """Evalúa una solicitud de seguridad según las reglas base de los metadatos declarados."""
        meta = request.metadata

        if meta.requires_elevation or meta.risk_level == SecurityLevel.CRITICAL:
            decision = SecurityDecision(
                decision_type=SecurityDecisionType.REQUIRE_ELEVATED_AUTHORIZATION,
                reason=f"La herramienta '{meta.tool_name}' [Riesgo: {meta.risk_level.value}] exige privilegios elevados (UAC/Admin).",
                requires_elevation=True,
            )
            is_allowed = False
        elif meta.requires_confirmation or meta.risk_level == SecurityLevel.DANGEROUS:
            decision = SecurityDecision(
                decision_type=SecurityDecisionType.REQUIRE_CONFIRMATION,
                reason=f"La herramienta '{meta.tool_name}' [Riesgo: {meta.risk_level.value}] exige confirmación del usuario.",
                requires_user_confirmation=True,
            )
            is_allowed = False
        else:
            decision = SecurityDecision(
                decision_type=SecurityDecisionType.ALLOW,
                reason=f"Ejecución de la herramienta '{meta.tool_name}' autorizada por la arquitectura base de seguridad.",
            )
            is_allowed = True

        logger.debug(
            f"Evaluación realizada [{request.request_id}] Tool: '{meta.tool_name}' -> Result: {decision.decision_type.value}"
        )

        return SecurityResult(
            is_allowed=is_allowed,
            decision=decision,
            request_id=request.request_id,
        )
