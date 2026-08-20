"""Agregador de decisiones de seguridad (Security Decision Aggregator - Subetapa 05.2).

Combina las evaluaciones del Risk Engine, Security Policy, Permission Manager y Confirmation Manager
siguiendo las reglas estrictas e invariantes de seguridad de Jessyca.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.security_architecture import SecurityDecisionType, SecurityLevel


@dataclass(frozen=True)
class AggregatedSecurityDecision:
    """Decisión de seguridad agregada inmutable."""

    is_allowed: bool
    decision_type: SecurityDecisionType | str
    requires_elevation: bool = False
    requires_confirmation: bool = False
    reason: str = ""
    matched_rule: str = ""


class SecurityDecisionAggregator:
    """Combina decisiones de seguridad aplicando las invariantes globales."""

    def aggregate(
        self,
        risk_assessment: Any,
        policy_decision: Any,
        permission_result: Any,
        confirmation_result: Any = None,
        capability_resolution: Any = None,
    ) -> AggregatedSecurityDecision:
        """Agrega todas las evaluaciones en una decisión consolidada inmutable."""
        cap_dec = ""
        # 0. Regla Capability System: Si Capability Resolution fue encontrada y deniega
        if capability_resolution is not None and getattr(capability_resolution, "found", False):
            cap_dec = getattr(cap_dec_obj := getattr(capability_resolution, "decision", "DENY"), "value", str(cap_dec_obj))
            if cap_dec == "DENY":
                return AggregatedSecurityDecision(
                    is_allowed=False,
                    decision_type=SecurityDecisionType.DENY,
                    reason=getattr(capability_resolution, "reason", "Denegado por Capability System."),
                )

        risk_level = getattr(risk_assessment, "risk_level", SecurityLevel.SAFE)
        risk_level_val = getattr(risk_level, "value", str(risk_level))

        policy_dec = getattr(policy_policy_dec := getattr(policy_decision, "decision_type", SecurityDecisionType.DENY), "value", str(policy_policy_dec))
        policy_allowed = getattr(policy_decision, "is_allowed", False)

        perm_dec = getattr(perm_dec_obj := getattr(permission_result, "decision", "DENY"), "value", str(perm_dec_obj))
        perm_allowed = getattr(permission_result, "is_allowed", False)

        requires_elev = (
            getattr(risk_assessment, "requires_elevation", False)
            or getattr(policy_decision, "requires_elevation", False)
            or getattr(permission_result, "requires_elevation", False)
            or getattr(capability_resolution, "requires_elevation", False)
        )

        requires_conf = (
            getattr(risk_assessment, "requires_confirmation", False)
            or getattr(policy_decision, "requires_confirmation", False)
            or getattr(permission_result, "requires_confirmation", False)
            or getattr(capability_resolution, "requires_confirmation", False)
            or (policy_dec == "REQUIRE_CONFIRMATION")
            or (perm_dec == "REQUIRE_CONFIRMATION")
            or (cap_dec == "REQUIRE_CONFIRMATION")
        )

        # 1. Regla DENY Overriding: Si cualquier capa indica DENY -> DENY prevalece
        if not policy_allowed and policy_dec == "DENY":
            return AggregatedSecurityDecision(
                is_allowed=False,
                decision_type=SecurityDecisionType.DENY,
                reason=getattr(policy_decision, "reason", "Denegado por política de seguridad."),
            )

        if not perm_allowed and perm_dec == "DENY":
            return AggregatedSecurityDecision(
                is_allowed=False,
                decision_type=SecurityDecisionType.DENY,
                reason=getattr(permission_result, "reason", "Denegado por Permission Manager."),
            )

        # 2. Regla CRITICAL: Jamás ALLOW directo
        if risk_level_val == "CRITICAL":
            return AggregatedSecurityDecision(
                is_allowed=False,
                decision_type=(
                    SecurityDecisionType.REQUIRE_ELEVATED_AUTHORIZATION if requires_elev else SecurityDecisionType.DENY
                ),
                requires_elevation=requires_elev,
                reason="Las operaciones de riesgo CRITICAL jamás se permiten de forma directa.",
            )

        # 3. Regla UNKNOWN: Fail-Safe DENY
        if risk_level_val == "UNKNOWN" or "UNKNOWN" in str(risk_assessment):
            return AggregatedSecurityDecision(
                is_allowed=False,
                decision_type=SecurityDecisionType.DENY,
                reason="Operación de riesgo desmesurado o UNKNOWN denegada por Fail-Safe.",
            )

        # 4. Regla requires_elevation=True: Jamás ALLOW directo
        if requires_elev:
            return AggregatedSecurityDecision(
                is_allowed=False,
                decision_type=SecurityDecisionType.REQUIRE_ELEVATED_AUTHORIZATION,
                requires_elevation=True,
                reason="La operación requiere elevación de privilegios UAC/Administrador.",
            )

        # 5. Regla REQUIRE_CONFIRMATION: Verificar resultado de confirmación
        if requires_conf:
            if confirmation_result is None:
                return AggregatedSecurityDecision(
                    is_allowed=False,
                    decision_type=SecurityDecisionType.REQUIRE_CONFIRMATION,
                    requires_confirmation=True,
                    reason="La operación requiere confirmación explícita del usuario.",
                )

            conf_status = getattr(confirmation_result, "status", None)
            conf_status_str = getattr(conf_status, "value", str(conf_status)) if conf_status else ""

            if conf_status_str.upper() == "APPROVED" or getattr(confirmation_result, "is_approved", False):
                return AggregatedSecurityDecision(
                    is_allowed=True,
                    decision_type=SecurityDecisionType.ALLOW,
                    reason="Operación autorizada tras aprobación explícita del usuario.",
                )
            else:
                return AggregatedSecurityDecision(
                    is_allowed=False,
                    decision_type=SecurityDecisionType.DENY,
                    requires_confirmation=True,
                    reason=f"Confirmación no aprobada (Estado: {conf_status_str or 'REJECTED'}).",
                )

        # 6. Si todas las capas anteriores otorgan ALLOW
        if policy_allowed and perm_allowed:
            return AggregatedSecurityDecision(
                is_allowed=True,
                decision_type=SecurityDecisionType.ALLOW,
                reason="Operación autorizada por las capas de seguridad.",
            )

        # Fail-Safe global por defecto
        return AggregatedSecurityDecision(
            is_allowed=False,
            decision_type=SecurityDecisionType.DENY,
            reason="Denegado por política Fail-Safe predeterminada.",
        )
