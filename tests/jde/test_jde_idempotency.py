"""Pruebas de idempotencia e integración con IdempotencyGuard en JDE Runtime Binding (Fase 1).

Verifica:
- JDE Runtime Binding no altera la deduplicación de IdempotencyGuard.
- Dos peticiones idénticas no producen doble efecto secundario (doble invocación de skill).
- La huella digital previene ejecución repetida en retry o replay.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.execution.idempotency_guard import (
    ExecutionFingerprint,
    ExecutionIdempotencyGuard,
)
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


def test_jde_runtime_binding_preserves_idempotency_deduplication():
    """Verifica que si JDE emite ALLOW, IdempotencyGuard bloquee la segunda ejecución idéntica."""
    mock_skill_manager = MagicMock()
    mock_skill_manager.execute_skill.return_value = MagicMock(
        success=True,
        output={
            "exito": True,
            "mensaje": "Notepad abierto.",
            "evidence": {"verification_type": "process", "target": "notepad", "is_verified": True},
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

    idempotency_guard = ExecutionIdempotencyGuard()
    binding = JDERuntimeBinding(
        mode=JDERuntimeMode.CONTROLLED,
        authority_gate=mock_gate,
        idempotency_guard=idempotency_guard,
    )

    agent = JessycaLocalAgent(
        skill_manager=mock_skill_manager,
        jde_runtime_binding=binding,
    )

    # Primer turno: se autoriza y se ejecuta
    req1 = JessycaRequest(request_id="idem_req_001", user_input="abre el bloc de notas", session_id="idem_session")
    with patch("core.execution.idempotency_guard.get_idempotency_guard", return_value=idempotency_guard):
        resp1 = agent.interact(req1)
        assert resp1.success is True
        assert mock_skill_manager.execute_skill.call_count == 1

        # Segundo turno idéntico: JDE da ALLOW pero IdempotencyGuard detecta duplicado
        req2 = JessycaRequest(request_id="idem_req_001", user_input="abre el bloc de notas", session_id="idem_session")
        resp2 = agent.interact(req2)
        assert resp2.success is True

        # La skill NUNCA fue ejecutada una segunda vez (call_count sigue siendo 1)
        assert mock_skill_manager.execute_skill.call_count == 1
