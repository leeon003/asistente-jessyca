"""Pruebas de resistencia ante intentos de bypass del JDE Runtime Binding (Fase 1).

Verifica que sea imposible:
1. Saltar la evaluación del JDE.
2. Saltar RiskEngine (JDE ALLOW no anula la seguridad de RiskEngine).
3. Ejecutar tras un veredicto de DENY.
4. Ejecutar tras REQUIRE_REVIEW sin confirmación válida.
5. Forzar el modo ACTIVE sin autorización formal.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.jde.authority import (
    ActionRiskTier,
    AuthorityDecision,
    AuthorityGateResult,
    AuthorityMode,
)
from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeMode,
    JDERuntimeVerdictType,
)
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest
from core.security_architecture import SecurityLevel


def test_bypass_attempt_after_deny_fails_safely():
    """Intento de forzar ejecución tras un DENY del JDE falla rotundamente."""
    mock_skill_manager = MagicMock()
    mock_gate = MagicMock()
    mock_gate.is_kill_switch_active = False
    mock_gate.current_mode = AuthorityMode.CONTROLLED
    mock_gate.evaluate_authority.return_value = AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.DENY,
        can_execute=False,
        can_block=True,
        risk_tier=ActionRiskTier.HIGH,
        action="open_application",
        tool="windows.apps",
        is_authorized=False,
        requires_human_confirmation=False,
        reason="Bloqueo estricto de bypass.",
    )

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=mock_gate)
    agent = JessycaLocalAgent(
        skill_manager=mock_skill_manager,
        jde_runtime_binding=binding,
    )

    req = JessycaRequest(user_input="abre notepad", session_id="bypass_deny_session")
    resp = agent.interact(req)

    assert not resp.success
    assert resp.status == AgentExecutionState.FAILED
    assert "Acción denegada por gobernanza JDE" in resp.response_text
    mock_skill_manager.execute_skill.assert_not_called()


def test_jde_allow_does_not_bypass_risk_engine():
    """Incluso si JDE emitiera ALLOW, la evaluación de RiskEngine y confirmación humana previa se mantienen intactas."""
    mock_skill_manager = MagicMock()
    mock_gate = MagicMock()
    mock_gate.is_kill_switch_active = False
    mock_gate.current_mode = AuthorityMode.CONTROLLED
    mock_gate.evaluate_authority.return_value = AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.ALLOW,
        can_execute=True,
        can_block=True,
        risk_tier=ActionRiskTier.LOW,
        action="open_application",
        tool="windows.apps",
        is_authorized=True,
        requires_human_confirmation=False,
        reason="Permitido.",
    )

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=mock_gate)
    agent = JessycaLocalAgent(
        skill_manager=mock_skill_manager,
        jde_runtime_binding=binding,
    )

    # Forzamos una acción que RiskEngine considera CRITICAL
    with patch.object(agent, "_evaluate_action_security", return_value=SecurityLevel.CRITICAL):
        req = JessycaRequest(user_input="abre notepad", session_id="risk_bypass_session")
        resp = agent.interact(req)

        # RiskEngine exige confirmación antes de llegar a la ejecución
        assert resp.status == AgentExecutionState.AWAITING_CONFIRMATION
        assert resp.requires_confirmation is True
        mock_skill_manager.execute_skill.assert_not_called()


def test_cannot_bypass_controlled_mode_with_active_injection():
    """Intento de forzar ACTIVE no debe sortear las defensas de Fase 1."""
    binding = JDERuntimeBinding(mode="ACTIVE")
    assert binding.current_mode == JDERuntimeMode.CONTROLLED

    ok, msg = binding.set_mode("ACTIVE")
    assert not ok
    assert binding.current_mode == JDERuntimeMode.CONTROLLED
