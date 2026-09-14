"""Tests unitarios para Execution Dispatcher (Fase 64.2.3).

Cubre exhaustivamente:
A. Acción autorizada -> skill correcta
B. Skill inexistente -> NOT_FOUND
C. Operación inexistente / no especificada -> NOT_FOUND
D. Argumentos inválidos -> INVALID_ARGUMENTS
E. Skill lanza excepción -> EXCEPTION
F. Skill devuelve fracaso -> FAILED
G. Skill devuelve éxito real -> SUCCESS
H. Acción sin autorización -> REJECTED
I. ExecutionGate bloqueado -> REJECTED
J. Confirmation requerida pero no confirmada -> REJECTED
K. Verificar que una acción rechazada NO llama a la skill
L. Verificar que el Dispatcher ejecuta solamente una operación
M. Verificar que action_id se conserva durante todo el proceso
N. Verificar que skill y operation se conservan
O. Verificar Anti-False Success
P. Verificar que una excepción no rompe el proceso global
Q. Compatibilidad con skills de producción (windows.apps, windows.screenshot)
TEST DOBLE: Fake/Mock skill para verificar invocación en autorizada y NO invocación en rechazada.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.action_intent_contract import (
    ActionIntent,
    ActionIntentContract,
    ExecutionGate,
    ExecutionSpec,
    PreActionFeedback,
)
from core.execution.execution_dispatcher import (
    DispatchResult,
    DispatchStatus,
    ExecutionDispatcher,
)
from core.execution.execution_gate_bridge import (
    ExecutionDecision,
    GateDecisionType,
)
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillContext,
    SkillDefinition,
    SkillManifest,
    SkillResult,
    SkillStatus,
)
from skills.skill_registry import SkillRegistry


class SpyMockSkill(BaseSkill):
    """Fake/Mock skill que registra meticulosamente sus invocaciones."""

    def __init__(
        self,
        skill_id: str = "test.mock_skill",
        should_fail: bool = False,
        should_raise: bool = False,
        return_evidence: bool = True,
    ) -> None:
        self.invocation_count = 0
        self.last_parameters: dict[str, Any] | None = None
        self.should_fail = should_fail
        self.should_raise = should_raise
        self.return_evidence = return_evidence

        manifest = SkillManifest(
            id=skill_id,
            name="Spy Mock Skill",
            version="1.0.0",
            description="Skill para test de despacho",
            capabilities=("application", "desktop"),
            required_tools=("mock_action",),
        )
        def_obj = SkillDefinition(
            skill_id=skill_id,
            name="Spy Mock Skill",
            version="1.0.0",
            capabilities=("application", "desktop"),
            required_tools=("mock_action",),
            manifest=manifest,
        )
        super().__init__(nombre=skill_id, nivel_riesgo=1, definition=def_obj)



    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        self.invocation_count += 1
        self.last_parameters = dict(parametros)

        if self.should_raise:
            raise RuntimeError("Fallo simulado e intencional en la skill")

        if self.should_fail:
            return {
                "exito": False,
                "mensaje": "Error simulado en la operación de la skill.",
            }

        evidence = None
        if self.return_evidence:
            evidence = {
                "verification_type": "mock_verify",
                "target": str(parametros.get("target", "mock_target")),
                "is_verified": True,
                "details": {"mock": True},
            }

        return {
            "exito": True,
            "mensaje": "Operación simulada completada exitosamente.",
            "evidence": evidence,
        }

    def execute(self, context: SkillContext) -> SkillResult:
        res_dict = self.ejecutar(context.parameters)
        success = bool(res_dict.get("exito", False))
        return SkillResult(
            skill_id=self.skill_id,
            success=success,
            status=SkillStatus.COMPLETED if success else SkillStatus.FAILED,
            output=res_dict,
            error=None if success else res_dict.get("mensaje"),
            execution_id=context.execution_id,
        )


@pytest.fixture
def isolated_registry() -> SkillRegistry:
    """Registro aislado para pruebas sin interferencia con singletons globales."""
    reg = SkillRegistry()
    return reg


@pytest.fixture
def authorized_decision() -> ExecutionDecision:
    """Decisión de ejecución formalmente AUTORIZADA."""
    intent = ActionIntent(
        intent_name="mock_action",
        confidence=0.95,
        target="item-42",
        parameters={"target": "item-42"},
    )
    gate = ExecutionGate(
        can_execute=True,
        needs_clarification=False,
        needs_confirmation=False,
        risk_level="SAFE",
    )
    spec = ExecutionSpec(
        skill_id="test.mock_skill",
        tool_name="mock_action",
        idempotency_key="idemp-mock-1",
    )
    contract = ActionIntentContract(
        request_id="req-auth-001",
        session_id="sess-auth-001",
        action_intent=intent,
        execution_gate=gate,
        pre_action_feedback=PreActionFeedback(acknowledgement_speech="Ejecutando"),
        execution_spec=spec,
    )
    return ExecutionDecision(
        decision_type=GateDecisionType.EXECUTE,
        contract=contract,
        reason="Acción autorizada para ejecución directa.",
        action_intent=intent,
        execution_gate=gate,
        execution_spec=spec,
        risk_level="SAFE",
        confidence=0.95,
        skill_id="test.mock_skill",
        operation="mock_action",
        parameters={"target": "item-42"},
    )


@pytest.fixture
def unauthorized_decision() -> ExecutionDecision:
    """Decisión de ejecución DENEGADA o RECHAZADA por compuerta."""
    intent = ActionIntent(
        intent_name="delete_database",
        confidence=0.95,
        target="prod_db",
        parameters={"db_name": "prod_db"},
    )
    gate = ExecutionGate(
        can_execute=False,
        needs_clarification=False,
        needs_confirmation=True,
        risk_level="CRITICAL",
        confirmation_prompt="¿Confirmas borrar?",
    )
    spec = ExecutionSpec(
        skill_id="test.mock_skill",
        tool_name="delete_database",
        idempotency_key="idemp-unauth-1",
    )
    contract = ActionIntentContract(
        request_id="req-unauth-001",
        session_id="sess-unauth-001",
        action_intent=intent,
        execution_gate=gate,
        pre_action_feedback=PreActionFeedback(),
        execution_spec=spec,
    )
    return ExecutionDecision(
        decision_type=GateDecisionType.ASK_CONFIRMATION,  # o REJECT
        contract=contract,
        reason="Acción requiere confirmación previa del usuario.",
        action_intent=intent,
        execution_gate=gate,
        execution_spec=spec,
        risk_level="CRITICAL",
        confidence=0.95,
        skill_id="test.mock_skill",
        operation="delete_database",
        parameters={"db_name": "prod_db"},
    )


# ── TEST A: Acción autorizada -> skill correcta ─────────────────────────────


def test_authorized_action_dispatches_to_correct_skill(
    isolated_registry: SkillRegistry,
    authorized_decision: ExecutionDecision,
) -> None:
    spy_skill = SpyMockSkill(skill_id="test.mock_skill")
    isolated_registry.register_skill(spy_skill)

    dispatcher = ExecutionDispatcher(registry=isolated_registry)
    result = dispatcher.dispatch(authorized_decision)

    assert result.status == DispatchStatus.SUCCESS
    assert result.is_success is True
    assert spy_skill.invocation_count == 1
    assert result.skill_id == "test.mock_skill"
    assert result.operation == "mock_action"


# ── TEST B: Skill inexistente -> NOT_FOUND ──────────────────────────────────


def test_missing_skill_returns_not_found(
    isolated_registry: SkillRegistry,
    authorized_decision: ExecutionDecision,
) -> None:
    # No registramos la skill en el registro
    dispatcher = ExecutionDispatcher(registry=isolated_registry)
    result = dispatcher.dispatch(authorized_decision)

    assert result.status == DispatchStatus.NOT_FOUND
    assert result.is_success is False
    assert result.execution_report.error_code == "SKILL_NOT_FOUND"
    assert result.contract.execution_report is not None
    assert result.contract.execution_report.claims_success is False


# ── TEST C: Operación no especificada -> NOT_FOUND / INVALID ────────────────


def test_missing_operation_returns_not_found(
    isolated_registry: SkillRegistry,
    authorized_decision: ExecutionDecision,
) -> None:
    spy_skill = SpyMockSkill(skill_id="test.mock_skill")
    isolated_registry.register_skill(spy_skill)

    # Modificamos la decisión para que solicite una operación que no existe
    empty_spec = ExecutionSpec(skill_id="test.mock_skill", tool_name="operacion_no_existente", idempotency_key="idemp-1")
    modified_contract = authorized_decision.contract.model_copy(update={"execution_spec": empty_spec})
    invalid_op_decision = ExecutionDecision(
        decision_type=GateDecisionType.EXECUTE,
        contract=modified_contract,
        reason="Autorizada",
        action_intent=authorized_decision.action_intent,
        execution_gate=authorized_decision.execution_gate,
        execution_spec=empty_spec,
        risk_level="SAFE",
        confidence=0.9,
        skill_id="test.mock_skill",
        operation="operacion_no_existente",
    )

    dispatcher = ExecutionDispatcher(registry=isolated_registry)
    result = dispatcher.dispatch(invalid_op_decision)

    assert result.status == DispatchStatus.NOT_FOUND
    assert result.is_success is False
    assert result.execution_report.error_code in ("MISSING_OPERATION", "OPERATION_NOT_FOUND")
    assert spy_skill.invocation_count == 0



# ── TEST D: Argumentos inválidos -> INVALID_ARGUMENTS ───────────────────────


def test_invalid_arguments_returns_invalid_arguments(
    isolated_registry: SkillRegistry,
) -> None:
    # windows.apps exige 'app_name' o 'nombre_app'
    spec = ExecutionSpec(skill_id="windows.apps", tool_name="open_application", idempotency_key="idemp-app")
    intent = ActionIntent(intent_name="open_application", parameters={})
    gate = ExecutionGate(can_execute=True, risk_level="SAFE")
    contract = ActionIntentContract(
        request_id="req-invalid-args",
        session_id="sess-1",
        action_intent=intent,
        execution_gate=gate,
        execution_spec=spec,
    )
    decision = ExecutionDecision(
        decision_type=GateDecisionType.EXECUTE,
        contract=contract,
        reason="Autorizada",
        action_intent=intent,
        execution_gate=gate,
        execution_spec=spec,
        risk_level="SAFE",
        confidence=0.9,
        skill_id="windows.apps",
        operation="open_application",
        parameters={},  # Sin app_name
    )

    from skills.apps_skill import WindowsAppsSkill
    isolated_registry.register_skill(WindowsAppsSkill())

    dispatcher = ExecutionDispatcher(registry=isolated_registry)
    result = dispatcher.dispatch(decision)

    assert result.status == DispatchStatus.INVALID_ARGUMENTS
    assert result.is_success is False
    assert result.execution_report.error_code == "INVALID_ARGUMENTS"


# ── TEST E: Skill lanza excepción -> EXCEPTION ──────────────────────────────


def test_skill_exception_is_handled_gracefully(
    isolated_registry: SkillRegistry,
    authorized_decision: ExecutionDecision,
) -> None:
    error_skill = SpyMockSkill(skill_id="test.mock_skill", should_raise=True)
    isolated_registry.register_skill(error_skill)

    dispatcher = ExecutionDispatcher(registry=isolated_registry)
    result = dispatcher.dispatch(authorized_decision)

    assert result.status == DispatchStatus.EXCEPTION
    assert result.is_success is False
    assert "Fallo simulado" in str(result.error)
    assert result.execution_report.claims_success is False


# ── TEST F: Skill devuelve fracaso -> FAILED ────────────────────────────────


def test_skill_failure_result_returns_failed(
    isolated_registry: SkillRegistry,
    authorized_decision: ExecutionDecision,
) -> None:
    failing_skill = SpyMockSkill(skill_id="test.mock_skill", should_fail=True)
    isolated_registry.register_skill(failing_skill)

    dispatcher = ExecutionDispatcher(registry=isolated_registry)
    result = dispatcher.dispatch(authorized_decision)

    assert result.status == DispatchStatus.FAILED
    assert result.is_success is False
    assert result.execution_report.claims_success is False
    assert result.execution_report.is_verified is False


# ── TEST G: Skill devuelve éxito real -> SUCCESS ────────────────────────────


def test_skill_genuine_success_returns_success(
    isolated_registry: SkillRegistry,
    authorized_decision: ExecutionDecision,
) -> None:
    success_skill = SpyMockSkill(skill_id="test.mock_skill", should_fail=False, return_evidence=True)
    isolated_registry.register_skill(success_skill)

    dispatcher = ExecutionDispatcher(registry=isolated_registry)
    result = dispatcher.dispatch(authorized_decision)

    assert result.status == DispatchStatus.SUCCESS
    assert result.is_success is True
    assert result.execution_report.claims_success is True
    assert result.execution_report.is_verified is True
    assert result.contract.execution_report is not None
    assert result.contract.execution_report.claims_success is True


# ── TEST H & I & J: Acción sin autorización / Gate bloqueado -> REJECTED ────


def test_unauthorized_action_is_rejected_without_executing_skill(
    isolated_registry: SkillRegistry,
    unauthorized_decision: ExecutionDecision,
) -> None:
    spy_skill = SpyMockSkill(skill_id="test.mock_skill")
    isolated_registry.register_skill(spy_skill)

    dispatcher = ExecutionDispatcher(registry=isolated_registry)
    result = dispatcher.dispatch(unauthorized_decision)

    assert result.status == DispatchStatus.REJECTED
    assert result.is_success is False
    # GARANTÍA CRÍTICA: La skill NUNCA debe ser invocada
    assert spy_skill.invocation_count == 0
    assert result.execution_report.claims_success is False
    assert result.execution_report.execution_status == "denied"


# ── TEST K: TEST DOBLE OBLIGATORIO (Spy Mock Skill) ─────────────────────────


def test_spy_mock_skill_invoked_on_authorized_and_not_invoked_on_rejected(
    isolated_registry: SkillRegistry,
    authorized_decision: ExecutionDecision,
    unauthorized_decision: ExecutionDecision,
) -> None:
    spy_skill = SpyMockSkill(skill_id="test.mock_skill")
    isolated_registry.register_skill(spy_skill)
    dispatcher = ExecutionDispatcher(registry=isolated_registry)

    # 1. Petición rechazada -> Invocation Count DEBE SER 0
    res_rejected = dispatcher.dispatch(unauthorized_decision)
    assert res_rejected.status == DispatchStatus.REJECTED
    assert spy_skill.invocation_count == 0

    # 2. Petición autorizada -> Invocation Count DEBE SER 1
    res_auth = dispatcher.dispatch(authorized_decision)
    assert res_auth.status == DispatchStatus.SUCCESS
    assert spy_skill.invocation_count == 1


# ── TEST L: Exactamente una operación ejecutada ──────────────────────────────


def test_dispatcher_executes_exactly_one_operation(
    isolated_registry: SkillRegistry,
    authorized_decision: ExecutionDecision,
) -> None:
    spy_skill = SpyMockSkill(skill_id="test.mock_skill")
    isolated_registry.register_skill(spy_skill)
    dispatcher = ExecutionDispatcher(registry=isolated_registry)

    result = dispatcher.dispatch(authorized_decision)

    assert result.status == DispatchStatus.SUCCESS
    assert spy_skill.invocation_count == 1


# ── TEST M & N: Preservación de action_id, skill y operation ────────────────


def test_trazabilidad_preserves_identifiers_and_metadata(
    isolated_registry: SkillRegistry,
    authorized_decision: ExecutionDecision,
) -> None:
    spy_skill = SpyMockSkill(skill_id="test.mock_skill")
    isolated_registry.register_skill(spy_skill)
    dispatcher = ExecutionDispatcher(registry=isolated_registry)

    result = dispatcher.dispatch(authorized_decision)

    assert result.action_id == authorized_decision.contract.request_id
    assert result.skill_id == "test.mock_skill"
    assert result.operation == "mock_action"
    assert result.contract.request_id == authorized_decision.contract.request_id
    assert result.contract.action_intent.intent_name == "mock_action"
    assert result.execution_report.skill_id == "test.mock_skill"
    assert result.execution_report.tool_name == "mock_action"
    assert result.duration_ms >= 0.0


# ── TEST O: Anti-False Success ──────────────────────────────────────────────


def test_anti_false_success_enforced_when_evidence_unverified(
    isolated_registry: SkillRegistry,
    authorized_decision: ExecutionDecision,
) -> None:
    # Skill devuelve exito=True pero return_evidence=False o no verificada
    unverified_skill = SpyMockSkill(skill_id="test.mock_skill", should_fail=False, return_evidence=False)
    isolated_registry.register_skill(unverified_skill)

    # Mock verifier que falla en confirmar
    mock_verifier = type("MockVerifier", (), {
        "verify_execution": lambda self, action, target, parameters, timeout_seconds: type(
            "Evidence", (), {"to_dict": lambda s: {"is_verified": False}}
        )()
    })()

    dispatcher = ExecutionDispatcher(registry=isolated_registry, verifier=mock_verifier)
    result = dispatcher.dispatch(authorized_decision)

    # No debe declarar éxito ya que no hubo evidencia comprobada
    assert result.is_success is False
    assert result.execution_report.claims_success is False
    assert result.execution_report.is_verified is False


# ── TEST P: Excepción no corrompe el proceso ────────────────────────────────


def test_unhandled_exception_does_not_crash_pipeline(
    isolated_registry: SkillRegistry,
    authorized_decision: ExecutionDecision,
) -> None:
    broken_skill = SpyMockSkill(skill_id="test.mock_skill", should_raise=True)
    isolated_registry.register_skill(broken_skill)

    dispatcher = ExecutionDispatcher(registry=isolated_registry)
    # No debe propagar un crash abrupto no tipado
    result = dispatcher.dispatch(authorized_decision)

    assert isinstance(result, DispatchResult)
    assert result.status == DispatchStatus.EXCEPTION
    assert result.is_success is False
    assert result.execution_report.claims_success is False


# ── TEST Q: Compatibilidad con Skill de producción windows.screenshot ───────


def test_compatibility_with_production_screenshot_skill(
    isolated_registry: SkillRegistry,
) -> None:
    from skills.screenshot_skill import WindowsScreenshotSkill
    isolated_registry.register_skill(WindowsScreenshotSkill())

    intent = ActionIntent(
        intent_name="capture_screen",
        confidence=0.98,
        target="desktop",
        parameters={"prompt": "Describir pantalla de prueba"},
    )
    spec = ExecutionSpec(
        skill_id="windows.screenshot",
        tool_name="capture_screen",
        idempotency_key="idemp-ss-1",
    )
    contract = ActionIntentContract(
        request_id="req-ss-prod-001",
        session_id="sess-ss-001",
        action_intent=intent,
        execution_gate=ExecutionGate(can_execute=True, risk_level="SAFE"),
        execution_spec=spec,
    )
    decision = ExecutionDecision(
        decision_type=GateDecisionType.EXECUTE,
        contract=contract,
        reason="Autorizado",
        action_intent=intent,
        execution_gate=ExecutionGate(can_execute=True, risk_level="SAFE"),
        execution_spec=spec,
        risk_level="SAFE",
        confidence=0.98,
        skill_id="windows.screenshot",
        operation="capture_screen",
        parameters={"prompt": "Describir pantalla de prueba"},
    )

    dispatcher = ExecutionDispatcher(registry=isolated_registry)
    result = dispatcher.dispatch(decision)

    assert result.skill_id == "windows.screenshot"
    assert result.action_id == "req-ss-prod-001"
    # Debe haber ejecutado y producido salida válida
    assert "analisis" in result.output or "mensaje" in result.output
