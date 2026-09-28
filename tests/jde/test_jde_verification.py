"""Pruebas del principio Anti-False Success y ExecutionVerifier bajo JDE Runtime Binding (Fase 1).

Verifica:
- "Tool returned OK" != "Real-world action succeeded".
- Si ExecutionVerifier reporta no-verificado (is_verified=False), el resultado final
  DEBE ser fallo/verification_failed, NUNCA éxito.
- JDE Runtime Binding jamás convierte un falso éxito en éxito.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.execution.execution_verifier import ExecutionStatus
from core.jde.authority import (
    ActionRiskTier,
    AuthorityDecision,
    AuthorityGateResult,
    AuthorityMode,
)
from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeMode,
)
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest


def test_anti_false_success_when_tool_claims_ok_but_unverified():
    """Si una skill devuelve exito=True pero la evidencia física no puede verificarse, el estado no debe ser de éxito."""
    mock_skill_manager = MagicMock()
    # La skill simula haber funcionado, pero la evidencia física dice is_verified=False
    mock_skill_manager.execute_skill.return_value = MagicMock(
        success=True,
        output={
            "exito": True,
            "mensaje": "Proceso iniciado supuestamente.",
            "evidence": {
                "verification_type": "process",
                "target": "notepad",
                "is_verified": False,
            },
        },
        error=None,
    )

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

    binding = JDERuntimeBinding(
        mode=JDERuntimeMode.CONTROLLED,
        authority_gate=mock_gate,
    )

    agent = JessycaLocalAgent(
        skill_manager=mock_skill_manager,
        jde_runtime_binding=binding,
    )

    req = JessycaRequest(user_input="abre el bloc de notas", session_id="false_success_session")
    resp = agent.interact(req)

    # Invariante Anti-False Success: sin evidencia física real, success DEBE ser False
    assert resp.success is False
    assert resp.status in (AgentExecutionState.FAILED, AgentExecutionState.UNKNOWN)
