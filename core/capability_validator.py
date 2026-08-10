"""Validador estricto de seguridad para el Capability System (Subetapa 06.1).

Verifica la validez y seguridad de ToolCapability, CapabilityOperation y del CapabilityRegistry.
Aplica las invariantes estrictas de seguridad (ej. CRITICAL jamás ALLOW, UNKNOWN DENY, fuentes prohibidas).
"""

from __future__ import annotations

from core.capabilities import (
    FORBIDDEN_CAPABILITY_SOURCES,
    CapabilityDecision,
    CapabilityOperation,
    CapabilityRiskLevel,
    CapabilitySource,
    ToolCapability,
)
from core.exceptions import SecurityValidationError


def validate_operation(operation: CapabilityOperation) -> list[str]:
    """Valida la consistencia e invariantes de seguridad de una operación de Capability."""
    errors: list[str] = []

    if not operation.operation_id or not operation.operation_id.strip():
        errors.append("La operación debe tener un 'operation_id' válido.")
    if not operation.name or not operation.name.strip():
        errors.append("La operación debe tener un 'name' válido.")

    # Regla 1: Risk CRITICAL jamás ALLOW directo
    if operation.risk_level == CapabilityRiskLevel.CRITICAL and operation.decision == CapabilityDecision.ALLOW:
        errors.append(
            f"Invariante de Seguridad Violada en op '{operation.name}': Risk CRITICAL jamás puede configurarse como ALLOW."
        )

    # Regla 2: Risk UNKNOWN -> DENY obligatorio
    if operation.risk_level == CapabilityRiskLevel.UNKNOWN and operation.decision != CapabilityDecision.DENY:
        errors.append(
            f"Invariante de Seguridad Violada en op '{operation.name}': Risk UNKNOWN exige decisión DENY."
        )

    # Regla 3: requires_elevation=True -> Jamás ALLOW directo
    if operation.requires_elevation and operation.decision == CapabilityDecision.ALLOW:
        errors.append(
            f"Invariante de Seguridad Violada en op '{operation.name}': Operación con requires_elevation=True no admite decision=ALLOW."
        )

    # Regla 4: requires_confirmation=True -> Jamás ALLOW directo sin confirmación
    if operation.requires_confirmation and operation.decision == CapabilityDecision.ALLOW:
        errors.append(
            f"Invariante de Seguridad Violada en op '{operation.name}': Operación con requires_confirmation=True no admite decision=ALLOW."
        )

    return errors


def validate_capability(capability: ToolCapability) -> list[str]:
    """Valida la integridad, origen confiable e invariantes de seguridad de una ToolCapability."""
    errors: list[str] = []

    if not capability.capability_id or not capability.capability_id.strip():
        errors.append("La ToolCapability debe tener un 'capability_id' válido.")
    if not capability.tool_name or not capability.tool_name.strip():
        errors.append("La ToolCapability debe tener un 'tool_name' válido.")
    if not capability.version or not capability.version.strip():
        errors.append("La ToolCapability debe especificar una 'version'.")

    # Validación de Fuente Legítima Confiable
    source_val = getattr(capability.source, "value", str(capability.source))
    if source_val in FORBIDDEN_CAPABILITY_SOURCES:
        errors.append(
            f"Fuente No Confiable Rechazada: La fuente '{source_val}' no está autorizada para registrar capabilities."
        )
    elif not isinstance(capability.source, CapabilitySource):
        errors.append(f"Fuente de Capability inválida: '{capability.source}'.")

    # Validación de duplicidad de operaciones internas
    seen_ops: set[str] = set()
    for op in capability.operations:
        op_key = op.name.strip().lower()
        if op_key in seen_ops:
            errors.append(f"Operación duplicada '{op.name}' detectada en la capability '{capability.tool_name}'.")
        seen_ops.add(op_key)

        # Validar la operación individual
        op_errors = validate_operation(op)
        errors.extend(op_errors)

    return errors


def check_and_assert_capability(capability: ToolCapability) -> None:
    """Valida una capability y lanza SecurityValidationError si existen infracciones."""
    errors = validate_capability(capability)
    if errors:
        raise SecurityValidationError(f"Falla en la validación de Capability '{capability.tool_name}': {'; '.join(errors)}")


def validate_registry(registry: Any) -> list[str]:
    """Valida todas las capabilities registradas en un CapabilityRegistry."""
    errors: list[str] = []
    if hasattr(registry, "list_capabilities"):
        for cap in registry.list_capabilities():
            errors.extend(validate_capability(cap))
    return errors

