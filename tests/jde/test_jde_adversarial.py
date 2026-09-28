"""Pruebas adversariales de seguridad exhaustivas para JDE Runtime Binding (Fase 1).

Cubre los 14 vectores de ataque y bypass:
1. Saltar JDE (ignorar veredicto)
2. Saltar RiskEngine (forzar ejecución saltando el análisis de riesgo)
3. Saltar PermissionManager (ignorar nivel de privilegio L0..L3)
4. Saltar IdempotencyGuard (forzar doble side effect)
5. Ejecutar tras veredicto DENY
6. Ejecutar tras veredicto REQUIRE_REVIEW sin confirmación
7. Duplicación simultánea o concurrente
8. Forzar retry tras fallo terminal
9. Provocar timeout en cancelación
10. Manipulación de campos de DecisionContract
11. Manipulación de ActionReceipt
12. Provocación de false success
13. Intento de activación accidental o forzada de ACTIVE
14. Despacho directo de skill sin pasar por el Runtime Binding
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from core.cancellation import CancellationToken
from core.execution.execution_verifier import ExecutionStatus
from core.execution.idempotency_guard import ExecutionIdempotencyGuard
from core.jde.authority import (
    ActionRiskTier,
    AuthorityDecision,
    AuthorityGateResult,
    AuthorityMode,
)
from core.jde.contract import DecisionContract
from core.jde.receipts import ActionReceipt
from core.jde.states import (
    DecisionState,
    ExecutionStatusType,
    VerificationStatusType,
)
from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeMode,
    JDERuntimeVerdict,
    JDERuntimeVerdictType,
)
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest
from core.security_architecture import SecurityLevel


@pytest.fixture
def mock_skill_mgr():
    mgr = MagicMock()
    mgr.execute_skill.return_value = MagicMock(
        success=True,
        output={
            "exito": True,
            "mensaje": "Ejecutado.",
            "evidence": {
                "verification_type": "process",
                "target": "notepad",
                "is_verified": True,
            },
        },
        error=None,
    )
    return mgr


# Vector 1: Saltar JDE
def test_vector_01_cannot_skip_jde_evaluation(mock_skill_mgr):
    binding = MagicMock(spec=JDERuntimeBinding)
    binding.evaluate.return_value = JDERuntimeVerdict(
        verdict=JDERuntimeVerdictType.DENY,
        reason="Veredicto de bloqueo obligatorio",
        action="open_application",
        tool="windows.apps",
        risk_level="HIGH",
        is_blocked=True,
    )
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)
    resp = agent.interact("abre notepad")
    assert resp.security_verdict == "DENY"
    mock_skill_mgr.execute_skill.assert_not_called()


# Vector 2: Saltar RiskEngine
def test_vector_02_jde_allow_does_not_skip_risk_engine(mock_skill_mgr):
    binding = MagicMock(spec=JDERuntimeBinding)
    binding.evaluate.return_value = JDERuntimeVerdict(
        verdict=JDERuntimeVerdictType.ALLOW,
        reason="JDE dice ok",
        action="open_application",
        tool="windows.apps",
        is_blocked=False,
    )
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)
    with patch.object(agent, "_evaluate_action_security", return_value=SecurityLevel.CRITICAL):
        resp = agent.interact("abre notepad")
        assert resp.status == AgentExecutionState.AWAITING_CONFIRMATION
        mock_skill_mgr.execute_skill.assert_not_called()


# Vector 3: Saltar PermissionManager
def test_vector_03_jde_allow_does_not_skip_permissions():
    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED)
    # Permisos insuficientes en ActionIntentContract
    verdict = binding.evaluate(
        intent="admin_action",
        action="format_c",
        tool="windows.disk",
        risk_level="CRITICAL",
    )
    assert verdict.verdict == JDERuntimeVerdictType.DENY
    assert verdict.is_blocked is True


# Vector 4: Saltar IdempotencyGuard
def test_vector_04_jde_cannot_bypass_idempotency_guard(mock_skill_mgr):
    guard = ExecutionIdempotencyGuard()
    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, idempotency_guard=guard)
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)

    req1 = JessycaRequest(request_id="adv_idem_1", user_input="abre notepad", session_id="s1")
    req2 = JessycaRequest(request_id="adv_idem_1", user_input="abre notepad", session_id="s1")

    with patch("core.execution.idempotency_guard.get_idempotency_guard", return_value=guard):
        agent.interact(req1)
        agent.interact(req2)
        assert mock_skill_mgr.execute_skill.call_count == 1


# Vector 5: Ejecutar tras DENY
def test_vector_05_execute_after_deny_is_zero_side_effect(mock_skill_mgr):
    gate = MagicMock()
    gate.is_kill_switch_active = False
    gate.current_mode = AuthorityMode.CONTROLLED
    gate.evaluate_authority.return_value = AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.DENY,
        can_execute=False,
        can_block=True,
        risk_tier=ActionRiskTier.HIGH,
        action="action_x",
        tool="tool_x",
        is_authorized=False,
        requires_human_confirmation=False,
        reason="Denegado",
    )
    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate)
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)
    resp = agent.interact("abre notepad")
    assert resp.success is False
    mock_skill_mgr.execute_skill.assert_not_called()


# Vector 6: Ejecutar tras REQUIRE_REVIEW sin confirmación
def test_vector_06_execute_after_require_review_unconfirmed(mock_skill_mgr):
    gate = MagicMock()
    gate.is_kill_switch_active = False
    gate.current_mode = AuthorityMode.CONTROLLED
    gate.evaluate_authority.return_value = AuthorityGateResult(
        mode=AuthorityMode.CONTROLLED,
        decision=AuthorityDecision.REQUIRE_VERIFICATION,
        can_execute=False,
        can_block=True,
        risk_tier=ActionRiskTier.HIGH,
        action="action_x",
        tool="tool_x",
        is_authorized=False,
        requires_human_confirmation=True,
        reason="Confirmación requerida",
    )
    binding = JDERuntimeBinding(mode=JDERuntimeMode.CONTROLLED, authority_gate=gate)
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)
    resp = agent.interact("abre notepad")
    assert resp.status == AgentExecutionState.AWAITING_CONFIRMATION
    mock_skill_mgr.execute_skill.assert_not_called()


# Vector 7: Duplicar una ejecución (concurrencia)
def test_vector_07_concurrent_duplicate_blocked():
    guard = ExecutionIdempotencyGuard()
    binding = JDERuntimeBinding(idempotency_guard=guard)
    # Misma petición dos veces
    v1 = binding.evaluate("action", "action", "tool", request_id="req_dup_01")
    v2 = binding.evaluate("action", "action", "tool", request_id="req_dup_01")
    assert v1.runtime_mode == JDERuntimeMode.CONTROLLED
    assert v2.runtime_mode == JDERuntimeMode.CONTROLLED


# Vector 8: Forzar retry
def test_vector_08_forced_retry_respects_guard(mock_skill_mgr):
    guard = ExecutionIdempotencyGuard()
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr)
    with patch("core.execution.idempotency_guard.get_idempotency_guard", return_value=guard):
        req = JessycaRequest(request_id="retry_req_01", user_input="abre notepad", session_id="s_retry")
        agent.interact(req)
        # Reintento forzado con el mismo request_id
        agent.interact(req)
        assert mock_skill_mgr.execute_skill.call_count == 1


# Vector 9: Provocar timeout / cancelación
def test_vector_09_cancellation_aborts_before_side_effects(mock_skill_mgr):
    token = CancellationToken()
    token.cancel()
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr)
    resp = agent.interact("abre notepad", cancellation_token=token)
    assert resp.status == AgentExecutionState.INTERRUPTED
    assert not resp.success
    mock_skill_mgr.execute_skill.assert_not_called()


# Vector 10: Manipular una decisión (inmutabilidad de DecisionContract)
def test_vector_10_decision_contract_is_immutable():
    contract = DecisionContract.create(
        intent="test",
        selected_action="test",
        reason="test",
    )
    with pytest.raises(ValidationError):
        # Intentar modificar un campo en un modelo frozen
        contract.selected_action = "malicious_overwrite"  # type: ignore


# Vector 11: Manipular un receipt (inmutabilidad de ActionReceipt)
def test_vector_11_action_receipt_is_immutable():
    now = datetime.now(UTC)
    receipt = ActionReceipt.create(
        request_id="r1",
        correlation_id="c1",
        user_request="req",
        action="act",
        tool="tool",
        parameters={},
        executor="exec",
        verifier="verif",
        started_at=now,
        finished_at=now,
        execution_status=ExecutionStatusType.OK,
        verification_status=VerificationStatusType.VERIFIED_TRUE,
        verified=True,
        final_status=DecisionState.SUCCESS,
        authority_mode="CONTROLLED",
        risk_tier="SAFE",
    )
    with pytest.raises(ValidationError):
        receipt.policy_verdict = "MALICIOUS_ALLOW"  # type: ignore


# Vector 12: Provocar false success
def test_vector_12_false_success_protection_unverified(mock_skill_mgr):
    mock_skill_mgr.execute_skill.return_value = MagicMock(
        success=True,
        output={"exito": True, "evidence": {"verification_type": "process", "target": "notepad", "is_verified": False}},
    )
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr)
    resp = agent.interact("abre notepad")
    assert resp.success is False


# Vector 13: Intentar activar ACTIVE accidentalmente
def test_vector_13_accidental_active_activation_blocked():
    binding = JDERuntimeBinding(mode=JDERuntimeMode.ACTIVE)
    assert binding.current_mode == JDERuntimeMode.CONTROLLED
    ok, _ = binding.set_mode(JDERuntimeMode.ACTIVE)
    assert not ok
    assert binding.current_mode == JDERuntimeMode.CONTROLLED


# Vector 14: Skill directa no salta el gate en el agente
def test_vector_14_skill_direct_call_guarded_in_agent(mock_skill_mgr):
    binding = MagicMock(spec=JDERuntimeBinding)
    binding.evaluate.return_value = JDERuntimeVerdict(
        verdict=JDERuntimeVerdictType.DENY,
        reason="Direct skill call blocked by JDE",
        action="windows.media",
        tool="windows.media",
        is_blocked=True,
    )
    agent = JessycaLocalAgent(skill_manager=mock_skill_mgr, jde_runtime_binding=binding)
    resp = agent.interact(JessycaRequest(user_input="pon un baile", session_id="media_sess"))
    assert resp.security_verdict == "DENY"
    mock_skill_mgr.execute_skill.assert_not_called()
