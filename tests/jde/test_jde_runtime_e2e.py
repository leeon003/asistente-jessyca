"""Prueba de integración End-to-End (E2E) para la cadena completa de gobernanza JDE (Fase 1).

Flujo E2E verificado:
User Intent
→ JessycaLocalAgent
→ JDE Runtime Binding
→ RiskEngine
→ PermissionManager
→ IdempotencyGuard
→ ExecutionBoundary
→ Skill/Adapter
→ ExecutionVerifier
→ Receipt

Casos probados:
1. ALLOW → ejecución y verificación correctas.
2. DENY → cero side effect.
3. REQUIRE_REVIEW → cero side effect sin confirmación.
4. Ejecución duplicada → protegida por IdempotencyGuard.
5. Falso éxito → verificación física falla y el resultado es FAILED.
6. Kill Switch → ejecución bloqueada inmediatamente.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from core.execution.idempotency_guard import ExecutionIdempotencyGuard
from core.jde.authority import (
    ActionRiskTier,
    AuthorityDecision,
    AuthorityGateResult,
    AuthorityMode,
    JDEAuthorityGate,
    reset_authority_gate,
)
from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeMode,
    reset_jde_runtime_binding,
)
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest


@pytest.fixture(autouse=True)
def clean_e2e_env():
    reset_authority_gate()
    reset_jde_runtime_binding()
    orig_mode = os.environ.get("JDE_RUNTIME_MODE")
    orig_ks = os.environ.get("JDE_KILL_SWITCH")
    if "JDE_RUNTIME_MODE" in os.environ:
        del os.environ["JDE_RUNTIME_MODE"]
    if "JDE_KILL_SWITCH" in os.environ:
        del os.environ["JDE_KILL_SWITCH"]
    yield
    reset_authority_gate()
    reset_jde_runtime_binding()
    if orig_mode is not None:
        os.environ["JDE_RUNTIME_MODE"] = orig_mode
    elif "JDE_RUNTIME_MODE" in os.environ:
        del os.environ["JDE_RUNTIME_MODE"]
    if orig_ks is not None:
        os.environ["JDE_KILL_SWITCH"] = orig_ks
    elif "JDE_KILL_SWITCH" in os.environ:
        del os.environ["JDE_KILL_SWITCH"]


def test_e2e_full_chain_allow():
    """E2E Caso 1: ALLOW -> ejecución y verificación correctas."""
    mock_skill_mgr = MagicMock()
    mock_skill_mgr.execute_skill.return_value = MagicMock(
        success=True,
        output={
            "exito": True,
            "mensaje": "Notepad abierto correctamente.",
            "evidence": {
                "verification_type": "process",
                "target": "notepad",
                "is_verified": True,
                "details": {"pid": 12345},
            },
        },
        error=None,
    )

    gate = JDEAuthorityGate()
    gate.evaluate_authority = MagicMock(return_value=AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.ALLOW,
        can_execute=True,
        can_block=True,
        risk_tier=ActionRiskTier.LOW,
        action="open_application",
        tool="windows.apps",
        is_authorized=True,
        requires_human_confirmation=False,
        reason="E2E Allow",
    ))

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate)
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)

    req = JessycaRequest(request_id="e2e_allow_01", user_input="abre el bloc de notas", session_id="e2e_sess")
    resp = agent.interact(req)

    assert resp.success is True
    assert resp.status == AgentExecutionState.COMPLETED
    mock_skill_mgr.execute_skill.assert_called_once()


def test_e2e_full_chain_deny():
    """E2E Caso 2: DENY -> cero side effect."""
    mock_skill_mgr = MagicMock()
    gate = JDEAuthorityGate()
    gate.evaluate_authority = MagicMock(return_value=AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.DENY,
        can_execute=False,
        can_block=True,
        risk_tier=ActionRiskTier.HIGH,
        action="open_application",
        tool="windows.apps",
        is_authorized=False,
        requires_human_confirmation=False,
        reason="E2E Deny",
    ))

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate)
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)

    req = JessycaRequest(request_id="e2e_deny_01", user_input="abre el bloc de notas", session_id="e2e_sess")
    resp = agent.interact(req)

    assert resp.success is False
    assert resp.status == AgentExecutionState.FAILED
    assert resp.security_verdict == "DENY"
    mock_skill_mgr.execute_skill.assert_not_called()


def test_e2e_full_chain_require_review():
    """E2E Caso 3: REQUIRE_REVIEW -> cero side effect sin confirmación."""
    mock_skill_mgr = MagicMock()
    gate = JDEAuthorityGate()
    gate.evaluate_authority = MagicMock(return_value=AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.REQUIRE_VERIFICATION,
        can_execute=False,
        can_block=True,
        risk_tier=ActionRiskTier.MEDIUM,
        action="open_application",
        tool="windows.apps",
        is_authorized=False,
        requires_human_confirmation=True,
        reason="E2E Review Required",
    ))

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate)
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)

    req = JessycaRequest(request_id="e2e_review_01", user_input="abre el bloc de notas", session_id="e2e_sess")
    resp = agent.interact(req)

    assert resp.status == AgentExecutionState.AWAITING_CONFIRMATION
    assert resp.requires_confirmation is True
    mock_skill_mgr.execute_skill.assert_not_called()


def test_e2e_full_chain_duplicate_protection():
    """E2E Caso 4: Ejecución duplicada -> protegida por IdempotencyGuard."""
    mock_skill_mgr = MagicMock()
    mock_skill_mgr.execute_skill.return_value = MagicMock(
        success=True,
        output={
            "exito": True,
            "mensaje": "Notepad abierto.",
            "evidence": {"verification_type": "process", "target": "notepad", "is_verified": True},
        },
        error=None,
    )

    guard = ExecutionIdempotencyGuard()
    gate = JDEAuthorityGate()
    gate.evaluate_authority = MagicMock(return_value=AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.ALLOW,
        can_execute=True,
        can_block=True,
        risk_tier=ActionRiskTier.LOW,
        action="open_application",
        tool="windows.apps",
        is_authorized=True,
        requires_human_confirmation=False,
        reason="E2E Allow",
    ))

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate, idempotency_guard=guard)
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)

    with patch("core.execution.idempotency_guard.get_idempotency_guard", return_value=guard):
        req1 = JessycaRequest(request_id="e2e_dup_01", user_input="abre el bloc de notas", session_id="e2e_sess")
        resp1 = agent.interact(req1)
        assert resp1.success is True

        req2 = JessycaRequest(request_id="e2e_dup_01", user_input="abre el bloc de notas", session_id="e2e_sess")
        resp2 = agent.interact(req2)
        assert resp2.success is True

        # Skill invocada únicamente una vez
        assert mock_skill_mgr.execute_skill.call_count == 1


def test_e2e_full_chain_false_success_protection():
    """E2E Caso 5: Falso éxito -> verificación física falla y resultado es FAILED."""
    mock_skill_mgr = MagicMock()
    mock_skill_mgr.execute_skill.return_value = MagicMock(
        success=True,
        output={
            "exito": True,
            "mensaje": "Fake success claim.",
            "evidence": {
                "verification_type": "process",
                "target": "notepad",
                "is_verified": False,
            },
        },
        error=None,
    )

    gate = JDEAuthorityGate()
    gate.evaluate_authority = MagicMock(return_value=AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.ALLOW,
        can_execute=True,
        can_block=True,
        risk_tier=ActionRiskTier.LOW,
        action="open_application",
        tool="windows.apps",
        is_authorized=True,
        requires_human_confirmation=False,
        reason="E2E Allow",
    ))

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate)
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)

    req = JessycaRequest(request_id="e2e_false_success", user_input="abre el bloc de notas", session_id="e2e_sess")
    resp = agent.interact(req)

    assert resp.success is False
    assert resp.status in (AgentExecutionState.FAILED, AgentExecutionState.UNKNOWN)


def test_e2e_full_chain_kill_switch_blocking():
    """E2E Caso 6: Kill switch -> ejecución bloqueada inmediatamente."""
    mock_skill_mgr = MagicMock()
    gate = JDEAuthorityGate()
    gate.trigger_kill_switch(reason="Parada de emergencia en E2E")

    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate)
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)

    req = JessycaRequest(request_id="e2e_ks_01", user_input="abre el bloc de notas", session_id="e2e_sess")
    resp = agent.interact(req)

    assert resp.success is False
    assert resp.status == AgentExecutionState.FAILED
    assert "Kill Switch activo" in resp.response_text
    mock_skill_mgr.execute_skill.assert_not_called()
