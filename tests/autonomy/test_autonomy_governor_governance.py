"""Tests exhaustivos para AutonomyGovernor (Etapa 20.2).

Verifica:
1. Control de capacidades y niveles de riesgo:
   - LOW_RISK: Ejecución automática permitida.
   - MEDIUM_RISK: Evaluación según política y confirmación.
   - DANGEROUS: Requerimiento obligatorio de confirmación.
   - CRITICAL: Confirmación individual obligatoria en todos los niveles.
2. Imposibilidad de elevación de permisos por actores no autorizados.
3. Decisiones formales: ALLOW, DENY, REQUIRE_CONFIRMATION, REQUIRE_REVIEW, STOP.
4. Enforzamiento de presupuestos (time budget, tool budget, risk ceiling).
5. Auditabilidad completa con metadata enriquecida.
"""

from __future__ import annotations

import pytest

from core.autonomy.autonomy_decision import AutonomyDecisionValue
from core.autonomy.autonomy_governor import get_autonomy_governor
from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk
from core.autonomy.autonomy_policy import AutonomyEscalationError
from core.control_plane.models import AgentBudget


class TestAutonomyGovernorGovernance:
    """Pruebas de gobernanza y control de autonomía de AutonomyGovernor."""

    def setup_method(self) -> None:
        self.governor = get_autonomy_governor()
        self.governor.reset_to_default()

    def test_low_risk_automatic_execution_allowed(self) -> None:
        """Verifica que acciones LOW_RISK / READ_ONLY en nivel 3 sean permitidas automáticamente."""
        decision = self.governor.govern_action(
            tool_name="filesystem",
            operation="read",
            task_id="t_read_01",
        )

        assert decision.decision == AutonomyDecisionValue.ALLOW
        assert decision.allowed is True
        assert decision.requires_confirmation is False
        assert decision.risk_level == TaskActionRisk.READ_ONLY
        assert "governor_level" in decision.metadata

    def test_dangerous_action_requires_confirmation(self) -> None:
        """Verifica que acciones DANGEROUS exijan confirmación y se permitan sólo tras confirmación."""
        # 1. Sin confirmar
        decision_unconfirmed = self.governor.govern_action(
            tool_name="filesystem",
            operation="delete",
            task_id="t_del_01",
            is_confirmed=False,
        )
        assert decision_unconfirmed.decision == AutonomyDecisionValue.REQUIRE_CONFIRMATION
        assert decision_unconfirmed.requires_confirmation is True

        # 2. Con confirmación
        decision_confirmed = self.governor.govern_action(
            tool_name="filesystem",
            operation="delete",
            task_id="t_del_01",
            is_confirmed=True,
        )
        assert decision_confirmed.decision == AutonomyDecisionValue.ALLOW
        assert decision_confirmed.allowed is True

    def test_critical_action_requires_individual_mandatory_confirmation_even_in_level_4(self) -> None:
        """Verifica que acciones CRITICAL siempre requieran confirmación individual obligatoria incluso en Nivel 4."""
        self.governor.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor="system_admin")

        # Sin confirmación
        decision = self.governor.govern_action(
            tool_name="windows.shell",
            operation="cmd",
            task_id="t_shell_01",
            is_confirmed=False,
        )
        assert decision.decision == AutonomyDecisionValue.REQUIRE_CONFIRMATION
        assert decision.requires_confirmation is True
        assert decision.risk_level == TaskActionRisk.CRITICAL

        # Con confirmación
        decision_ok = self.governor.govern_action(
            tool_name="windows.shell",
            operation="cmd",
            task_id="t_shell_01",
            is_confirmed=True,
        )
        assert decision_ok.decision == AutonomyDecisionValue.ALLOW

    def test_level_0_observe_denies_non_read_only_actions(self) -> None:
        """Verifica que el Nivel 0 (OBSERVE) deniegue cualquier acción de escritura o modificación."""
        self.governor.set_autonomy_level(AutonomyLevel.LEVEL_0_OBSERVE, actor="user")

        decision = self.governor.govern_action(
            tool_name="filesystem",
            operation="write",
            task_id="t_write_01",
        )
        assert decision.decision == AutonomyDecisionValue.DENY
        assert decision.allowed is False

    def test_level_1_suggest_requires_review(self) -> None:
        """Verifica que el Nivel 1 (SUGGEST) emita REQUIRE_REVIEW para acciones activas."""
        self.governor.set_autonomy_level(AutonomyLevel.LEVEL_1_SUGGEST, actor="user")

        decision = self.governor.govern_action(
            tool_name="filesystem",
            operation="create",
            task_id="t_create_01",
        )
        assert decision.decision == AutonomyDecisionValue.REQUIRE_REVIEW
        assert decision.allowed is False

    def test_unauthorized_actors_cannot_elevate_autonomy_level(self) -> None:
        """INVARIANTE CRÍTICO: El LLM, plugins o workflows NUNCA pueden cambiar el nivel de autonomía."""
        unauthorized = ["llm", "plugin", "scheduler", "memory", "workflow", "assistant", "external"]

        for actor in unauthorized:
            with pytest.raises(AutonomyEscalationError):
                self.governor.set_autonomy_level(
                    AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY,
                    actor=actor,
                )

    def test_budget_exhaustion_emits_stop(self) -> None:
        """Verifica que superar los límites de tiempo o herramientas emita la decisión STOP."""
        budget = AgentBudget(max_iterations=10, global_timeout_seconds=5.0, max_tool_executions=3)

        # 1. Timeout excedido
        dec_timeout = self.governor.govern_action(
            tool_name="filesystem",
            operation="read",
            task_id="t_budget_01",
            task_budget=budget,
            time_elapsed=6.0,
        )
        assert dec_timeout.decision == AutonomyDecisionValue.STOP
        assert "tiempo agotado" in dec_timeout.reason.lower()

        # 2. Límite de herramientas alcanzado
        dec_tools = self.governor.govern_action(
            tool_name="filesystem",
            operation="read",
            task_id="t_budget_02",
            task_budget=budget,
            tools_count=3,
        )
        assert dec_tools.decision == AutonomyDecisionValue.STOP
        assert "herramientas agotado" in dec_tools.reason.lower()

    def test_risk_ceiling_breach_emits_deny(self) -> None:
        """Verifica que superar el techo de riesgo del presupuesto emita DENY."""
        budget = AgentBudget(
            risk_ceiling=TaskActionRisk.LOW_RISK,
        )

        # filesystem.delete es DANGEROUS (> LOW_RISK)
        decision = self.governor.govern_action(
            tool_name="filesystem",
            operation="delete",
            task_id="t_ceil_01",
            task_budget=budget,
        )
        assert decision.decision == AutonomyDecisionValue.DENY
        assert "techo de riesgo" in decision.reason.lower()

    def test_decision_is_fully_auditable_with_metadata(self) -> None:
        """Verifica que toda decisión del Governor contenga metadata enriquecida."""
        decision = self.governor.govern_action(
            tool_name="document",
            operation="create",
            task_id="t_audit_01",
            task_source="interactive",
        )

        meta = decision.metadata
        assert "reversibility" in meta
        assert "governor_level" in meta
        assert "governor_risk" in meta
        assert "decision_enum" in meta
        assert meta["task_source"] == "interactive"
