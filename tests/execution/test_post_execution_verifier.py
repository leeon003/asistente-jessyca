"""Tests unitarios exhaustivos para Post-Execution Verification (Fase 64.2.4).

Cubre rigurosamente:
A. Skill SUCCESS + verificación positiva -> VERIFIED_SUCCESS
B. Skill SUCCESS + verificación negativa -> VERIFIED_FAILURE
C. Skill FAILURE -> no convertir en VERIFIED_SUCCESS
D. Acción no verificable -> UNVERIFIED
E. Error del verifier -> VERIFICATION_ERROR
F. Resultado parcial -> PARTIAL_SUCCESS
G. action_id se conserva durante todo el pipeline
H. expected_effect se conserva
I. observed_effect se registra
J. Dispatcher SUCCESS no implica automáticamente VERIFIED_SUCCESS
K. Una acción verificada como fallida no debe generar feedback de éxito
L. Acción rechazada por ExecutionGate no llega al verifier como ejecutada
M. Mock verifier positivo
N. Mock verifier negativo
O. Mock verifier que lanza excepción
P. Invariantes estrictas de Anti-False Success en VerificationReport
TEST ESPECIAL: Fake action "open_application(notepad)" (positivo, negativo, excepción)
TEST ESPECIAL: Fake action "close_application(notepad)" (terminación exitosa vs proceso residual)
"""

from __future__ import annotations

from typing import Any

import pytest

from core.action_intent_contract import (
    ActionExecutionReport,
    ActionIntent,
    ActionIntentContract,
    ExecutionGate,
    ExecutionSpec,
    PreActionFeedback,
)
from core.execution.execution_dispatcher import (
    DispatchResult,
    DispatchStatus,
)
from core.execution.post_execution_verifier import (
    PostExecutionVerifier,
    VerificationReport,
    VerificationReportStatus,
)

# ── FIXTURES Y MOCKS ──


class MockBooleanVerifier:
    """Mock verifier que expone la presencia o ausencia de proceso."""

    def __init__(self, process_exists: bool = True) -> None:
        self.process_exists = process_exists


class MockExceptionVerifier:
    """Mock verifier que simula fallo catastrófico en el mecanismo de inspección."""

    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc or RuntimeError("Error de comunicación con subsistema WMI/OS")

    def verify_execution(self, *args: Any, **kwargs: Any) -> Any:
        raise self.exc

    def verify_action(self, *args: Any, **kwargs: Any) -> Any:
        raise self.exc


class MockCustomActionVerifier:
    """Mock verifier que devuelve resultados específicos por acción."""

    def __init__(self, observed_text: str, is_ok: bool) -> None:
        self.observed_text = observed_text
        self.is_ok = is_ok

    def verify_action(self, operation: str, target: str, parameters: dict[str, Any]) -> tuple[str, bool]:
        return self.observed_text, self.is_ok


def make_test_contract(
    request_id: str = "req-test-verify-001",
    action_type: str = "open_application",
    target: str = "notepad",
    can_execute: bool = True,
    skill_id: str = "windows.apps",
    tool_name: str = "apps.open",
) -> ActionIntentContract:
    """Construye un contrato válido de prueba."""
    intent = ActionIntent(
        intent_name=action_type,
        confidence=0.95,
        parameters={"nombre_app": target, "target": target},
    )
    gate = ExecutionGate(
        can_execute=can_execute,
        needs_clarification=False,
        needs_confirmation=False,
    )
    spec = ExecutionSpec(
        skill_id=skill_id,
        tool_name=tool_name,
        idempotency_key=f"idem-{request_id}",
    )
    return ActionIntentContract(
        request_id=request_id,
        session_id="session-verify-001",
        action_intent=intent,
        execution_gate=gate,
        pre_action_feedback=PreActionFeedback(acknowledgement_speech="Abriendo aplicación."),
        execution_spec=spec,
    )


# ── TESTS PRINCIPALES ──


def test_a_skill_success_and_verification_positive() -> None:
    """A. Skill SUCCESS + verificación positiva -> VERIFIED_SUCCESS."""
    contract = make_test_contract(target="notepad")
    verifier = PostExecutionVerifier()

    exec_report = ActionExecutionReport(
        skill_id="windows.apps",
        tool_name="apps.open",
        execution_status="success",
        is_verified=True,
        claims_success=True,
        evidence={
            "verification_type": "process_exists",
            "target": "notepad",
            "is_verified": True,
            "details": {"pids": [1234]},
        },
    )

    mock_v = MockBooleanVerifier(process_exists=True)
    report = verifier.verify(
        intent=contract,
        execution=exec_report,
        custom_verifier=mock_v,
    )

    assert report.verification_status == VerificationReportStatus.VERIFIED_SUCCESS
    assert report.claims_success is True
    assert report.is_verified is True
    assert "notepad" in report.observed_effect.lower()
    assert report.error is None
    assert "Listo" in str(report.feedback_suggestion)


def test_b_skill_success_and_verification_negative() -> None:
    """B. Skill SUCCESS + verificación negativa -> VERIFIED_FAILURE (Anti-False Success)."""
    contract = make_test_contract(target="notepad")
    verifier = PostExecutionVerifier()

    # La skill devolvió éxito aparente
    exec_report = ActionExecutionReport(
        skill_id="windows.apps",
        tool_name="apps.open",
        execution_status="success",
        is_verified=True,
        claims_success=True,
        evidence={"target": "notepad"},
    )

    # Pero el verifier observa que el proceso NO existe
    mock_v = MockBooleanVerifier(process_exists=False)
    report = verifier.verify(
        intent=contract,
        execution=exec_report,
        custom_verifier=mock_v,
    )

    assert report.verification_status == VerificationReportStatus.VERIFIED_FAILURE
    assert report.claims_success is False
    assert report.is_verified is True
    assert "no existe" in report.observed_effect.lower()
    assert report.error is not None
    assert "No pude confirmar" in str(report.feedback_suggestion)


def test_c_skill_failure_never_becomes_verified_success() -> None:
    """C. Skill FAILURE -> nunca se convierte en VERIFIED_SUCCESS."""
    contract = make_test_contract(target="calc")
    verifier = PostExecutionVerifier()

    exec_report = ActionExecutionReport(
        skill_id="windows.apps",
        tool_name="apps.open",
        execution_status="failed",
        is_verified=False,
        claims_success=False,
        evidence={},
        error_code="SPAWN_FAILED",
    )

    # Aunque el mock dijera process_exists=True, la ejecución falló
    mock_v = MockBooleanVerifier(process_exists=True)
    report = verifier.verify(
        intent=contract,
        execution=exec_report,
        custom_verifier=mock_v,
    )

    assert report.verification_status != VerificationReportStatus.VERIFIED_SUCCESS
    assert report.verification_status == VerificationReportStatus.VERIFIED_FAILURE
    assert report.claims_success is False
    assert "fallida" in report.observed_effect.lower() or "fallo" in report.observed_effect.lower()


def test_d_non_verifiable_action_produces_unverified() -> None:
    """D. Acción no verificable -> UNVERIFIED (sin falsos éxitos)."""
    intent = ActionIntent(
        intent_name="chat_response",
        confidence=0.99,
        parameters={"text": "¿Cómo estás?"},
    )
    contract = ActionIntentContract(
        request_id="req-chat-unverified",
        session_id="session-001",
        action_intent=intent,
        execution_gate=ExecutionGate(can_execute=True),
        execution_spec=ExecutionSpec(skill_id="system.chat", idempotency_key="idem-chat-01"),
    )

    verifier = PostExecutionVerifier()
    exec_report = ActionExecutionReport(
        skill_id="system.chat",
        tool_name="chat_response",
        execution_status="success",
        is_verified=True,
        claims_success=True,
    )

    report = verifier.verify(intent=contract, execution=exec_report)

    assert report.verification_status == VerificationReportStatus.UNVERIFIED
    assert report.claims_success is False
    assert report.is_verified is False
    assert "no pude verificar" in str(report.feedback_suggestion).lower()


def test_e_verifier_error_produces_verification_error() -> None:
    """E. Error del verifier -> VERIFICATION_ERROR (no asume éxito)."""
    contract = make_test_contract(target="notepad")
    verifier = PostExecutionVerifier()

    exec_report = ActionExecutionReport(
        skill_id="windows.apps",
        tool_name="apps.open",
        execution_status="success",
        is_verified=True,
        claims_success=True,
    )

    mock_exc = MockExceptionVerifier(TimeoutError("Límite de tiempo en IPC"))
    report = verifier.verify(
        intent=contract,
        execution=exec_report,
        custom_verifier=mock_exc,
    )

    assert report.verification_status == VerificationReportStatus.VERIFICATION_ERROR
    assert report.claims_success is False
    assert report.is_verified is False
    assert "Límite de tiempo en IPC" in str(report.error)
    assert "problema al comprobar" in str(report.feedback_suggestion).lower()


def test_f_partial_success_produces_partial_status() -> None:
    """F. Resultado parcial -> PARTIAL_SUCCESS (no declara éxito completo)."""
    contract = make_test_contract(target="multiapp")
    verifier = PostExecutionVerifier()

    # Simular ejecución que indica éxito parcial
    exec_report = ActionExecutionReport(
        skill_id="windows.apps",
        tool_name="apps.close_multiple",
        execution_status="success",
        is_verified=True,
        claims_success=True,
        evidence={"is_partial": True, "details": {"partial_reason": "Se cerró app1 pero no app2"}},
    )

    report = verifier.verify(
        intent=contract,
        execution=exec_report,
        parameters={"is_partial": True, "partial_details": "Se cerró app1 pero no app2"},
    )

    assert report.verification_status == VerificationReportStatus.PARTIAL_SUCCESS
    assert report.claims_success is False  # Regla: NO declarar éxito completo
    assert report.is_verified is True
    assert "parcialmente" in str(report.feedback_suggestion).lower()


def test_g_action_id_preserved_across_report() -> None:
    """G. action_id se conserva estrictamente."""
    contract = make_test_contract(request_id="req-custom-preserved-999")
    verifier = PostExecutionVerifier()

    mock_v = MockBooleanVerifier(process_exists=True)
    report = verifier.verify(
        intent=contract,
        execution={"is_success": True, "status": "SUCCESS"},
        custom_verifier=mock_v,
    )

    assert report.action_id == "req-custom-preserved-999"


def test_h_expected_effect_preserved() -> None:
    """H. expected_effect se conserva y describe la expectativa."""
    contract = make_test_contract(target="notepad")
    verifier = PostExecutionVerifier()

    mock_v = MockBooleanVerifier(process_exists=True)
    report = verifier.verify(intent=contract, execution={"is_success": True}, custom_verifier=mock_v)

    assert report.expected_effect is not None
    assert len(report.expected_effect) > 0
    assert "notepad" in report.expected_effect.lower()


def test_i_observed_effect_recorded() -> None:
    """I. observed_effect se registra de forma determinista."""
    contract = make_test_contract(target="calc")
    verifier = PostExecutionVerifier()

    mock_v = MockBooleanVerifier(process_exists=False)
    report = verifier.verify(intent=contract, execution={"is_success": True}, custom_verifier=mock_v)

    assert report.observed_effect is not None
    assert "no existe" in report.observed_effect.lower()


def test_j_dispatcher_success_does_not_imply_verified_success() -> None:
    """J. Dispatcher SUCCESS no implica automáticamente VERIFIED_SUCCESS."""
    contract = make_test_contract(target="paint")

    # Dispatcher entrega un resultado formalmente SUCCESS
    dispatch_result = DispatchResult(
        action_id=contract.request_id,
        skill_id="windows.apps",
        operation="apps.open",
        status=DispatchStatus.SUCCESS,
        is_success=True,
        execution_report=ActionExecutionReport(
            skill_id="windows.apps",
            tool_name="apps.open",
            execution_status="success",
            is_verified=True,
            claims_success=True,
        ),
        contract=contract,
        duration_ms=50.0,
        output={"exito": True},
    )

    verifier = PostExecutionVerifier()
    # El sistema real informa que el proceso no está
    mock_v = MockBooleanVerifier(process_exists=False)

    report = verifier.verify(intent=contract, execution=dispatch_result, custom_verifier=mock_v)

    # Invariante: Aunque Dispatcher dijo SUCCESS, el verifier dice VERIFIED_FAILURE
    assert report.verification_status == VerificationReportStatus.VERIFIED_FAILURE
    assert report.claims_success is False


def test_k_verified_failure_does_not_generate_success_feedback() -> None:
    """K. Una acción verificada como fallida no debe generar feedback de éxito."""
    contract = make_test_contract(target="notepad")
    verifier = PostExecutionVerifier()

    mock_v = MockBooleanVerifier(process_exists=False)
    report = verifier.verify(intent=contract, execution={"is_success": True}, custom_verifier=mock_v)

    feedback = report.to_post_action_feedback()
    # No puede contener "Listo" ni confirmar apertura
    assert "listo, notepad está abierto" not in feedback.spoken_response.lower()
    assert "no pude confirmar" in feedback.spoken_response.lower()


def test_l_gate_rejected_action_does_not_arrive_as_executed() -> None:
    """L. Acción rechazada por ExecutionGate no llega al verifier como ejecutada."""
    contract = make_test_contract(can_execute=False)
    verifier = PostExecutionVerifier()

    report = verifier.verify(
        intent=contract,
        execution={"is_success": False, "status": "REJECTED"},
    )

    assert report.verification_status == VerificationReportStatus.UNVERIFIED
    assert report.claims_success is False
    assert report.verification_method == "gate_barrier"
    assert "no ejecutada" in report.observed_effect.lower()


def test_m_mock_verifier_positive() -> None:
    """M. Mock verifier positivo integrado."""
    custom_v = MockCustomActionVerifier("Ventana activa detectada", is_ok=True)
    verifier = PostExecutionVerifier()

    contract = make_test_contract(target="notepad")
    report = verifier.verify(intent=contract, execution={"is_success": True}, custom_verifier=custom_v)

    assert report.verification_status == VerificationReportStatus.VERIFIED_SUCCESS
    assert report.claims_success is True
    assert "Ventana activa detectada" in report.observed_effect


def test_n_mock_verifier_negative() -> None:
    """N. Mock verifier negativo integrado."""
    custom_v = MockCustomActionVerifier("Ventana no responde y proceso congelado", is_ok=False)
    verifier = PostExecutionVerifier()

    contract = make_test_contract(target="notepad")
    report = verifier.verify(intent=contract, execution={"is_success": True}, custom_verifier=custom_v)

    assert report.verification_status == VerificationReportStatus.VERIFIED_FAILURE
    assert report.claims_success is False
    assert "congelado" in report.observed_effect


def test_o_mock_verifier_raising_exception() -> None:
    """O. Mock verifier que lanza excepción."""
    exc_v = MockExceptionVerifier(PermissionError("Acceso denegado a PID 4"))
    verifier = PostExecutionVerifier()

    contract = make_test_contract(target="system_tool")
    report = verifier.verify(intent=contract, execution={"is_success": True}, custom_verifier=exc_v)

    assert report.verification_status == VerificationReportStatus.VERIFICATION_ERROR
    assert report.claims_success is False
    assert "Acceso denegado" in str(report.error)


def test_p_anti_false_success_invariants() -> None:
    """P. Invariantes estrictas de Anti-False Success en la inicialización de VerificationReport."""
    # Intentar crear un VERIFIED_FAILURE con claims_success=True debe lanzar ValueError
    with pytest.raises(ValueError, match="Anti-False Success"):
        VerificationReport(
            action_id="act-001",
            skill="windows.apps",
            operation="apps.open",
            expected_effect="App abierta",
            observed_effect="App no encontrada",
            verification_status=VerificationReportStatus.VERIFIED_FAILURE,
            verification_method="process_inspection",
            is_verified=True,
            claims_success=True,  # VIOLACIÓN!
        )

    # Intentar crear un VERIFIED_SUCCESS con is_verified=False debe lanzar ValueError
    with pytest.raises(ValueError, match="exige is_verified=True"):
        VerificationReport(
            action_id="act-002",
            skill="windows.apps",
            operation="apps.open",
            expected_effect="App abierta",
            observed_effect="App abierta",
            verification_status=VerificationReportStatus.VERIFIED_SUCCESS,
            verification_method="process_inspection",
            is_verified=False,  # VIOLACIÓN!
            claims_success=False,
        )


# ── TEST ESPECIAL REQUERIDO POR LA ESPECIFICACIÓN ──


def test_special_open_application_notepad_three_scenarios() -> None:
    """TEST ESPECIAL:

    Fake action: "open_application(notepad)"

    Escenario 1: Skill SUCCESS + Verifier process_exists=True -> VERIFIED_SUCCESS
    Escenario 2: Skill SUCCESS + Verifier process_exists=False -> VERIFIED_FAILURE
    Escenario 3: Skill SUCCESS + Verifier raises Exception -> VERIFICATION_ERROR
    """
    contract = make_test_contract(target="notepad", action_type="open_application")
    verifier = PostExecutionVerifier()

    # Escenario 1:
    v1 = MockBooleanVerifier(process_exists=True)
    rep1 = verifier.verify(intent=contract, execution={"is_success": True}, custom_verifier=v1)
    assert rep1.verification_status == VerificationReportStatus.VERIFIED_SUCCESS
    assert rep1.claims_success is True
    assert rep1.is_verified is True

    # Escenario 2:
    v2 = MockBooleanVerifier(process_exists=False)
    rep2 = verifier.verify(intent=contract, execution={"is_success": True}, custom_verifier=v2)
    assert rep2.verification_status == VerificationReportStatus.VERIFIED_FAILURE
    assert rep2.claims_success is False
    assert rep2.is_verified is True

    # Escenario 3:
    v3 = MockExceptionVerifier(RuntimeError("WMI query failed"))
    rep3 = verifier.verify(intent=contract, execution={"is_success": True}, custom_verifier=v3)
    assert rep3.verification_status == VerificationReportStatus.VERIFICATION_ERROR
    assert rep3.claims_success is False
    assert rep3.is_verified is False


def test_special_close_application_notepad() -> None:
    """Verificación de cierre de aplicación:

    - Si process_exists=False tras close -> VERIFIED_SUCCESS
    - Si process_exists=True tras close -> VERIFIED_FAILURE
    """
    contract = make_test_contract(target="notepad", action_type="close_application", tool_name="apps.close")
    verifier = PostExecutionVerifier()

    # Caso 1: Proceso ya no existe -> Cierre confirmado
    v_closed = MockBooleanVerifier(process_exists=False)
    rep_closed = verifier.verify(intent=contract, execution={"is_success": True}, custom_verifier=v_closed)
    assert rep_closed.verification_status == VerificationReportStatus.VERIFIED_SUCCESS
    assert rep_closed.claims_success is True
    assert "cerrado" in str(rep_closed.feedback_suggestion).lower()

    # Caso 2: Proceso sigue activo -> Cierre fallido
    v_stuck = MockBooleanVerifier(process_exists=True)
    rep_stuck = verifier.verify(intent=contract, execution={"is_success": True}, custom_verifier=v_stuck)
    assert rep_stuck.verification_status == VerificationReportStatus.VERIFIED_FAILURE
    assert rep_stuck.claims_success is False
    assert "no pude confirmar que notepad se haya cerrado" in str(rep_stuck.feedback_suggestion).lower()


def test_attach_to_contract_integration() -> None:
    """Verifica que attach_to_contract incrusta el resultado inmutablemente en ActionIntentContract."""
    contract = make_test_contract(target="notepad")
    verifier = PostExecutionVerifier()

    mock_v = MockBooleanVerifier(process_exists=True)
    report = verifier.verify(intent=contract, execution={"is_success": True}, custom_verifier=mock_v)

    updated_contract = report.attach_to_contract(contract)

    assert updated_contract.execution_report is not None
    assert updated_contract.execution_report.execution_status == "success"
    assert updated_contract.execution_report.claims_success is True
    assert updated_contract.execution_report.is_verified is True
    assert updated_contract.post_action_feedback is not None
    assert "Listo" in updated_contract.post_action_feedback.spoken_response
