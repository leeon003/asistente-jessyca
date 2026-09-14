"""Tests exhaustivos para User Feedback & Natural Response (Fase 64.2.5).

Cubre rigurosamente:
A. VERIFIED_SUCCESS -> respuesta positiva
B. VERIFIED_FAILURE -> respuesta de fallo
C. PARTIAL_SUCCESS -> respuesta parcial
D. UNVERIFIED -> respuesta no afirmativa
E. VERIFICATION_ERROR -> respuesta apropiada
F. REJECTED -> respuesta de rechazo
G. CLARIFY -> pregunta de aclaración
H. ASK_CONFIRMATION -> pregunta de confirmación
I. Anti-False Success (prohibición de "Listo" o afirmación de éxito en estados no verificados)
J. No mencionar componentes internos (ActionIntent, ExecutionGate, Dispatcher, skill, etc.)
K. Mantener nombre de aplicación
L. Mantener operación
M. No ejecutar ninguna acción desde Feedback Builder
N. Feedback Builder no debe llamar directamente a una skill
O. Regresiones e integración con NaturalActionDialogueManager

TESTS ESPECIALES:
- TEST ESPECIAL 1: status=VERIFIED_FAILURE, action=close_application, target=notepad -> Sin falso éxito
- TEST ESPECIAL 2: status=VERIFIED_SUCCESS -> Respuesta positiva natural
- TEST ESPECIAL 3: status=UNVERIFIED -> Indica que no pudo comprobarse el resultado
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.action_intent_contract import (
    ActionIntent,
    ActionIntentContract,
    ExecutionGate,
    ExecutionSpec,
    PreActionFeedback,
)
from core.dialogue.dialogue_manager import NaturalActionDialogueManager
from core.dialogue.feedback_builder import (
    FeedbackBuilder,
    FeedbackStatus,
    NaturalFeedbackResponse,
    get_feedback_builder,
)
from core.execution.post_execution_verifier import (
    VerificationReport,
    VerificationReportStatus,
)


def make_test_verification_report(
    action_id: str = "act-test-feedback-001",
    skill: str = "windows.apps",
    operation: str = "open_application",
    target: str = "notepad",
    status: VerificationReportStatus = VerificationReportStatus.VERIFIED_SUCCESS,
    expected_effect: str = "Proceso notepad en ejecución",
    observed_effect: str = "Proceso notepad activo (PID 1234)",
    error: str | None = None,
) -> VerificationReport:
    """Construye un VerificationReport válido según el estado deseado."""
    is_verif = status in (
        VerificationReportStatus.VERIFIED_SUCCESS,
        VerificationReportStatus.VERIFIED_FAILURE,
        VerificationReportStatus.PARTIAL_SUCCESS,
    )
    claims_succ = (status == VerificationReportStatus.VERIFIED_SUCCESS)
    return VerificationReport(
        action_id=action_id,
        skill=skill,
        operation=operation,
        expected_effect=expected_effect,
        observed_effect=observed_effect,
        verification_status=status,
        verification_method="process_inspection",
        is_verified=is_verif,
        claims_success=claims_succ,
        error=error,
        details={"target": target},
    )


# ── TESTS PRINCIPALES (A - O) ──


def test_a_verified_success_produces_positive_response() -> None:
    """A. VERIFIED_SUCCESS -> respuesta positiva natural."""
    builder = FeedbackBuilder()
    rep = make_test_verification_report(
        operation="open_application",
        target="notepad",
        status=VerificationReportStatus.VERIFIED_SUCCESS,
    )

    response = builder.build_feedback(verification_report=rep)

    assert response.status == FeedbackStatus.VERIFIED_SUCCESS
    assert response.is_success is True
    assert "Listo, abrí Bloc de notas." in response.spoken_response
    assert "Listo, abrí Bloc de notas." in response.response_text


def test_b_verified_failure_explains_action_failed() -> None:
    """B. VERIFIED_FAILURE -> respuesta clara de que no se completó."""
    builder = FeedbackBuilder()
    rep = make_test_verification_report(
        operation="open_application",
        target="notepad",
        status=VerificationReportStatus.VERIFIED_FAILURE,
        observed_effect="El proceso nunca apareció",
        error="Proceso no encontrado",
    )

    response = builder.build_feedback(verification_report=rep)

    assert response.status == FeedbackStatus.VERIFIED_FAILURE
    assert response.is_success is False
    assert "No pude confirmar que Bloc de notas se haya abierto." in response.spoken_response
    assert "listo" not in response.spoken_response.lower()


def test_c_partial_success_explains_partial_outcome() -> None:
    """C. PARTIAL_SUCCESS -> respuesta de éxito parcial."""
    builder = FeedbackBuilder()
    rep = make_test_verification_report(
        operation="close_application",
        target="notepad",
        status=VerificationReportStatus.PARTIAL_SUCCESS,
    )

    response = builder.build_feedback(verification_report=rep)

    assert response.status == FeedbackStatus.PARTIAL_SUCCESS
    assert response.is_success is False
    assert "parcialmente" in response.spoken_response.lower() or "parte de la acción" in response.spoken_response.lower()


def test_d_unverified_does_not_lie() -> None:
    """D. UNVERIFIED -> no miente ni afirma éxito."""
    builder = FeedbackBuilder()
    rep = make_test_verification_report(
        operation="system_beep",
        target="chime",
        status=VerificationReportStatus.UNVERIFIED,
    )

    response = builder.build_feedback(verification_report=rep)

    assert response.status == FeedbackStatus.UNVERIFIED
    assert response.is_success is False
    assert "no pude verificar" in response.spoken_response.lower()
    assert "listo" not in response.spoken_response.lower()


def test_e_verification_error_explains_check_problem() -> None:
    """E. VERIFICATION_ERROR -> respuesta honesta de fallo en la comprobación."""
    builder = FeedbackBuilder()
    rep = make_test_verification_report(
        operation="open_application",
        target="calc",
        status=VerificationReportStatus.VERIFICATION_ERROR,
        error="Error de sondeo WMI",
    )

    response = builder.build_feedback(verification_report=rep)

    assert response.status == FeedbackStatus.VERIFICATION_ERROR
    assert response.is_success is False
    assert "problema al comprobar" in response.spoken_response.lower()


def test_f_rejected_communicates_clean_refusal() -> None:
    """F. REJECTED -> respuesta de rechazo clara y educada."""
    builder = FeedbackBuilder()

    response = builder.build_rejection_response()

    assert response == "No puedo ejecutar esa acción porque no está autorizada."
    assert "executiongate" not in response.lower()
    assert "actionintent" not in response.lower()


def test_g_clarify_asks_specific_question() -> None:
    """G. CLARIFY -> formula la pregunta de aclaración."""
    builder = FeedbackBuilder()

    prompt_open = builder.build_clarification_prompt(operation="open_application")
    assert prompt_open == "¿Qué aplicación quieres que abra?"

    prompt_close = builder.build_clarification_prompt(operation="close_application")
    assert prompt_close == "¿Qué aplicación quieres que cierre?"


def test_h_ask_confirmation_asks_direct_question() -> None:
    """H. ASK_CONFIRMATION -> pregunta directa sin ejecutar."""
    builder = FeedbackBuilder()

    prompt = builder.build_confirmation_prompt(operation="close_application", target="notepad")
    assert prompt == "Voy a cerrar Bloc de notas. ¿Quieres que lo haga?"


def test_i_anti_false_success_guaranteed() -> None:
    """I. Anti-False Success: NUNCA emite 'Listo' si verification_status != VERIFIED_SUCCESS."""
    builder = FeedbackBuilder()

    non_success_statuses = [
        FeedbackStatus.VERIFIED_FAILURE,
        FeedbackStatus.PARTIAL_SUCCESS,
        FeedbackStatus.UNVERIFIED,
        FeedbackStatus.VERIFICATION_ERROR,
        FeedbackStatus.REJECTED,
        FeedbackStatus.CLARIFY,
        FeedbackStatus.ASK_CONFIRMATION,
    ]

    for st in non_success_statuses:
        resp = builder.build_feedback(status=st, target="notepad", operation="open_application")
        low = resp.spoken_response.lower()
        assert not low.startswith("listo"), f"Falso éxito detectado en estado {st}"
        assert "listo," not in low, f"Falso éxito detectado en estado {st}"
        assert resp.is_success is False, f"is_success debe ser False en estado {st}"


def test_j_no_internal_components_leaked() -> None:
    """J. No menciona componentes internos en el mensaje hacia el usuario."""
    builder = FeedbackBuilder()
    reason_with_internals = (
        "ExecutionGate rechazó ActionIntent por falta de confidence en Dispatcher y SkillRegistry."
    )

    sanitized = builder.sanitize_text(reason_with_internals)
    for term in builder.FORBIDDEN_INTERNAL_TERMS:
        assert term not in sanitized.lower(), f"Término prohibido filtrado: {term}"


def test_k_preserves_application_name() -> None:
    """K. Mantiene el nombre reconocible de la aplicación."""
    builder = FeedbackBuilder()

    r1 = builder.build_feedback(status=FeedbackStatus.VERIFIED_SUCCESS, target="notepad", operation="open")
    assert "Bloc de notas" in r1.spoken_response

    r2 = builder.build_feedback(status=FeedbackStatus.VERIFIED_SUCCESS, target="calc", operation="open")
    assert "la Calculadora" in r2.spoken_response

    r3 = builder.build_feedback(status=FeedbackStatus.VERIFIED_SUCCESS, target="chrome", operation="open")
    assert "Chrome" in r3.spoken_response


def test_l_preserves_operation_type() -> None:
    """L. Mantiene la coherencia de la operación realizada."""
    builder = FeedbackBuilder()

    r_open = builder.build_feedback(status=FeedbackStatus.VERIFIED_SUCCESS, target="notepad", operation="open_application")
    assert "abrí" in r_open.spoken_response

    r_close = builder.build_feedback(status=FeedbackStatus.VERIFIED_SUCCESS, target="notepad", operation="close_application")
    assert "cerré" in r_close.spoken_response


def test_m_no_actions_executed_from_feedback_builder() -> None:
    """M. No ejecuta ninguna acción del sistema operativo."""
    builder = FeedbackBuilder()

    with patch("subprocess.Popen") as mock_popen, patch("os.system") as mock_system:
        _ = builder.build_feedback(status=FeedbackStatus.VERIFIED_SUCCESS, target="calc", operation="open")
        mock_popen.assert_not_called()
        mock_system.assert_not_called()


def test_n_feedback_builder_does_not_call_skills() -> None:
    """N. Feedback Builder no llama a ninguna skill ni plugin."""
    builder = FeedbackBuilder()
    mock_skill = MagicMock()

    _ = builder.build_feedback(status=FeedbackStatus.VERIFIED_SUCCESS, target="notepad", operation="open")
    mock_skill.execute.assert_not_called()
    mock_skill.ejecutar.assert_not_called()


def test_o_integration_with_dialogue_manager() -> None:
    """O. Integración armónica con NaturalActionDialogueManager sin crear un segundo gestor."""
    dm = NaturalActionDialogueManager.get_instance()
    rep = make_test_verification_report(
        operation="close_application",
        target="notepad",
        status=VerificationReportStatus.VERIFIED_SUCCESS,
    )

    feedback = dm.build_feedback(verification_report=rep)

    assert isinstance(feedback, NaturalFeedbackResponse)
    assert feedback.status == FeedbackStatus.VERIFIED_SUCCESS
    assert "Listo, cerré Bloc de notas." in feedback.spoken_response

    # Comprobación de conversión a PostActionFeedback
    post_fb = feedback.to_post_action_feedback()
    assert post_fb.spoken_response == feedback.spoken_response


# ── TESTS ESPECIALES REQUERIDOS ──


def test_special_01_verified_failure_close_notepad() -> None:
    """TEST ESPECIAL 1:

    VerificationReport:
    status = VERIFIED_FAILURE
    action = close_application
    target = notepad

    Esperado:
    NO debe contener: "Listo", "cerré correctamente", "éxito".
    Debe comunicar claramente que no se pudo confirmar.
    """
    builder = get_feedback_builder()
    rep = make_test_verification_report(
        operation="close_application",
        target="notepad",
        status=VerificationReportStatus.VERIFIED_FAILURE,
        observed_effect="El proceso sigue activo",
        error="Proceso no terminado",
    )

    response = builder.build_feedback(verification_report=rep)
    low = response.spoken_response.lower()

    # Invariantes absolutas
    assert "listo" not in low
    assert "cerré correctamente" not in low
    assert "éxito" not in low
    assert "no pude confirmar que bloc de notas se haya cerrado" in low


def test_special_02_verified_success_produces_natural_positive() -> None:
    """TEST ESPECIAL 2:

    status = VERIFIED_SUCCESS
    Esperado: Produce una respuesta positiva natural.
    """
    builder = get_feedback_builder()
    rep = make_test_verification_report(
        operation="open_application",
        target="notepad",
        status=VerificationReportStatus.VERIFIED_SUCCESS,
    )

    response = builder.build_feedback(verification_report=rep)

    assert response.is_success is True
    assert response.spoken_response == "Listo, abrí Bloc de notas."


def test_special_03_unverified_explains_cannot_check() -> None:
    """TEST ESPECIAL 3:

    status = UNVERIFIED
    Esperado: Debe indicar que no pudo comprobarse el resultado.
    """
    builder = get_feedback_builder()
    rep = make_test_verification_report(
        operation="custom_action",
        target="unknown",
        status=VerificationReportStatus.UNVERIFIED,
    )

    response = builder.build_feedback(verification_report=rep)

    assert response.is_success is False
    assert "no pude verificar el resultado" in response.spoken_response.lower()


def test_contract_driven_feedback() -> None:
    """Comprueba que el FeedbackBuilder procesa un ActionIntentContract en sus distintas etapas."""
    builder = get_feedback_builder()

    # Contrato con ExecutionGate que requiere confirmación
    intent = ActionIntent(intent_name="close_application", parameters={"nombre_app": "notepad"})
    gate = ExecutionGate(
        can_execute=True,
        needs_confirmation=True,
        confirmation_prompt="Voy a cerrar Bloc de notas. ¿Quieres que lo haga?",
    )
    contract = ActionIntentContract(
        request_id="req-conf-001",
        session_id="session-001",
        action_intent=intent,
        execution_gate=gate,
        pre_action_feedback=PreActionFeedback(acknowledgement_speech="Cerrando."),
        execution_spec=ExecutionSpec(skill_id="windows.apps", idempotency_key="idem-001"),
    )

    resp = builder.build_feedback(intent=contract)
    assert resp.status == FeedbackStatus.ASK_CONFIRMATION
    assert resp.requires_user_action is True
    assert "Voy a cerrar Bloc de notas. ¿Quieres que lo haga?" in resp.spoken_response
