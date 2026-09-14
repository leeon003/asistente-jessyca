"""Tests unitarios rigurosos para Action Intent Contract (Fase 64.1.2).

Verifica exhaustivamente:
1. ActionIntent (rangos de confianza, no vacuidad, defaults seguros).
2. ExecutionGate (consistencia de aclaración y confirmación).
3. PreActionFeedback (opcionalidad y representación de acknowledgement).
4. ExecutionSpec (validación de skill_id e idempotency_key).
5. ActionExecutionReport (Invariante fundamental: Anti-False Success).
6. PostActionFeedback (no vacuidad de respuesta hablada, respuesta textual opcional).
7. ActionIntentContract (estados mínimo pre-ejecución y completo post-ejecución).
8. Identificadores no vacíos (request_id, session_id).
9. Inmutabilidad estricta (frozen=True).
10. Extra Forbid (rechazo de campos desconocidos).
11. Independencia de colecciones por defecto.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from core.action_intent_contract import (
    ActionExecutionReport,
    ActionIntent,
    ActionIntentContract,
    ExecutionGate,
    ExecutionSpec,
    PostActionFeedback,
    PreActionFeedback,
)

# ==============================================================================
# 1. TESTS DE ActionIntent
# ==============================================================================

def test_action_intent_valid_standard() -> None:
    """A) ActionIntent válido con todos los campos especificados."""
    intent = ActionIntent(
        intent_name="open_application",
        confidence=0.95,
        is_ambiguous=False,
        input_modality="voice",
        target="notepad",
        parameters={"app_name": "notepad"},
        missing_slots=["window_mode"],
    )
    assert intent.intent_name == "open_application"
    assert intent.confidence == 0.95
    assert intent.is_ambiguous is False
    assert intent.input_modality == "voice"
    assert intent.target == "notepad"
    assert intent.parameters == {"app_name": "notepad"}
    assert intent.missing_slots == ["window_mode"]


def test_action_intent_confidence_minimum() -> None:
    """B) confidence=0.0 debe ser válido (límite inferior)."""
    intent = ActionIntent(intent_name="unknown_action", confidence=0.0)
    assert intent.confidence == 0.0


def test_action_intent_confidence_maximum() -> None:
    """C) confidence=1.0 debe ser válido (límite superior)."""
    intent = ActionIntent(intent_name="direct_action", confidence=1.0)
    assert intent.confidence == 1.0


def test_action_intent_confidence_below_zero_rejected() -> None:
    """D) confidence < 0.0 debe lanzar ValidationError."""
    with pytest.raises(ValidationError):
        ActionIntent(intent_name="test", confidence=-0.01)


def test_action_intent_confidence_above_one_rejected() -> None:
    """E) confidence > 1.0 debe lanzar ValidationError."""
    with pytest.raises(ValidationError):
        ActionIntent(intent_name="test", confidence=1.01)


def test_action_intent_empty_name_rejected() -> None:
    """F) intent_name vacío debe lanzar ValidationError."""
    with pytest.raises(ValidationError):
        ActionIntent(intent_name="")


def test_action_intent_whitespace_name_rejected() -> None:
    """G) intent_name compuesto únicamente de espacios debe lanzar ValidationError."""
    with pytest.raises(ValidationError):
        ActionIntent(intent_name="   \t\n  ")


def test_action_intent_default_values_independent() -> None:
    """H) Los valores por defecto de parameters y missing_slots deben ser instancias independientes."""
    intent1 = ActionIntent(intent_name="intent1")
    intent2 = ActionIntent(intent_name="intent2")

    assert intent1.parameters == {}
    assert intent2.parameters == {}
    assert intent1.parameters is not intent2.parameters

    assert intent1.missing_slots == []
    assert intent2.missing_slots == []
    assert intent1.missing_slots is not intent2.missing_slots


# ==============================================================================
# 2. TESTS DE ExecutionGate
# ==============================================================================

def test_execution_gate_basic_valid() -> None:
    """A) Gate básico por defecto debe ser ejecutable sin aclaración ni confirmación."""
    gate = ExecutionGate()
    assert gate.can_execute is True
    assert gate.needs_clarification is False
    assert gate.clarification_prompt is None
    assert gate.needs_confirmation is False
    assert gate.risk_level is None
    assert gate.confirmation_prompt is None


def test_execution_gate_clarification_with_valid_prompt() -> None:
    """B) needs_clarification=True con prompt válido debe ser aceptado."""
    gate = ExecutionGate(
        can_execute=False,
        needs_clarification=True,
        clarification_prompt="¿Qué aplicación deseas abrir?",
    )
    assert gate.needs_clarification is True
    assert gate.clarification_prompt == "¿Qué aplicación deseas abrir?"


def test_execution_gate_clarification_without_prompt_rejected() -> None:
    """C) needs_clarification=True sin prompt (None) debe lanzar ValidationError."""
    with pytest.raises(ValidationError):
        ExecutionGate(needs_clarification=True, clarification_prompt=None)


def test_execution_gate_clarification_with_empty_prompt_rejected() -> None:
    """D) needs_clarification=True con prompt vacío debe lanzar ValidationError."""
    with pytest.raises(ValidationError):
        ExecutionGate(needs_clarification=True, clarification_prompt="   ")


def test_execution_gate_confirmation_with_valid_prompt() -> None:
    """E) needs_confirmation=True con confirmation_prompt válido debe ser aceptado."""
    gate = ExecutionGate(
        can_execute=False,
        needs_confirmation=True,
        risk_level="HIGH",
        confirmation_prompt="¿Estás seguro de eliminar este archivo?",
    )
    assert gate.needs_confirmation is True
    assert gate.risk_level == "HIGH"
    assert gate.confirmation_prompt == "¿Estás seguro de eliminar este archivo?"


def test_execution_gate_confirmation_without_prompt_rejected() -> None:
    """F) needs_confirmation=True sin confirmation_prompt (None) debe lanzar ValidationError."""
    with pytest.raises(ValidationError):
        ExecutionGate(needs_confirmation=True, confirmation_prompt=None)


def test_execution_gate_confirmation_with_empty_prompt_rejected() -> None:
    """G) needs_confirmation=True con confirmation_prompt vacío debe lanzar ValidationError."""
    with pytest.raises(ValidationError):
        ExecutionGate(needs_confirmation=True, confirmation_prompt="   ")


# ==============================================================================
# 3. TESTS DE PreActionFeedback
# ==============================================================================

def test_pre_action_feedback_none_valid() -> None:
    """A) acknowledgement_speech=None debe ser válido por defecto."""
    feedback = PreActionFeedback()
    assert feedback.acknowledgement_speech is None


def test_pre_action_feedback_with_text_valid() -> None:
    """B) acknowledgement_speech con texto explícito debe ser válido."""
    feedback = PreActionFeedback(acknowledgement_speech="Claro, voy a abrir el Bloc de notas.")
    assert feedback.acknowledgement_speech == "Claro, voy a abrir el Bloc de notas."


# ==============================================================================
# 4. TESTS DE ExecutionSpec
# ==============================================================================

def test_execution_spec_valid() -> None:
    """A, B y E) ExecutionSpec válido con skill_id, idempotency_key y tool_name opcional."""
    spec = ExecutionSpec(
        skill_id="windows.apps",
        tool_name="apps.open",
        idempotency_key="idemp-12345",
    )
    assert spec.skill_id == "windows.apps"
    assert spec.tool_name == "apps.open"
    assert spec.idempotency_key == "idemp-12345"


def test_execution_spec_tool_name_can_be_none() -> None:
    """E) tool_name puede ser None."""
    spec = ExecutionSpec(skill_id="windows.media", idempotency_key="idemp-67890")
    assert spec.tool_name is None


def test_execution_spec_empty_skill_id_rejected() -> None:
    """C) skill_id vacío debe lanzar ValidationError."""
    with pytest.raises(ValidationError):
        ExecutionSpec(skill_id="   ", idempotency_key="idemp-123")


def test_execution_spec_empty_idempotency_key_rejected() -> None:
    """D) idempotency_key vacío debe lanzar ValidationError."""
    with pytest.raises(ValidationError):
        ExecutionSpec(skill_id="windows.apps", idempotency_key="")


# ==============================================================================
# 5. TESTS CRÍTICOS DE ActionExecutionReport (ANTI-FALSE SUCCESS)
# ==============================================================================

def test_action_execution_report_verified_success_valid() -> None:
    """A) is_verified=True y claims_success=True debe ser válido."""
    report = ActionExecutionReport(
        skill_id="windows.apps",
        execution_status="SUCCEEDED",
        is_verified=True,
        claims_success=True,
        evidence={"pids": [1234]},
    )
    assert report.is_verified is True
    assert report.claims_success is True


def test_action_execution_report_verified_failure_valid() -> None:
    """B) is_verified=True y claims_success=False debe ser válido (verificación de terminación fallida o timeout)."""
    report = ActionExecutionReport(
        skill_id="windows.apps",
        execution_status="FAILED",
        is_verified=True,
        claims_success=False,
    )
    assert report.is_verified is True
    assert report.claims_success is False


def test_action_execution_report_unverified_failure_valid() -> None:
    """C) is_verified=False y claims_success=False debe ser válido."""
    report = ActionExecutionReport(
        skill_id="windows.apps",
        execution_status="FAILED",
        is_verified=False,
        claims_success=False,
    )
    assert report.is_verified is False
    assert report.claims_success is False


def test_anti_false_success_rejects_unverified_success_claim() -> None:
    """D) REGLA CRÍTICA OBLIGATORIA: is_verified=False con claims_success=True DEBE lanzar ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        ActionExecutionReport(
            skill_id="windows.apps",
            execution_status="SUCCEEDED",
            is_verified=False,
            claims_success=True,
            evidence={},
        )
    assert "Anti-False Success" in str(exc_info.value)


# ==============================================================================
# 6. TESTS DE PostActionFeedback
# ==============================================================================

def test_post_action_feedback_valid() -> None:
    """A y D) PostActionFeedback con spoken_response válido y response_text opcional."""
    feedback = PostActionFeedback(
        spoken_response="Listo, abrí el Bloc de notas.",
        response_text="Listo, abrí el Bloc de notas. (PID 4321)",
    )
    assert feedback.spoken_response == "Listo, abrí el Bloc de notas."
    assert feedback.response_text == "Listo, abrí el Bloc de notas. (PID 4321)"


def test_post_action_feedback_response_text_none_valid() -> None:
    """D) response_text puede ser None."""
    feedback = PostActionFeedback(spoken_response="Listo, abrí la Calculadora.")
    assert feedback.response_text is None


def test_post_action_feedback_empty_spoken_response_rejected() -> None:
    """B) spoken_response vacío debe lanzar ValidationError."""
    with pytest.raises(ValidationError):
        PostActionFeedback(spoken_response="")


def test_post_action_feedback_whitespace_spoken_response_rejected() -> None:
    """C) spoken_response compuesto únicamente por espacios debe lanzar ValidationError."""
    with pytest.raises(ValidationError):
        PostActionFeedback(spoken_response="   \n\t  ")


# ==============================================================================
# 7. TESTS DE ActionIntentContract
# ==============================================================================

def test_action_intent_contract_minimal_valid() -> None:
    """Creación de un contrato mínimo válido antes de la ejecución (execution_report=None)."""
    intent = ActionIntent(intent_name="open_application", target="notepad")
    gate = ExecutionGate(can_execute=True)
    feedback = PreActionFeedback(acknowledgement_speech="Abriendo el Bloc de notas...")

    contract = ActionIntentContract(
        request_id="req-1001",
        session_id="session-001",
        action_intent=intent,
        execution_gate=gate,
        pre_action_feedback=feedback,
    )

    assert contract.request_id == "req-1001"
    assert contract.session_id == "session-001"
    assert contract.action_intent.intent_name == "open_application"
    assert contract.execution_gate.can_execute is True
    assert contract.execution_spec is None
    assert contract.execution_report is None
    assert contract.post_action_feedback is None
    assert isinstance(contract.created_at, datetime)


def test_action_intent_contract_full_valid() -> None:
    """Creación de un contrato completo con todos los submódulos integrados."""
    intent = ActionIntent(
        intent_name="open_application",
        confidence=1.0,
        target="calc",
        parameters={"app_name": "calc"},
    )
    gate = ExecutionGate(can_execute=True)
    pre_fb = PreActionFeedback(acknowledgement_speech="Abriendo la Calculadora...")
    spec = ExecutionSpec(skill_id="windows.apps", idempotency_key="idemp-calc-1")
    report = ActionExecutionReport(
        skill_id="windows.apps",
        execution_status="SUCCEEDED",
        is_verified=True,
        claims_success=True,
        evidence={"pids": [9999]},
    )
    post_fb = PostActionFeedback(spoken_response="Listo, abrí la Calculadora.")

    contract = ActionIntentContract(
        request_id="req-1002",
        session_id="session-002",
        action_intent=intent,
        execution_gate=gate,
        pre_action_feedback=pre_fb,
        execution_spec=spec,
        execution_report=report,
        post_action_feedback=post_fb,
    )

    assert contract.execution_spec is not None
    assert contract.execution_spec.skill_id == "windows.apps"
    assert contract.execution_report is not None
    assert contract.execution_report.claims_success is True
    assert contract.post_action_feedback is not None
    assert contract.post_action_feedback.spoken_response == "Listo, abrí la Calculadora."


# ==============================================================================
# 8. TESTS DE IDENTIFICADORES EN ActionIntentContract
# ==============================================================================

def test_contract_empty_request_id_rejected() -> None:
    """request_id vacío debe lanzar ValidationError."""
    intent = ActionIntent(intent_name="test")
    gate = ExecutionGate()
    with pytest.raises(ValidationError):
        ActionIntentContract(
            request_id="",
            session_id="sess-01",
            action_intent=intent,
            execution_gate=gate,
        )


def test_contract_whitespace_request_id_rejected() -> None:
    """request_id con espacios debe lanzar ValidationError."""
    intent = ActionIntent(intent_name="test")
    gate = ExecutionGate()
    with pytest.raises(ValidationError):
        ActionIntentContract(
            request_id="   ",
            session_id="sess-01",
            action_intent=intent,
            execution_gate=gate,
        )


def test_contract_empty_session_id_rejected() -> None:
    """session_id vacío debe lanzar ValidationError."""
    intent = ActionIntent(intent_name="test")
    gate = ExecutionGate()
    with pytest.raises(ValidationError):
        ActionIntentContract(
            request_id="req-01",
            session_id="",
            action_intent=intent,
            execution_gate=gate,
        )


def test_contract_whitespace_session_id_rejected() -> None:
    """session_id con espacios debe lanzar ValidationError."""
    intent = ActionIntent(intent_name="test")
    gate = ExecutionGate()
    with pytest.raises(ValidationError):
        ActionIntentContract(
            request_id="req-01",
            session_id="  \t  ",
            action_intent=intent,
            execution_gate=gate,
        )


# ==============================================================================
# 9. TESTS DE INMUTABILIDAD (frozen=True)
# ==============================================================================

def test_action_intent_immutability() -> None:
    """Verificar que intentar mutar un atributo de ActionIntent lance ValidationError."""
    intent = ActionIntent(intent_name="open_application")
    with pytest.raises(ValidationError):
        intent.intent_name = "close_application"


def test_action_intent_contract_immutability() -> None:
    """Verificar que intentar mutar un atributo de ActionIntentContract lance ValidationError."""
    contract = ActionIntentContract(
        request_id="req-1",
        session_id="sess-1",
        action_intent=ActionIntent(intent_name="test"),
        execution_gate=ExecutionGate(),
    )
    with pytest.raises(ValidationError):
        contract.request_id = "req-2"


# ==============================================================================
# 10. TEST DE EXTRA FORBID
# ==============================================================================

def test_extra_forbid_rejects_unknown_fields() -> None:
    """Verificar que introducir un campo no declarado provoque ValidationError."""
    with pytest.raises(ValidationError):
        ActionIntent(
            intent_name="open_application",
            campo_inexistente="valor_invalido",  # type: ignore[call-arg]
        )

    with pytest.raises(ValidationError):
        ExecutionGate(
            unknown_parameter=123,  # type: ignore[call-arg]
        )


# ==============================================================================
# 11. TEST DE INDEPENDENCIA DE DEFAULTS
# ==============================================================================

def test_independence_of_defaults_parameters_and_slots() -> None:
    """Demostrar que parameters y missing_slots no comparten estado mutable entre instancias."""
    intent_a = ActionIntent(intent_name="a", parameters={"key": "val_a"}, missing_slots=["slot_a"])
    intent_b = ActionIntent(intent_name="b")

    assert "key" in intent_a.parameters
    assert "key" not in intent_b.parameters

    assert "slot_a" in intent_a.missing_slots
    assert "slot_a" not in intent_b.missing_slots
