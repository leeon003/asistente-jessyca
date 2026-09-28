"""Pruebas del Kill Switch en JDE Runtime Binding (Fase 1).

Verifica:
- Si el Kill Switch está activo (flag interno o variable JDE_KILL_SWITCH),
  JDE Runtime Binding emite DENY inmediato.
- Cero side effects durante kill switch activo.
- Restablecimiento del Kill Switch reanuda la operación gobernada.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from core.jde.authority import (
    AuthorityDecision,
    AuthorityGateResult,
    AuthorityMode,
    JDEAuthorityGate,
    reset_authority_gate,
)
from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeMode,
    JDERuntimeVerdictType,
    reset_jde_runtime_binding,
)
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest


@pytest.fixture(autouse=True)
def clean_ks_env():
    reset_authority_gate()
    reset_jde_runtime_binding()
    orig = os.environ.get("JDE_KILL_SWITCH")
    if "JDE_KILL_SWITCH" in os.environ:
        del os.environ["JDE_KILL_SWITCH"]
    yield
    reset_authority_gate()
    reset_jde_runtime_binding()
    if orig is not None:
        os.environ["JDE_KILL_SWITCH"] = orig
    elif "JDE_KILL_SWITCH" in os.environ:
        del os.environ["JDE_KILL_SWITCH"]


def test_kill_switch_triggers_immediate_deny():
    """Con kill switch activo, JDE Runtime Binding devuelve DENY y bloquea."""
    gate = JDEAuthorityGate()
    gate.trigger_kill_switch(reason="Test de parada de emergencia")

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate)
    verdict = binding.evaluate(
        intent="open_application",
        action="open_application",
        tool="windows.apps",
        parameters={"app_name": "notepad"},
    )

    assert verdict.verdict == JDERuntimeVerdictType.DENY
    assert verdict.is_blocked is True
    assert "Kill Switch activo" in verdict.reason


def test_kill_switch_blocks_agent_side_effects():
    """Verifica que el agente local no despache skills si el kill switch de JDE está activo."""
    mock_skill_manager = MagicMock()
    gate = JDEAuthorityGate()
    gate.trigger_kill_switch(reason="Emergencia simulada")

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate)
    agent = JessycaLocalAgent(
        skill_manager=mock_skill_manager,
        jde_runtime_binding=binding,
    )

    req = JessycaRequest(user_input="abre el bloc de notas", session_id="ks_session")
    resp = agent.interact(req)

    assert resp.success is False
    assert resp.status == AgentExecutionState.FAILED
    assert "Kill Switch activo" in resp.response_text
    mock_skill_manager.execute_skill.assert_not_called()


def test_kill_switch_reset_restores_operation():
    """Al resetear el kill switch, el sistema vuelve a evaluar normalmente."""
    gate = JDEAuthorityGate()
    gate.trigger_kill_switch()
    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate)

    assert binding.evaluate("test", "test", "test").verdict == JDERuntimeVerdictType.DENY

    gate.reset_kill_switch()
    # Con el kill switch inactivo, una acción autorizada procede normalmente
    from core.jde.authority import ActionRiskTier
    gate.evaluate_authority = MagicMock(return_value=AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.ALLOW,
        can_execute=True,
        can_block=True,
        risk_tier=ActionRiskTier.LOW,
        action="test",
        tool="test",
        is_authorized=True,
        requires_human_confirmation=False,
        reason="Operación normal",
    ))

    verdict_after = binding.evaluate("test", "test", "test")
    assert verdict_after.verdict == JDERuntimeVerdictType.ALLOW
    assert not verdict_after.is_blocked
