"""Sistema de Capabilities y Declaración de Herramientas (Subetapa 06.1).

Modelos declarativos inmutables y fuertemente tipados para el Capability System de Jessyca.
Garantiza que la definición de capacidades provenga exclusivamente de fuentes autorizadas
(SYSTEM, ADMINISTRATOR, CONFIGURATION, BUILTIN) y prohíbe fuentes no confiables (LLM, CLIENT, etc.).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.types import JSONDict


class CapabilitySource(StrEnum):
    """Fuentes legítimas autorizadas para la definición de Capabilities.

    Excluye explícitamente fuentes no confiables como LLM, USER_PROMPT, CLIENT o ASSISTANT.
    """

    SYSTEM = "SYSTEM"
    ADMINISTRATOR = "ADMINISTRATOR"
    CONFIGURATION = "CONFIGURATION"
    BUILTIN = "BUILTIN"


# Fuentes explícitamente prohibidas que NUNCA deben aceptarse como autoridad de capacidades
FORBIDDEN_CAPABILITY_SOURCES: set[str] = {
    "LLM",
    "USER_PROMPT",
    "CLIENT",
    "ASSISTANT",
    "UNTRUSTED",
    "EXTERNAL",
}


class CapabilityRiskLevel(StrEnum):
    """Nivel de riesgo inherente declarado para una operación de Capability."""

    SAFE = "SAFE"
    WARNING = "WARNING"
    DANGEROUS = "DANGEROUS"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class CapabilityDecision(StrEnum):
    """Decisión de autorización declarada para una operación de Capability."""

    ALLOW = "ALLOW"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    REQUIRE_ELEVATED_AUTHORIZATION = "REQUIRE_ELEVATED_AUTHORIZATION"
    DENY = "DENY"


class CapabilityStatus(StrEnum):
    """Estado operativo del ciclo de vida de una Capability."""

    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    DEPRECATED = "DEPRECATED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class CapabilityOperation:
    """Modelo inmutable para representar una operación expuesta por una Capability."""

    operation_id: str = ""
    name: str = ""
    description: str = ""
    risk_level: CapabilityRiskLevel = CapabilityRiskLevel.SAFE
    decision: CapabilityDecision = CapabilityDecision.ALLOW
    requires_confirmation: bool = False
    requires_elevation: bool = False
    allowed_parameters: tuple[str, ...] = field(default_factory=tuple)
    required_parameters: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.operation_id:
            op_id = f"op_{self.name.lower().replace('.', '_')}" if self.name else f"op_{uuid.uuid4().hex[:8]}"
            object.__setattr__(self, "operation_id", op_id)

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario estructurado de la operación."""
        return {
            "operation_id": self.operation_id,
            "name": self.name,
            "description": self.description,
            "risk_level": self.risk_level.value,
            "decision": self.decision.value,
            "requires_confirmation": self.requires_confirmation,
            "requires_elevation": self.requires_elevation,
            "allowed_parameters": list(self.allowed_parameters),
            "required_parameters": list(self.required_parameters),
        }


def compute_capability_fingerprint(
    tool_name: str,
    version: str,
    operation_id: str,
    operation_name: str,
    risk_level: str | CapabilityRiskLevel,
    decision: str | CapabilityDecision,
    requires_confirmation: bool,
    requires_elevation: bool,
) -> str:
    """Calcula el hash canónico SHA-256 determinista para el fingerprint de una capability/operación.

    Si cualquier elemento (tool_name, version, risk_level, decision, etc.) es alterado,
    el fingerprint cambiará inmediatamente, invalidando la capacidad.
    """
    risk_str = risk_level.value if isinstance(risk_level, CapabilityRiskLevel) else str(risk_level)
    decision_str = decision.value if isinstance(decision, CapabilityDecision) else str(decision)

    canonical_payload = {
        "tool_name": tool_name.strip().lower(),
        "version": version.strip(),
        "operation_id": operation_id.strip().lower(),
        "operation_name": operation_name.strip().lower(),
        "risk_level": risk_str.upper(),
        "decision": decision_str.upper(),
        "requires_confirmation": bool(requires_confirmation),
        "requires_elevation": bool(requires_elevation),
    }

    canonical_json = json.dumps(canonical_payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ToolCapability:
    """Modelo inmutable que representa la Capability completa de una herramienta."""

    capability_id: str
    tool_name: str
    display_name: str = ""
    description: str = ""
    version: str = "1.0.0"
    source: CapabilitySource = CapabilitySource.BUILTIN
    status: CapabilityStatus = CapabilityStatus.ENABLED
    operations: tuple[CapabilityOperation, ...] = field(default_factory=tuple)
    metadata: JSONDict = field(default_factory=dict)
    is_immutable: bool = True

    def get_operation(self, operation_name: str) -> CapabilityOperation | None:
        """Busca una operación por su nombre."""
        op_clean = operation_name.strip().lower()
        for op in self.operations:
            if op.name.lower() == op_clean or op.operation_id.lower() == op_clean:
                return op
        return None

    def get_operation_fingerprint(self, operation_name: str) -> str | None:
        """Obtiene el fingerprint SHA-256 determinista de una operación específica."""
        op = self.get_operation(operation_name)
        if not op:
            return None
        return compute_capability_fingerprint(
            tool_name=self.tool_name,
            version=self.version,
            operation_id=op.operation_id,
            operation_name=op.name,
            risk_level=op.risk_level,
            decision=op.decision,
            requires_confirmation=op.requires_confirmation,
            requires_elevation=op.requires_elevation,
        )

    def to_dict(self) -> dict[str, Any]:
        """Devuelve un diccionario explícito de la capability."""
        return {
            "capability_id": self.capability_id,
            "tool_name": self.tool_name,
            "display_name": self.display_name,
            "description": self.description,
            "version": self.version,
            "source": self.source.value,
            "status": self.status.value,
            "operations": [op.to_dict() for op in self.operations],
            "metadata": dict(self.metadata),
            "is_immutable": self.is_immutable,
        }
