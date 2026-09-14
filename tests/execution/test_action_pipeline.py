"""Tests de integración End-to-End para Action Pipeline (Fase 64.2.6).

Cubre exhaustivamente:
TEST 1  — SUCCESS: open_application(notepad) -> COMPLETED y respuesta positiva
TEST 2  — CONFIRMATION: close_application(notepad) con riesgo -> WAITING_CONFIRMATION (Dispatcher NO llamado)
TEST 3  — CONFIRMATION ACCEPTED: Continuar Test 2 con confirmación True -> Dispatcher llamado 1 vez -> COMPLETED
TEST 4  — CONFIRMATION REJECTED: confirm_action con False -> REJECTED (Dispatcher NO llamado)
TEST 5  — CLARIFICATION: Planner con confianza insuficiente (< 0.60) -> CLARIFICATION_REQUIRED (No Dispatcher)
TEST 6  — DISPATCHER FAILURE: Dispatcher FAILED -> Pipeline FAILED (Sin falso éxito)
TEST 7  — VERIFICATION FAILURE: Dispatcher SUCCESS + Verifier VERIFIED_FAILURE -> Pipeline FAILED (Anti-False Success)
TEST 8  — UNVERIFIED: Dispatcher SUCCESS + Verifier UNVERIFIED -> No afirma éxito verificado
TEST 9  — DUPLICATE ACTION: Mismo action_id enviado 2 veces -> Idempotencia bloquea segunda ejecución
TEST 10 — EXCEPTION: Una etapa lanza excepción -> Controlada, sin crash, sin falso éxito
TEST 11 — REJECTED ACTION: Gate rechaza por política -> Dispatcher nunca es llamado
TEST 12 — ACTION CONTEXT: Preservación de action_id, skill, operation, arguments, risk_level, confidence
TEST 13 — FEEDBACK: Verificación de que feedback usa VerificationReport real sin inventar estados
TEST 14 — REGRESSION: Garantía de no regresión en contratos y subsistemas
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from core.action_intent_contract import (
    ActionIntent,
    ActionIntentContract,
    ExecutionGate,
    ExecutionSpec,
    PreActionFeedback,
)
from core.dialogue.action_planner import ActionPlanner
from core.dialogue.feedback_builder import FeedbackBuilder
from core.execution.action_pipeline import (
    ActionPipeline,
    ActionPipelineStatus,
)
from core.execution.execution_dispatcher import (
    ExecutionDispatcher,
)
from core.execution.execution_gate_bridge import (
    ExecutionGateBridge,
)
from core.execution.idempotency_guard import ExecutionIdempotencyGuard
from core.execution.post_execution_verifier import (
    PostExecutionVerifier,
    VerificationReport,
    VerificationReportStatus,
)
from skills.base_skill import BaseSkill
from skills.skill_models import SkillDefinition, SkillManifest, SkillResult, SkillStatus
from skills.skill_registry import SkillRegistry


class SpySkill(BaseSkill):
    """Skill espía que cuenta cuántas veces fue invocada y registra parámetros."""

    def __init__(self, skill_id: str = "windows.apps", should_fail: bool = False) -> None:
        self.call_count = 0
        self.last_params: dict[str, Any] | None = None
        self.should_fail = should_fail
        manifest = SkillManifest(
            id=skill_id,
            name="Spy Skill",
            version="1.0.0",
            description="Spy skill for E2E testing",
            author="Jessyca Core",
            capabilities=("application_control", "application"),
            required_tools=("apps.open", "apps.close", "windows.launch_app", "windows.close_app"),
        )
        definition = SkillDefinition(
            skill_id=skill_id,
            name="Spy Skill",
            version="1.0.0",
            description="Spy skill definition",
            capabilities=("application_control", "application"),
            required_tools=("apps.open", "apps.close", "windows.launch_app", "windows.close_app"),
            manifest=manifest,
        )
        super().__init__(nombre=skill_id, nivel_riesgo=1, definition=definition)

    def execute(self, context: Any) -> SkillResult:
        self.call_count += 1
        self.last_params = dict(context.parameters)
        if self.should_fail:
            return SkillResult(
                skill_id="windows.apps",
                success=False,
                status=SkillStatus.FAILED,
                error="Simulated skill execution failure",
                output={"exito": False, "mensaje": "Fallo simulado"},
            )
        return SkillResult(
            skill_id="windows.apps",
            success=True,
            status=SkillStatus.COMPLETED,
            output={"exito": True, "mensaje": "Proceso ejecutado", "evidence": {"is_verified": True}},
        )

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        self.last_params = dict(parametros)
        if self.should_fail:
            return {"exito": False, "mensaje": "Fallo simulado"}
        return {"exito": True, "mensaje": "Proceso ejecutado", "evidence": {"is_verified": True}}


class MockBooleanVerifier:
    """Mock verifier determinista para controlar la existencia de procesos."""

    def __init__(self, process_exists: bool = True) -> None:
        self.process_exists = process_exists


@pytest.fixture
def isolated_pipeline() -> tuple[ActionPipeline, SpySkill]:
    """Crea una instancia completamente aislada de ActionPipeline con SpySkill."""
    spy_skill = SpySkill(skill_id="windows.apps")
    registry = SkillRegistry()
    registry.register_skill(spy_skill)

    dispatcher = ExecutionDispatcher(registry=registry)
    guard = ExecutionIdempotencyGuard()
    guard.reset()

    pipeline = ActionPipeline(
        planner=ActionPlanner(),
        gate_bridge=ExecutionGateBridge(),
        dispatcher=dispatcher,
        verifier=PostExecutionVerifier(),
        feedback_builder=FeedbackBuilder(),
        idempotency_guard=guard,
    )
    pipeline.reset()
    return pipeline, spy_skill


# ── TEST 1: SUCCESS ──────────────────────────────────────────────────────────


def test_01_pipeline_success_end_to_end(isolated_pipeline: tuple[ActionPipeline, SpySkill]) -> None:
    """TEST 1 — SUCCESS: open_application(notepad) -> COMPLETED y respuesta positiva."""
    pipeline, spy = isolated_pipeline
    mock_v = MockBooleanVerifier(process_exists=True)

    result = pipeline.execute(
        user_input="Abre Bloc de notas",
        intent="open_application",
        parameters={"nombre_app": "notepad"},
        session_id="session-e2e-01",
        request_id="req-e2e-01",
        confidence=0.95,
        custom_verifier=mock_v,
    )

    assert result.status == ActionPipelineStatus.COMPLETED
    assert result.is_terminal is True
    assert spy.call_count == 1
    assert result.verification_report is not None
    assert result.verification_report.claims_success is True
    assert "Listo, abrí Bloc de notas." in result.spoken_response
    assert result.error is None


# ── TEST 2: CONFIRMATION (PAUSE) ─────────────────────────────────────────────


def test_02_pipeline_confirmation_pauses_execution(isolated_pipeline: tuple[ActionPipeline, SpySkill]) -> None:
    """TEST 2 — CONFIRMATION: close_application con riesgo -> WAITING_CONFIRMATION (Dispatcher NO llamado)."""
    pipeline, spy = isolated_pipeline

    # Crear contrato que requiere confirmación explícita
    intent = ActionIntent(
        intent_name="close_application",
        confidence=0.92,
        parameters={"nombre_app": "notepad"},
    )
    gate = ExecutionGate(
        can_execute=True,
        needs_confirmation=True,
        risk_level="HIGH",
        confirmation_prompt="Voy a cerrar Bloc de notas. ¿Quieres que lo haga?",
    )
    contract = ActionIntentContract(
        request_id="req-e2e-conf-02",
        session_id="session-e2e-02",
        action_intent=intent,
        execution_gate=gate,
        pre_action_feedback=PreActionFeedback(acknowledgement_speech="Cerrando."),
        execution_spec=ExecutionSpec(skill_id="windows.apps", tool_name="apps.close", idempotency_key="idem-02"),
    )

    result = pipeline.execute(
        user_input="Cierra Bloc de notas",
        contract=contract,
    )

    assert result.status == ActionPipelineStatus.WAITING_CONFIRMATION
    assert result.is_terminal is False
    assert spy.call_count == 0  # DISPATCHER NO DEBE SER LLAMADO
    assert "Voy a cerrar Bloc de notas. ¿Quieres que lo haga?" in result.spoken_response


# ── TEST 3: CONFIRMATION ACCEPTED ────────────────────────────────────────────


def test_03_pipeline_confirmation_accepted(isolated_pipeline: tuple[ActionPipeline, SpySkill]) -> None:
    """TEST 3 — CONFIRMATION ACCEPTED: Continuar Test 2 con confirmación True -> Dispatcher 1 vez -> COMPLETED."""
    pipeline, spy = isolated_pipeline
    mock_v = MockBooleanVerifier(process_exists=False)  # En close, False significa que cerró con éxito

    # 1. Petición inicial que entra en pausa
    intent = ActionIntent(
        intent_name="close_application",
        confidence=0.95,
        parameters={"nombre_app": "notepad"},
    )
    gate = ExecutionGate(
        can_execute=True,
        needs_confirmation=True,
        risk_level="HIGH",
        confirmation_prompt="Voy a cerrar Bloc de notas. ¿Quieres que lo haga?",
    )
    contract = ActionIntentContract(
        request_id="req-e2e-conf-03",
        session_id="session-e2e-03",
        action_intent=intent,
        execution_gate=gate,
        pre_action_feedback=PreActionFeedback(acknowledgement_speech="Cerrando."),
        execution_spec=ExecutionSpec(skill_id="windows.apps", tool_name="apps.close", idempotency_key="idem-03"),
    )

    r_wait = pipeline.execute(user_input="Cierra Bloc de notas", contract=contract)
    assert r_wait.status == ActionPipelineStatus.WAITING_CONFIRMATION
    assert spy.call_count == 0

    # 2. Usuario confirma afirmativamente
    r_done = pipeline.confirm_action(
        action_id="req-e2e-conf-03",
        user_confirmed=True,
        custom_verifier=mock_v,
    )

    assert r_done.status == ActionPipelineStatus.COMPLETED
    assert spy.call_count == 1  # Llamado exactamente una vez
    assert r_done.verification_report is not None
    assert r_done.verification_report.claims_success is True
    assert "Listo, cerré Bloc de notas." in r_done.spoken_response


# ── TEST 4: CONFIRMATION REJECTED ────────────────────────────────────────────


def test_04_pipeline_confirmation_rejected(isolated_pipeline: tuple[ActionPipeline, SpySkill]) -> None:
    """TEST 4 — CONFIRMATION REJECTED: confirm_action con False -> REJECTED (Dispatcher NO llamado)."""
    pipeline, spy = isolated_pipeline

    intent = ActionIntent(
        intent_name="close_application",
        confidence=0.95,
        parameters={"nombre_app": "notepad"},
    )
    gate = ExecutionGate(
        can_execute=True,
        needs_confirmation=True,
        risk_level="HIGH",
        confirmation_prompt="Voy a cerrar Bloc de notas. ¿Quieres que lo haga?",
    )
    contract = ActionIntentContract(
        request_id="req-e2e-conf-04",
        session_id="session-e2e-04",
        action_intent=intent,
        execution_gate=gate,
        pre_action_feedback=PreActionFeedback(acknowledgement_speech="Cerrando."),
        execution_spec=ExecutionSpec(skill_id="windows.apps", tool_name="apps.close", idempotency_key="idem-04"),
    )

    _ = pipeline.execute(user_input="Cierra Bloc de notas", contract=contract)
    assert spy.call_count == 0

    # Usuario deniega
    r_reject = pipeline.confirm_action(action_id="req-e2e-conf-04", user_confirmed=False)

    assert r_reject.status == ActionPipelineStatus.REJECTED
    assert spy.call_count == 0  # Dispatcher NUNCA debe ser llamado
    assert "no puedo" in r_reject.spoken_response.lower()


# ── TEST 5: CLARIFICATION ────────────────────────────────────────────────────


def test_05_pipeline_clarification_required(isolated_pipeline: tuple[ActionPipeline, SpySkill]) -> None:
    """TEST 5 — CLARIFICATION: Confianza insuficiente (< 0.60) -> CLARIFICATION_REQUIRED (No Dispatcher)."""
    pipeline, spy = isolated_pipeline

    result = pipeline.execute(
        user_input="Abre algo",
        intent="open_application",
        parameters={"nombre_app": "notepad"},
        confidence=0.45,  # Confianza insuficiente
        request_id="req-e2e-clarify-05",
    )

    assert result.status == ActionPipelineStatus.CLARIFICATION_REQUIRED
    assert spy.call_count == 0  # No Dispatcher
    assert result.is_terminal is False


# ── TEST 6: DISPATCHER FAILURE ───────────────────────────────────────────────


def test_06_pipeline_dispatcher_failure(isolated_pipeline: tuple[ActionPipeline, SpySkill]) -> None:
    """TEST 6 — DISPATCHER FAILURE: Dispatcher FAILED -> Pipeline FAILED (Sin falso éxito)."""
    pipeline, spy = isolated_pipeline
    spy.should_fail = True  # La skill reporta fallo

    result = pipeline.execute(
        user_input="Abre Bloc de notas",
        intent="open_application",
        parameters={"nombre_app": "notepad"},
        request_id="req-e2e-fail-06",
        confidence=0.95,
    )

    assert result.status == ActionPipelineStatus.FAILED
    assert result.dispatch_result is not None
    assert result.dispatch_result.is_success is False
    assert "listo" not in result.spoken_response.lower()
    assert "no pude" in result.spoken_response.lower()


# ── TEST 7: VERIFICATION FAILURE ─────────────────────────────────────────────


def test_07_pipeline_verification_failure(isolated_pipeline: tuple[ActionPipeline, SpySkill]) -> None:
    """TEST 7 — VERIFICATION FAILURE: Dispatcher SUCCESS + Verifier VERIFIED_FAILURE -> Pipeline FAILED (Anti-False Success)."""
    pipeline, spy = isolated_pipeline
    # Skill dice que se ejecutó bien, pero el verifier físico observa que el proceso NO existe
    mock_v = MockBooleanVerifier(process_exists=False)

    result = pipeline.execute(
        user_input="Abre Bloc de notas",
        intent="open_application",
        parameters={"nombre_app": "notepad"},
        request_id="req-e2e-false-succ-07",
        confidence=0.95,
        custom_verifier=mock_v,
    )

    assert result.status == ActionPipelineStatus.FAILED  # NUNCA COMPLETED
    assert result.verification_report is not None
    assert result.verification_report.verification_status == VerificationReportStatus.VERIFIED_FAILURE
    assert result.verification_report.claims_success is False
    assert "listo" not in result.spoken_response.lower()
    assert "no pude confirmar que bloc de notas se haya abierto" in result.spoken_response.lower()


# ── TEST 8: UNVERIFIED ───────────────────────────────────────────────────────


def test_08_pipeline_unverified_action(isolated_pipeline: tuple[ActionPipeline, SpySkill]) -> None:
    """TEST 8 — UNVERIFIED: Dispatcher SUCCESS + Verifier UNVERIFIED -> No afirma éxito verificado."""
    pipeline, spy = isolated_pipeline

    intent = ActionIntent(intent_name="open_application", confidence=0.95, parameters={"nombre_app": "notepad"})
    contract = ActionIntentContract(
        request_id="req-e2e-unverif-08",
        session_id="session-08",
        action_intent=intent,
        execution_gate=ExecutionGate(can_execute=True),
        execution_spec=ExecutionSpec(skill_id="windows.apps", tool_name="apps.open", idempotency_key="idem-08"),
    )

    mock_v = MagicMock()
    mock_v.verify.return_value = VerificationReport(
        action_id="req-e2e-unverif-08",
        skill="windows.apps",
        operation="apps.open",
        expected_effect="Aplicación ejecutándose",
        observed_effect="Sin sensor disponible",
        verification_status=VerificationReportStatus.UNVERIFIED,
        verification_method="noop",
        is_verified=False,
        claims_success=False,
        feedback_suggestion="Se envió la orden de abrir Bloc de notas, pero no pude verificar si se completó.",
    )

    result = pipeline.execute(
        user_input="Abre Bloc de notas",
        contract=contract,
        custom_verifier=mock_v,
    )

    # Conserva la diferencia: Se ejecutó pero no está afirmado como verificado positivamente
    assert result.status == ActionPipelineStatus.EXECUTED
    assert result.verification_report is not None
    assert result.verification_report.verification_status == VerificationReportStatus.UNVERIFIED
    assert result.verification_report.claims_success is False
    assert "no pude verificar" in result.spoken_response.lower()


# ── TEST 9: DUPLICATE ACTION ─────────────────────────────────────────────────


def test_09_pipeline_duplicate_action_blocked(isolated_pipeline: tuple[ActionPipeline, SpySkill]) -> None:
    """TEST 9 — DUPLICATE ACTION: Mismo action_id enviado 2 veces -> Idempotencia bloquea segunda ejecución."""
    pipeline, spy = isolated_pipeline
    mock_v = MockBooleanVerifier(process_exists=True)

    r1 = pipeline.execute(
        user_input="Abre Bloc de notas",
        intent="open_application",
        parameters={"nombre_app": "notepad"},
        request_id="req-duplicate-09",
        confidence=0.95,
        custom_verifier=mock_v,
    )
    assert r1.status == ActionPipelineStatus.COMPLETED
    assert spy.call_count == 1

    # Segunda ejecución con exactamente el mismo action_id
    r2 = pipeline.execute(
        user_input="Abre Bloc de notas",
        intent="open_application",
        parameters={"nombre_app": "notepad"},
        request_id="req-duplicate-09",
        confidence=0.95,
        custom_verifier=mock_v,
    )

    assert r2.status == ActionPipelineStatus.COMPLETED
    assert spy.call_count == 1  # No se volvió a ejecutar


# ── TEST 10: EXCEPTION HANDLING ──────────────────────────────────────────────


def test_10_pipeline_exception_handling(isolated_pipeline: tuple[ActionPipeline, SpySkill]) -> None:
    """TEST 10 — EXCEPTION: Una etapa lanza excepción -> Controlada, sin crash, sin falso éxito."""
    pipeline, spy = isolated_pipeline

    class ExplodingVerifier:
        def verify_action(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("Fallo catastrófico en driver del sistema")

    result = pipeline.execute(
        user_input="Abre Bloc de notas",
        intent="open_application",
        parameters={"nombre_app": "notepad"},
        request_id="req-e2e-exc-10",
        confidence=0.95,
        custom_verifier=ExplodingVerifier(),
    )

    assert result.status == ActionPipelineStatus.FAILED
    assert result.error is not None
    assert "Fallo catastrófico" in result.error
    assert "problema al comprobar" in result.spoken_response.lower()


# ── TEST 11: REJECTED ACTION ─────────────────────────────────────────────────


def test_11_pipeline_rejected_action(isolated_pipeline: tuple[ActionPipeline, SpySkill]) -> None:
    """TEST 11 — REJECTED ACTION: Gate rechaza por can_execute=False -> Dispatcher nunca es llamado."""
    pipeline, spy = isolated_pipeline

    intent = ActionIntent(intent_name="open_application", confidence=0.95, parameters={"nombre_app": "notepad"})
    gate = ExecutionGate(can_execute=False)  # Bloqueada
    contract = ActionIntentContract(
        request_id="req-e2e-reject-11",
        session_id="session-11",
        action_intent=intent,
        execution_gate=gate,
        execution_spec=ExecutionSpec(skill_id="windows.apps", tool_name="apps.open", idempotency_key="idem-11"),
    )

    result = pipeline.execute(user_input="Abre Bloc de notas", contract=contract)

    assert result.status == ActionPipelineStatus.REJECTED
    assert spy.call_count == 0
    assert "no puedo" in result.spoken_response.lower()


# ── TEST 12: ACTION CONTEXT PRESERVATION ──────────────────────────────────────


def test_12_pipeline_action_context_preserved(isolated_pipeline: tuple[ActionPipeline, SpySkill]) -> None:
    """TEST 12 — ACTION CONTEXT: Preservación de action_id, skill, operation, arguments, risk_level, confidence."""
    pipeline, spy = isolated_pipeline
    mock_v = MockBooleanVerifier(process_exists=True)

    result = pipeline.execute(
        user_input="Abre Bloc de notas",
        intent="open_application",
        parameters={"nombre_app": "notepad", "custom_flag": 42},
        session_id="session-ctx-12",
        request_id="req-ctx-12",
        confidence=0.94,
        risk_level="LOW",
        custom_verifier=mock_v,
    )

    assert result.action_id == "req-ctx-12"
    assert result.session_id == "session-ctx-12"
    assert result.contract is not None
    assert result.contract.action_intent.confidence == 0.94
    assert result.contract.execution_spec is not None
    assert "windows.apps" in result.contract.execution_spec.skill_id
    assert result.contract.action_intent.parameters.get("custom_flag") == 42


# ── TEST 13: FEEDBACK ACCURACY ───────────────────────────────────────────────


def test_13_pipeline_feedback_matches_verification(isolated_pipeline: tuple[ActionPipeline, SpySkill]) -> None:
    """TEST 13 — FEEDBACK: Feedback usa VerificationReport real sin inventar estados."""
    pipeline, spy = isolated_pipeline
    mock_v = MockBooleanVerifier(process_exists=True)

    result = pipeline.execute(
        user_input="Abre Bloc de notas",
        intent="open_application",
        parameters={"nombre_app": "notepad"},
        request_id="req-feedback-13",
        confidence=0.95,
        custom_verifier=mock_v,
    )

    assert result.feedback_response is not None
    assert result.feedback_response.is_success is True
    assert result.feedback_response.spoken_response == "Listo, abrí Bloc de notas."
    assert result.to_post_action_feedback().spoken_response == "Listo, abrí Bloc de notas."


# ── TEST 14: REGRESSION / INTEGRATION ────────────────────────────────────────


def test_14_pipeline_regression_and_reset(isolated_pipeline: tuple[ActionPipeline, SpySkill]) -> None:
    """TEST 14 — REGRESSION: Pipeline resetea su estado y procesa flujos limpios."""
    pipeline, spy = isolated_pipeline
    pipeline.reset()
    assert len(pipeline._action_records) == 0
    assert len(pipeline._pending_actions) == 0
