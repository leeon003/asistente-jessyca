"""Módulo de Resolución de Conflictos y Jerarquía de Decisiones - JDE Fase 8.

Implementa la jerarquía determinista de gobernanza:
    SAFETY (RiskEngine)
    >
    AUTHORIZATION (PermissionManager)
    >
    POLICY (JDE Policies / Safety Gate)
    >
    BUSINESS RULE (CapabilityRegistry / Scopes)
    >
    OPTIMIZATION (Selección y Despacho)

Regla Fundamental:
Decision Authority != Security Override Authority.
JDE decide, pero no puede eludir las restricciones de seguridad ni autorización.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.jde.states import DecisionState


class ConflictResolutionResult(BaseModel):
    """Resultado formal del análisis de precedencia y resolución de conflictos."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_allowed: bool
    resolved_state: DecisionState
    overriding_layer: str  # SAFETY | AUTHORIZATION | POLICY | BUSINESS_RULE | OPTIMIZATION
    reason: str
    requires_confirmation: bool = False
    effective_action: str = ""
    rules_applied: list[str] = Field(default_factory=list)


# Patrones para detección de contradicciones obvias en la instrucción
_CONTRADICTORY_PATTERNS = re.compile(
    r"(haz\s+[\w\s]+?(?:y\s+)?no\s+hagas|"
    r"borra\s+[\w\s]+?(?:y\s+)?mant[eé]n|"
    r"ejecuta\s+[\w\s]+?(?:y\s+)?cancela|"
    r"inicia\s+[\w\s]+?(?:y\s+)?det[eé]n|"
    r"elimina\s+[\w\s]+?(?:y\s+)?conserva)",
    re.IGNORECASE,
)

# Patrones de ambigüedad extrema
_AMBIGUOUS_PATTERNS = re.compile(
    r"^(haz\s+eso|hazlo|ejecuta|dale|contin[uú]a|procede|haz\s+algo)$",
    re.IGNORECASE,
)


class JDEConflictResolver:
    """Resolutor determinista de conflictos y prioridades para JDE."""

    @staticmethod
    def detect_contradiction(user_instruction: str) -> bool:
        """Detecta si el usuario emite una instrucción flagrantemente contradictoria."""
        cleaned = user_instruction.strip()
        return bool(_CONTRADICTORY_PATTERNS.search(cleaned))

    @staticmethod
    def detect_ambiguity(user_instruction: str) -> bool:
        """Detecta si la petición es totalmente ambigua y carece de acción u objetivo claro."""
        cleaned = user_instruction.strip()
        return bool(_AMBIGUOUS_PATTERNS.match(cleaned))

    def resolve(
        self,
        action: str,
        tool: str,
        user_prompt: str = "",
        risk_tier: str = "SAFE",
        permission_decision: str = "ALLOW",
        policy_allowed: bool = True,
        policy_reason: str = "",
        capability_enabled: bool = True,
        scope_valid: bool = True,
        scope_reason: str = "",
        user_confirmed: bool = False,
    ) -> ConflictResolutionResult:
        """Aplica la jerarquía formal para resolver cualquier conflicto de decisión."""
        rules_applied: list[str] = []

        # 0. Ambigüedad extrema -> NO_DECISION / REQUIRES_CONFIRMATION
        if user_prompt and self.detect_ambiguity(user_prompt):
            rules_applied.append("AMBIGUOUS_INTENT_RULE")
            return ConflictResolutionResult(
                is_allowed=False,
                resolved_state=DecisionState.NO_DECISION,
                overriding_layer="POLICY",
                reason=f"Petición ambigua ('{user_prompt}'): JDE no inventa acciones ante la incertidumbre.",
                requires_confirmation=True,
                effective_action=action,
                rules_applied=rules_applied,
            )

        # 0.1. Instrucción contradictoria -> CONFLICT / REQUIRES_CONFIRMATION
        if user_prompt and self.detect_contradiction(user_prompt):
            rules_applied.append("CONTRADICTORY_INSTRUCTION_RULE")
            return ConflictResolutionResult(
                is_allowed=False,
                resolved_state=DecisionState.CONFLICT,
                overriding_layer="SAFETY",
                reason=f"Instrucción contradictoria detectada ('{user_prompt}'): resolución de seguridad en CONFLICT.",
                requires_confirmation=True,
                effective_action=action,
                rules_applied=rules_applied,
            )

        # ── 1. NIVEL 1: SAFETY (RiskEngine) ──
        # Prevalece sobre todas las demás capas
        risk_upper = risk_tier.upper().strip()
        if risk_upper in ("CRITICAL", "HIGH", "DANGEROUS"):
            rules_applied.append("SAFETY_LAYER_EVALUATION")
            if not user_confirmed:
                return ConflictResolutionResult(
                    is_allowed=False,
                    resolved_state=DecisionState.REQUIRES_CONFIRMATION,
                    overriding_layer="SAFETY",
                    reason=f"Restricción de seguridad crítica: acción '{action}' (riesgo {risk_upper}) requiere confirmación humana explícita.",
                    requires_confirmation=True,
                    effective_action=action,
                    rules_applied=rules_applied,
                )

        # ── 2. NIVEL 2: AUTHORIZATION (PermissionManager) ──
        # Si el PermissionManager deniega, ningún nivel inferior puede autorizar
        perm_upper = permission_decision.upper().strip()
        if perm_upper in ("DENY", "DENIED", "BLOCKED"):
            rules_applied.append("AUTHORIZATION_LAYER_EVALUATION")
            return ConflictResolutionResult(
                is_allowed=False,
                resolved_state=DecisionState.BLOCKED,
                overriding_layer="AUTHORIZATION",
                reason=f"Restricción de autorización: PermissionManager denegó la operación '{action}' en '{tool}'.",
                requires_confirmation=False,
                effective_action=action,
                rules_applied=rules_applied,
            )
        elif perm_upper == "REQUIRE_CONFIRMATION" and not user_confirmed:
            rules_applied.append("AUTHORIZATION_CONFIRMATION_EVALUATION")
            return ConflictResolutionResult(
                is_allowed=False,
                resolved_state=DecisionState.REQUIRES_CONFIRMATION,
                overriding_layer="AUTHORIZATION",
                reason=f"PermissionManager exige confirmación de seguridad para '{action}'.",
                requires_confirmation=True,
                effective_action=action,
                rules_applied=rules_applied,
            )

        # ── 3. NIVEL 3: POLICY (JDE Policies / Policy Gate) ──
        if not policy_allowed:
            rules_applied.append("POLICY_LAYER_EVALUATION")
            return ConflictResolutionResult(
                is_allowed=False,
                resolved_state=DecisionState.BLOCKED,
                overriding_layer="POLICY",
                reason=policy_reason or f"Restricción de política: JDE Policy Gate denegó '{action}'.",
                requires_confirmation=False,
                effective_action=action,
                rules_applied=rules_applied,
            )

        # ── 4. NIVEL 4: BUSINESS RULES (CapabilityRegistry / Scopes) ──
        if not capability_enabled:
            rules_applied.append("BUSINESS_RULE_CAPABILITY_DISABLED")
            return ConflictResolutionResult(
                is_allowed=False,
                resolved_state=DecisionState.DENIED,
                overriding_layer="BUSINESS_RULE",
                reason=f"Regla de negocio: la capacidad '{action}' está deshabilitada en el catálogo.",
                requires_confirmation=False,
                effective_action=action,
                rules_applied=rules_applied,
            )

        if not scope_valid:
            rules_applied.append("BUSINESS_RULE_SCOPE_VIOLATION")
            return ConflictResolutionResult(
                is_allowed=False,
                resolved_state=DecisionState.DENIED,
                overriding_layer="BUSINESS_RULE",
                reason=scope_reason or f"Regla de negocio: parámetros fuera de scope para '{action}'.",
                requires_confirmation=False,
                effective_action=action,
                rules_applied=rules_applied,
            )

        # ── 5. NIVEL 5: OPTIMIZATION (Autorización Concedida) ──
        rules_applied.append("OPTIMIZATION_DISPATCH_AUTHORIZED")
        return ConflictResolutionResult(
            is_allowed=True,
            resolved_state=DecisionState.AUTHORIZED,
            overriding_layer="OPTIMIZATION",
            reason=f"Acción '{action}' autorizada formalmente tras satisfacer todas las restricciones de gobernanza.",
            requires_confirmation=False,
            effective_action=action,
            rules_applied=rules_applied,
        )
