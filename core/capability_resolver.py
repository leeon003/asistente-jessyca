"""Resolutor desacoplado de Capabilities (CapabilityResolver - Subetapa 06.1).

Resuelve solicitudes de herramienta y operación contra el CapabilityRegistry.
Si una herramienta u operación no existe, o si está bloqueada, devuelve un resultado DENY.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.capabilities import (
    CapabilityDecision,
    CapabilityRiskLevel,
    CapabilityStatus,
)
from core.capability_registry import ICapabilityRegistry, get_capability_registry
from core.logger import get_logger

logger = get_logger("jessyca.core.capability_resolver")


@dataclass(frozen=True)
class CapabilityResolution:
    """Resultado inmutable de la resolución de una Capability."""

    found: bool
    tool_name: str
    operation: str
    capability_id: str | None = None
    risk_level: CapabilityRiskLevel = CapabilityRiskLevel.UNKNOWN
    decision: CapabilityDecision = CapabilityDecision.DENY
    requires_confirmation: bool = False
    requires_elevation: bool = False
    fingerprint: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, str | bool | None]:
        """Devuelve un diccionario estructurado del resultado de resolución."""
        return {
            "found": self.found,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "capability_id": self.capability_id,
            "risk_level": self.risk_level.value,
            "decision": self.decision.value,
            "requires_confirmation": self.requires_confirmation,
            "requires_elevation": self.requires_elevation,
            "fingerprint": self.fingerprint,
            "reason": self.reason,
        }


class CapabilityResolver:
    """Resolutor de autorizaciones y metadatos de Capabilities."""

    def __init__(self, registry: ICapabilityRegistry | None = None) -> None:
        self.registry: ICapabilityRegistry = registry or get_capability_registry()

    def resolve(self, tool_name: str, operation: str = "execute") -> CapabilityResolution:
        """Resuelve el estado de seguridad de una herramienta y operación solicitadas."""
        tool_clean = tool_name.strip().lower()
        op_clean = operation.strip().lower()

        cap = self.registry.get_tool(tool_clean)
        if not cap:
            logger.warning(f"[CAPABILITY RESOLVER] Herramienta no registrada en CapabilityRegistry: '{tool_clean}'")
            return CapabilityResolution(
                found=False,
                tool_name=tool_clean,
                operation=op_clean,
                risk_level=CapabilityRiskLevel.UNKNOWN,
                decision=CapabilityDecision.DENY,
                reason=f"Herramienta '{tool_clean}' no declarada en el CapabilityRegistry.",
            )

        if cap.status in (CapabilityStatus.BLOCKED, CapabilityStatus.DISABLED):
            logger.warning(f"[CAPABILITY RESOLVER] Capability '{tool_clean}' en estado {cap.status.value}")
            return CapabilityResolution(
                found=True,
                capability_id=cap.capability_id,
                tool_name=tool_clean,
                operation=op_clean,
                risk_level=CapabilityRiskLevel.UNKNOWN,
                decision=CapabilityDecision.DENY,
                reason=f"La capability de la herramienta '{tool_clean}' se encuentra {cap.status.value}.",
            )

        op = cap.get_operation(op_clean)
        if not op:
            logger.warning(f"[CAPABILITY RESOLVER] Operación '{op_clean}' no registrada en capability '{tool_clean}'")
            return CapabilityResolution(
                found=False,
                capability_id=cap.capability_id,
                tool_name=tool_clean,
                operation=op_clean,
                risk_level=CapabilityRiskLevel.UNKNOWN,
                decision=CapabilityDecision.DENY,
                reason=f"Operación '{op_clean}' no declarada para la herramienta '{tool_clean}'.",
            )

        fingerprint = cap.get_operation_fingerprint(op_clean)

        logger.info(
            f"[CAPABILITY RESOLVER] Resuelta capability [{cap.capability_id}] '{tool_clean}.{op_clean}' "
            f"-> Risk: {op.risk_level.value}, Decision: {op.decision.value}"
        )

        return CapabilityResolution(
            found=True,
            capability_id=cap.capability_id,
            tool_name=tool_clean,
            operation=op_clean,
            risk_level=op.risk_level,
            decision=op.decision,
            requires_confirmation=op.requires_confirmation,
            requires_elevation=op.requires_elevation,
            fingerprint=fingerprint,
            reason="Capability declarada resuelta exitosamente.",
        )
