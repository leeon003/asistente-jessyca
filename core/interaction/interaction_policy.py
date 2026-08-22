"""Política de Decisión y Evaluación de Interacción Humana (interaction_policy.py - Fase 41).

Evalúa el flujo canónico:
    User Intent -> Intent Classification -> Risk Assessment -> Autonomy Policy -> Clarity Check -> Interaction Decision
"""

from __future__ import annotations

from typing import Any

from core.autonomy.autonomy_level import AutonomyLevel
from core.interaction.interaction_models import (
    ClarificationPrompt,
    ConfirmationPrompt,
    InteractionAction,
    InteractionDecision,
    InteractionState,
)
from core.security_architecture import SecurityLevel


class InteractionPolicy:
    """Evaluador de políticas de interacción confiable y decisiones Human-in-the-Loop."""

    @classmethod
    def evaluate_interaction(
        cls,
        intent: str,
        clarity_score: float = 1.0,
        missing_fields: list[str] | None = None,
        candidate_options: list[str] | None = None,
        risk_level: SecurityLevel = SecurityLevel.SAFE,
        autonomy_level: AutonomyLevel = AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED,
        task_id: str = "",
        action_name: str = "",
        target_resource: str = "",
        parameters: dict[str, Any] | None = None,
        emergency_stop_active: bool = False,
    ) -> InteractionDecision:
        """Determina la acción canónica de interacción ante una petición o paso de ejecución."""
        # 1. Invariante de Parada de Emergencia
        if emergency_stop_active:
            return InteractionDecision(
                action=InteractionAction.STOPS,
                state=InteractionState.CANCELLED,
                reason="Parada de Emergencia activa. Interacción y ejecución detenidas incondicionalmente.",
                execution_authorized=False,
            )

        # 2. Operaciones Prohibidas por Seguridad
        if risk_level == SecurityLevel.CRITICAL and action_name in ("format_disk", "delete_system32", "disable_security"):
            return InteractionDecision(
                action=InteractionAction.DENIES,
                state=InteractionState.DENIED,
                reason=f"Operación '{action_name}' denegada por SecurityPipeline (Acción prohibida inmutable).",
                execution_authorized=False,
            )

        # 3. Aclaración por Ambigüedad o Parámetros Críticos Faltantes
        missing = missing_fields or []
        candidates = candidate_options or []
        if missing or clarity_score < 0.6 or len(candidates) > 1:
            question = f"¿Cuál opción prefieres para {action_name or 'esta acción'}?" if candidates else f"Faltan los siguientes parámetros: {', '.join(missing)}."
            clarification = ClarificationPrompt(
                question=question,
                candidate_options=candidates,
                missing_fields=missing,
                context_hint=f"Intención: '{intent}'",
            )
            return InteractionDecision(
                action=InteractionAction.CLARIFIES if missing else InteractionAction.ASKS,
                state=InteractionState.ASK_CLARIFICATION,
                reason="Intención incompleta o ambigua. Se requiere aclaración previa antes de actuar.",
                clarification=clarification,
                execution_authorized=False,
            )

        # 4. Requerimiento de Confirmación para Acciones de Riesgo Elevado o Nivel de Autonomía 3
        requires_confirmation = (
            risk_level in (SecurityLevel.WARNING, SecurityLevel.DANGEROUS, SecurityLevel.CRITICAL)
            or autonomy_level == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED
        )
        if requires_confirmation:
            confirmation = ConfirmationPrompt(
                task_id=task_id,
                action_name=action_name or "Acción solicitada",
                target_resource=target_resource or "Sistema local",
                objective=intent,
                scope_description=f"Ejecutar '{action_name}' sobre '{target_resource}'",
                risk_level=risk_level,
                relevant_parameters=parameters or {},
                potential_impact="Modificación o acceso a recursos del sistema",
                ttl_seconds=120.0,
            )
            return InteractionDecision(
                action=InteractionAction.CONFIRMS,
                state=InteractionState.REQUEST_CONFIRMATION,
                reason=f"La acción requiere confirmación explícita del usuario (Nivel de riesgo: {risk_level.name}).",
                confirmation=confirmation,
                execution_authorized=False,
            )

        # 5. Ejecución Directa Autorizada
        return InteractionDecision(
            action=InteractionAction.ACTS,
            state=InteractionState.EXECUTE,
            reason="Intención clara, parámetros completos y nivel de riesgo SAFE/LOW. Ejecución autorizada.",
            execution_authorized=True,
        )
