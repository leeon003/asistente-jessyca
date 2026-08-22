"""Validador y Máquina de Estados de Propuestas de Aprendizaje (proposal_validator.py - Fase 59).

Implementa:
1. PROTECCIÓN ABSOLUTA DE SEGURIDAD: Rechazo tajante de propuestas que afecten
   políticas de seguridad, gestión de permisos, auditoría o secretos.
2. VALIDACIÓN DE EVIDENCIA: Verificación estricta de completitud técnica.
3. MÁQUINA DE ESTADOS FORMAL: Control determinista de transiciones de ciclo de vida.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from core.learning.proposal_models import LearningProposal, ProposalStatus

# Componentes y vectores de seguridad protegidos contra propuestas automáticas
PROTECTED_SECURITY_COMPONENTS: frozenset[str] = frozenset({
    "security_policy",
    "security_architecture",
    "permission_manager",
    "confirmation_manager",
    "audit_logger",
    "credential_handling",
    "secret_storage",
    "authentication",
    "sandbox_boundaries",
    "execution_boundary",
    "mcp_security_boundaries",
    "risk_engine",
    "emergency_stop",
})

# Matriz estricta de transiciones válidas de ciclo de vida
ALLOWED_TRANSITIONS: dict[ProposalStatus, frozenset[ProposalStatus]] = {
    ProposalStatus.DRAFT: frozenset({
        ProposalStatus.VALIDATED,
        ProposalStatus.REJECTED,
        ProposalStatus.EXPIRED,
    }),
    ProposalStatus.VALIDATED: frozenset({
        ProposalStatus.SIMULATION_PENDING,
        ProposalStatus.REJECTED,
        ProposalStatus.EXPIRED,
    }),
    ProposalStatus.SIMULATION_PENDING: frozenset({
        ProposalStatus.READY_FOR_EVALUATION,
        ProposalStatus.SIMULATION_FAILED,
        ProposalStatus.REJECTED,
        ProposalStatus.EXPIRED,
    }),
    ProposalStatus.SIMULATION_FAILED: frozenset({
        ProposalStatus.SIMULATION_PENDING,
        ProposalStatus.REJECTED,
        ProposalStatus.EXPIRED,
    }),
    ProposalStatus.READY_FOR_EVALUATION: frozenset({
        ProposalStatus.APPROVED,
        ProposalStatus.REJECTED,
        ProposalStatus.EXPIRED,
    }),
    ProposalStatus.APPROVED: frozenset({
        ProposalStatus.DEPLOYED,
        ProposalStatus.REJECTED,
        ProposalStatus.EXPIRED,
    }),
    ProposalStatus.DEPLOYED: frozenset({
        ProposalStatus.ROLLED_BACK,
    }),
    ProposalStatus.REJECTED: frozenset(),
    ProposalStatus.ROLLED_BACK: frozenset(),
    ProposalStatus.EXPIRED: frozenset(),
}


def is_security_component(component_name: str) -> bool:
    """Verifica si un nombre de componente o recurso pertenece al perímetro de seguridad protegido."""
    norm = component_name.lower().strip()
    for protected in PROTECTED_SECURITY_COMPONENTS:
        if protected in norm:
            return True
    tokens = set(re.split(r"[\.\s/:\\]+", norm))
    return bool(tokens & PROTECTED_SECURITY_COMPONENTS)


class ProposalValidator:
    """Validador central de seguridad, completitud y transiciones de propuestas."""

    @staticmethod
    def validate_proposal(proposal: LearningProposal) -> tuple[bool, list[str]]:
        """Valida que la propuesta cumpla los requisitos formales y no toque componentes de seguridad.

        Retorna (is_valid, errors).
        """
        errors: list[str] = []

        # 1. VERIFICACIÓN DE SEGURIDAD ABSOLUTA (Regla Fundamental)
        for comp in proposal.affected_components:
            if is_security_component(comp):
                errors.append(
                    f"CRITICAL SECURITY VIOLATION: La propuesta afecta el componente protegido '{comp}'. "
                    "Las propuestas automáticas tienen estrictamente prohibido alterar la arquitectura de seguridad."
                )

        # 2. Completitud del problema y evidencia
        if not proposal.problem or not proposal.problem.strip():
            errors.append("El campo 'problem' es obligatorio y no puede estar vacío.")

        if not proposal.evidence and proposal.occurrences <= 0:
            errors.append("La propuesta debe incluir evidencia auditable u ocurrencias registradas.")

        # 3. Componentes afectados
        if not proposal.affected_components:
            errors.append("Debe especificarse al menos un componente afectado en 'affected_components'.")

        # 4. Solución y beneficio
        if not proposal.suggested_improvement or not proposal.suggested_improvement.strip():
            errors.append("El campo 'suggested_improvement' es obligatorio.")

        if not proposal.expected_benefit or not proposal.expected_benefit.strip():
            errors.append("El campo 'expected_benefit' es obligatorio.")

        # 5. Pruebas requeridas
        if not proposal.required_tests:
            errors.append("Debe especificarse al menos una prueba requerida en 'required_tests'.")

        return (len(errors) == 0, errors)

    @staticmethod
    def can_transition(current_status: ProposalStatus, target_status: ProposalStatus) -> bool:
        """Determina si una transición de estado es válida según la máquina de estados."""
        allowed = ALLOWED_TRANSITIONS.get(current_status, frozenset())
        return target_status in allowed

    @classmethod
    def transition_proposal(
        cls,
        proposal: LearningProposal,
        target_status: ProposalStatus,
        reason: str | None = None,
    ) -> LearningProposal:
        """Ejecuta una transición de estado validada de forma inmutable."""
        if not cls.can_transition(proposal.status, target_status):
            raise ValueError(
                f"Transición de estado inválida: no se permite avanzar de '{proposal.status.value}' "
                f"a '{target_status.value}'."
            )

        # Si avanza a VALIDATED, validar exhaustivamente
        if target_status == ProposalStatus.VALIDATED:
            is_valid, errors = cls.validate_proposal(proposal)
            if not is_valid:
                raise ValueError(f"Fallo de validación de la propuesta: {'; '.join(errors)}")

        updated_dict = proposal.to_dict()
        updated_dict["status"] = target_status.value
        updated_dict["updated_at"] = datetime.now(UTC).isoformat()
        if reason:
            updated_dict["rejection_reason"] = reason

        return LearningProposal.from_dict(updated_dict)
