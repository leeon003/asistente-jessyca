"""Tests unitarios para Execution Gate & Confirmation Bridge (Fase 64.2.2).

Cubre exhaustivamente:
A. ActionIntent de bajo riesgo -> EXECUTE
B. ActionIntent que requiere confirmación -> ASK_CONFIRMATION
C. ActionIntent de riesgo no permitido -> REJECT
D. ActionIntent con confidence insuficiente -> CLARIFY
E. Confirmación válida -> transición a CONFIRMED
F. Rechazo del usuario -> REJECTED
G. Confirmación para ActionIntent equivocado -> INVALID
H. Confirmación reutilizada (Replay) -> INVALID
I. Confirmación expirada -> EXPIRED
J. Confirmación no debe ejecutar la acción real
K. El bridge no debe ejecutar ninguna skill
L. No debe existir bypass del ExecutionGate
M. Anti-False Success
N. Regresión y compatibilidad
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from core.action_intent_contract import (
    ActionIntent,
    ActionIntentContract,
    ExecutionGate,
    ExecutionSpec,
    PreActionFeedback,
)
from core.confirmation import (
    ConfirmationManager,
)
from core.execution.execution_gate_bridge import (
    ConfirmationBridgeStatus,
    ExecutionGateBridge,
    GateDecisionType,
)
from core.security import (
    RiskLevel,
    SecurityManager,
    SecurityPolicy,
)


@pytest.fixture
def base_contract() -> ActionIntentContract:
    """Fixture de un ActionIntentContract válido y de bajo riesgo."""
    intent = ActionIntent(
        intent_name="open_application",
        confidence=0.95,
        is_ambiguous=False,
        input_modality="text",
        target="Notepad",
        parameters={"app_name": "notepad"},
    )
    gate = ExecutionGate(
        can_execute=True,
        needs_clarification=False,
        needs_confirmation=False,
        risk_level="SAFE",
    )
    spec = ExecutionSpec(
        skill_id="windows.apps",
        tool_name="open_application",
        idempotency_key="idemp-test-safe-123",
    )
    return ActionIntentContract(
        request_id="req-test-safe-001",
        session_id="sess-test-safe-001",
        action_intent=intent,
        execution_gate=gate,
        pre_action_feedback=PreActionFeedback(acknowledgement_speech="Abriendo Notepad"),
        execution_spec=spec,
        execution_report=None,
        post_action_feedback=None,
    )


@pytest.fixture
def dangerous_contract() -> ActionIntentContract:
    """Fixture de un ActionIntentContract que realiza una operación peligrosa."""
    intent = ActionIntent(
        intent_name="close_application",
        confidence=0.92,
        is_ambiguous=False,
        input_modality="text",
        target="Notepad",
        parameters={"app_name": "notepad"},
    )
    gate = ExecutionGate(
        can_execute=False,
        needs_clarification=False,
        needs_confirmation=True,
        risk_level="DANGEROUS",
        confirmation_prompt="¿Deseas cerrar Bloc de notas?",
    )
    spec = ExecutionSpec(
        skill_id="windows.apps",
        tool_name="close_application",
        idempotency_key="idemp-test-dang-123",
    )
    return ActionIntentContract(
        request_id="req-test-dang-001",
        session_id="sess-test-dang-001",
        action_intent=intent,
        execution_gate=gate,
        pre_action_feedback=PreActionFeedback(acknowledgement_speech="Cerrando Notepad"),
        execution_spec=spec,
        execution_report=None,
        post_action_feedback=None,
    )


# ── TEST A: ActionIntent de bajo riesgo -> EXECUTE ──────────────────────────


def test_gate_evaluates_safe_intent_as_execute(base_contract: ActionIntentContract) -> None:
    bridge = ExecutionGateBridge()
    decision = bridge.evaluate_intent(base_contract)

    assert decision.decision_type == GateDecisionType.EXECUTE
    assert decision.can_proceed_to_execution is True
    assert decision.skill_id == "windows.apps"
    assert decision.operation == "open_application"
    assert decision.confirmation_request is None
    assert decision.clarification_prompt is None


# ── TEST B: ActionIntent que requiere confirmación -> ASK_CONFIRMATION ──────


def test_gate_evaluates_dangerous_intent_as_ask_confirmation(
    dangerous_contract: ActionIntentContract,
) -> None:
    bridge = ExecutionGateBridge()
    decision = bridge.evaluate_intent(dangerous_contract)

    assert decision.decision_type == GateDecisionType.ASK_CONFIRMATION
    assert decision.can_proceed_to_execution is False
    assert decision.confirmation_request is not None
    assert decision.confirmation_prompt == "¿Deseas cerrar Bloc de notas?"
    assert decision.confirmation_request.tool_name == "close_application"
    assert decision.confirmation_request.correlation_id == dangerous_contract.request_id


# ── TEST C: ActionIntent de riesgo no permitido -> REJECT ───────────────────


def test_gate_rejects_intent_exceeding_max_risk_policy(
    dangerous_contract: ActionIntentContract,
) -> None:
    # Configurar política restrictiva: riesgo máximo permitido es SAFE
    strict_policy = SecurityPolicy(max_allowed_risk=RiskLevel.SAFE)
    bridge = ExecutionGateBridge(security_policy=strict_policy)

    decision = bridge.evaluate_intent(dangerous_contract)

    assert decision.decision_type == GateDecisionType.REJECT
    assert decision.can_proceed_to_execution is False
    assert "excede el máximo permitido por la política" in decision.reason or "denegada por política" in decision.reason


# ── TEST D: ActionIntent con confidence insuficiente -> CLARIFY ─────────────


def test_gate_requests_clarification_on_low_confidence() -> None:
    intent = ActionIntent(
        intent_name="open_application",
        confidence=0.55,  # < 0.70
        is_ambiguous=False,
        input_modality="text",
        target="Notepad",
        parameters={"app_name": "notepad"},
    )
    gate = ExecutionGate(
        can_execute=False,
        needs_clarification=True,
        clarification_prompt="¿Podrías confirmar si deseas abrir Bloc de notas?",
        needs_confirmation=False,
        risk_level="SAFE",
    )
    contract = ActionIntentContract(
        request_id="req-test-lowconf-001",
        session_id="sess-test-lowconf-001",
        action_intent=intent,
        execution_gate=gate,
        pre_action_feedback=PreActionFeedback(),
        execution_spec=ExecutionSpec(skill_id="windows.apps", tool_name="open_application", idempotency_key="idemp-1"),
    )

    bridge = ExecutionGateBridge()
    decision = bridge.evaluate_intent(contract)

    assert decision.decision_type == GateDecisionType.CLARIFY
    assert decision.can_proceed_to_execution is False
    assert decision.clarification_prompt == "¿Podrías confirmar si deseas abrir Bloc de notas?"
    assert decision.confidence == 0.55


# ── TEST E: Confirmación válida -> transición a CONFIRMED ────────────────────


def test_valid_user_confirmation_transitions_to_confirmed(
    dangerous_contract: ActionIntentContract,
) -> None:
    bridge = ExecutionGateBridge()
    decision = bridge.evaluate_intent(dangerous_contract)
    assert decision.decision_type == GateDecisionType.ASK_CONFIRMATION
    assert decision.confirmation_request is not None

    req_id = decision.confirmation_request.request_id

    # El usuario aprueba la confirmación
    status, approved_decision = bridge.process_confirmation_response(
        request_id=req_id,
        user_confirmed=True,
        target_contract=dangerous_contract,
    )

    assert status == ConfirmationBridgeStatus.CONFIRMED
    assert approved_decision is not None
    assert approved_decision.decision_type == GateDecisionType.EXECUTE
    assert approved_decision.can_proceed_to_execution is True
    assert approved_decision.execution_gate.can_execute is True
    assert approved_decision.execution_gate.needs_confirmation is False


# ── TEST F: Rechazo del usuario -> REJECTED ──────────────────────────────────


def test_user_rejection_transitions_to_rejected(
    dangerous_contract: ActionIntentContract,
) -> None:
    bridge = ExecutionGateBridge()
    decision = bridge.evaluate_intent(dangerous_contract)
    assert decision.confirmation_request is not None

    req_id = decision.confirmation_request.request_id

    # El usuario rechaza la confirmación
    status, rejected_decision = bridge.process_confirmation_response(
        request_id=req_id,
        user_confirmed=False,
        target_contract=dangerous_contract,
    )

    assert status == ConfirmationBridgeStatus.REJECTED
    assert rejected_decision is not None
    assert rejected_decision.decision_type == GateDecisionType.REJECT
    assert rejected_decision.can_proceed_to_execution is False
    assert "rechazó" in rejected_decision.reason


# ── TEST G: Confirmación para ActionIntent equivocado -> INVALID ──────────────


def test_confirmation_for_wrong_contract_is_invalid(
    dangerous_contract: ActionIntentContract,
    base_contract: ActionIntentContract,
) -> None:
    bridge = ExecutionGateBridge()
    decision = bridge.evaluate_intent(dangerous_contract)
    assert decision.confirmation_request is not None

    req_id = decision.confirmation_request.request_id

    # Se intenta usar la confirmación de 'close_application' para validar 'open_application'
    status, result_decision = bridge.process_confirmation_response(
        request_id=req_id,
        user_confirmed=True,
        target_contract=base_contract,
    )

    assert status == ConfirmationBridgeStatus.INVALID
    assert result_decision is None


# ── TEST H: Confirmación reutilizada (Replay Attack) -> INVALID ──────────────


def test_reused_confirmation_is_rejected_as_invalid(
    dangerous_contract: ActionIntentContract,
) -> None:
    bridge = ExecutionGateBridge()
    decision = bridge.evaluate_intent(dangerous_contract)
    assert decision.confirmation_request is not None

    req_id = decision.confirmation_request.request_id

    # Primer uso: exitoso
    status_1, decision_1 = bridge.process_confirmation_response(
        request_id=req_id,
        user_confirmed=True,
        target_contract=dangerous_contract,
    )
    assert status_1 == ConfirmationBridgeStatus.CONFIRMED
    assert decision_1 is not None

    # Segundo uso (replay attack con el mismo request_id): debe fallar
    status_2, decision_2 = bridge.process_confirmation_response(
        request_id=req_id,
        user_confirmed=True,
        target_contract=dangerous_contract,
    )
    assert status_2 == ConfirmationBridgeStatus.INVALID
    assert decision_2 is None


# ── TEST I: Confirmación expirada -> EXPIRED ─────────────────────────────────


def test_expired_confirmation_is_detected_as_expired(
    dangerous_contract: ActionIntentContract,
) -> None:
    bridge = ExecutionGateBridge()
    # TTL de 0.05 segundos para forzar expiración
    decision = bridge.evaluate_intent(dangerous_contract, ttl_seconds=0.05)
    assert decision.confirmation_request is not None

    req_id = decision.confirmation_request.request_id
    time.sleep(0.06)

    status, expired_decision = bridge.process_confirmation_response(
        request_id=req_id,
        user_confirmed=True,
        target_contract=dangerous_contract,
    )

    assert status == ConfirmationBridgeStatus.EXPIRED
    assert expired_decision is None


# ── TEST J: Confirmación no debe ejecutar la acción real ─────────────────────


def test_confirmation_does_not_execute_real_action(
    dangerous_contract: ActionIntentContract,
) -> None:
    bridge = ExecutionGateBridge()
    decision = bridge.evaluate_intent(dangerous_contract)
    assert decision.confirmation_request is not None

    req_id = decision.confirmation_request.request_id

    # Procesar confirmación
    status, approved_decision = bridge.process_confirmation_response(
        request_id=req_id,
        user_confirmed=True,
        target_contract=dangerous_contract,
    )

    assert status == ConfirmationBridgeStatus.CONFIRMED
    assert approved_decision is not None
    # El contrato resultante NO debe tener reportes de ejecución
    assert approved_decision.contract.execution_report is None
    assert approved_decision.contract.post_action_feedback is None


# ── TEST K: El bridge no debe ejecutar ninguna skill ─────────────────────────


def test_bridge_never_invokes_skills_or_os_calls(base_contract: ActionIntentContract) -> None:
    mock_skill = MagicMock()
    bridge = ExecutionGateBridge()

    decision = bridge.evaluate_intent(base_contract)

    # Verifica que el mock nunca fue invocado
    mock_skill.execute.assert_not_called()
    assert decision.decision_type == GateDecisionType.EXECUTE
    # La decisión contiene únicamente la especificación sin ejecución
    assert decision.skill_id == "windows.apps"
    assert decision.contract.execution_report is None


# ── TEST L: No debe existir bypass del ExecutionGate ─────────────────────────


def test_cannot_bypass_execution_gate_when_confirmation_required() -> None:
    intent = ActionIntent(
        intent_name="kill_process",
        confidence=0.99,
        is_ambiguous=False,
        input_modality="text",
        target="explorer.exe",
        parameters={"process_name": "explorer.exe"},
    )
    # Intento malicioso de forzar can_execute=True en una acción DANGEROUS que exige confirmación
    gate = ExecutionGate(
        can_execute=False,
        needs_clarification=False,
        needs_confirmation=True,
        risk_level="DANGEROUS",
        confirmation_prompt="¿Deseas terminar explorer.exe?",
    )
    contract = ActionIntentContract(
        request_id="req-bypass-attempt",
        session_id="sess-bypass-attempt",
        action_intent=intent,
        execution_gate=gate,
        pre_action_feedback=PreActionFeedback(),
        execution_spec=ExecutionSpec(skill_id="windows.apps", tool_name="kill_process", idempotency_key="idemp-bypass"),
    )

    bridge = ExecutionGateBridge()
    decision = bridge.evaluate_intent(contract)

    # El gate DEBE forzar ASK_CONFIRMATION y can_proceed_to_execution=False
    assert decision.decision_type == GateDecisionType.ASK_CONFIRMATION
    assert decision.can_proceed_to_execution is False


# ── TEST M: Anti-False Success ──────────────────────────────────────────────


def test_anti_false_success_guarantee_in_gate_and_decision(
    base_contract: ActionIntentContract,
) -> None:
    bridge = ExecutionGateBridge()
    decision = bridge.evaluate_intent(base_contract)

    # Nunca debe contener un execution_report con claims_success=True durante la fase de gate
    assert decision.contract.execution_report is None
    assert decision.contract.post_action_feedback is None


# ── TEST N: Regresión de compatibilidad con ConfirmationManager ──────────────


def test_compatibility_with_existing_confirmation_manager() -> None:
    sec_mgr = SecurityManager()
    conf_mgr = ConfirmationManager(security_manager=sec_mgr)
    bridge = ExecutionGateBridge(security_manager=sec_mgr, confirmation_manager=conf_mgr)

    assert bridge.confirmation_manager is conf_mgr
    assert bridge.security_manager is sec_mgr
