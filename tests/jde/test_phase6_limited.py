"""Tests de JDE Fase 6: Autoridad Limitada y Control por Capacidades.

Certifica:
1. SHADOW sigue siendo el valor por defecto seguro (Default Safe).
2. LIMITED requiere configuración explícita (JDE_AUTHORITY_MODE=LIMITED).
3. Configuración inválida o ausente revierte a SHADOW.
4. Capability desconocida -> DENY.
5. Capability deshabilitada -> DENY.
6. Capability LOW autorizada -> ALLOW.
7. Capability MEDIUM no autorizada -> DENY.
8. HIGH risk -> DENY / REQUIRE_VERIFICATION (fuera de LIMITED).
9. Capability sin verifier -> no SUCCESS (UNKNOWN).
10. UNKNOWN -> UNKNOWN.
11. UNKNOWN -> claims_success=False.
12. Verified positive -> SUCCESS.
13. Receipt obligatorio con trazabilidad de capability.
14. Receipt corrupto -> fallo de integridad SHA-256.
15. Doble ejecución imposible (execution_count == 1).
16. Idempotencia y correlación preservada.
17. Computer Use uncertain -> no autorizado / UNKNOWN.
18. Browser uncertain -> no autorizado / UNKNOWN.
19. YouTube uncertain -> no autorizado / UNKNOWN.
20. LLM no puede otorgarse autoridad.
21. Parameter fuera de scope (rutas críticas de SO) -> DENY.
22. Capability fuera de scope (archivos fuera de workspace temporal) -> DENY.
23. Human confirmation requerida -> NOT_EXECUTED si no existe confirmación.
24. LIMITED no puede auto-escalar a PROGRESSIVE.
25. LIMITED no puede auto-escalar a FULL.
26. ActionReceipt auditado contiene authority_mode=LIMITED y capability.
27. Métricas LIMITED registran telemetría precisa.
28. false_success == 0 en todas las condiciones.
29. Matriz obligatoria de decisiones y resultados.
30. Pruebas reales en disco (SUCCESS verificado y UNKNOWN controlado).
"""

from __future__ import annotations

import os
import tempfile
from typing import Any
from unittest.mock import Mock, patch
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
from core.jde.capabilities import (
    Capability,
    CapabilityRegistry,
    get_capability_registry,
    reset_capability_registry,
)
from core.jde.engine import DecisionEngine
from core.jde.models import DecisionRequest, DecisionResult, PolicyRequirement
from core.jde.receipts import ActionReceipt
from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType


@pytest.fixture(autouse=True)
def clean_limited_environment():
    """Restaura el entorno, la allowlist y singletons antes y después de cada test."""
    old_env = os.environ.get("JDE_AUTHORITY_MODE")
    ExecutionIdempotencyGuard.get_instance().clear()
    reset_capability_registry()
    reset_authority_gate(AuthorityMode.SHADOW)
    yield
    ExecutionIdempotencyGuard.get_instance().clear()
    if old_env is not None:
        os.environ["JDE_AUTHORITY_MODE"] = old_env
    else:
        os.environ.pop("JDE_AUTHORITY_MODE", None)
    reset_capability_registry()
    reset_authority_gate(AuthorityMode.SHADOW)


# ==============================================================================
# 1. CONFIGURACIÓN Y FAIL-SAFE (Tests 1-3)
# ==============================================================================


def test_01_shadow_remains_safe_default():
    """1. SHADOW sigue siendo el modo por defecto seguro en ausencia de configuración."""
    with patch.dict(os.environ, {}, clear=True):
        gate = JDEAuthorityGate(mode=None)
        assert gate.current_mode == AuthorityMode.SHADOW
        assert gate.is_shadow is True
        assert gate.is_limited is False
        assert gate.can_execute("read_file", "files") is False


def test_02_limited_requires_explicit_configuration():
    """2. LIMITED requiere configuración explícita opt-in."""
    with patch.dict(os.environ, {"JDE_AUTHORITY_MODE": "LIMITED"}):
        gate = JDEAuthorityGate(mode=None)
        assert gate.current_mode == AuthorityMode.LIMITED
        assert gate.is_limited is True
        assert gate.is_shadow is False


def test_03_invalid_config_reverts_to_shadow():
    """3. Configuración inválida o corrupta activa fail-safe SHADOW."""
    for invalid_val in ["", "   ", "FULL_AUTO", "SUPER_ADMIN", "UNKNOWN_MODE", "123"]:
        with patch.dict(os.environ, {"JDE_AUTHORITY_MODE": invalid_val}):
            gate = JDEAuthorityGate(mode=None)
            assert gate.current_mode == AuthorityMode.SHADOW
            assert gate.is_shadow is True


# ==============================================================================
# 2. CAPABILITY REGISTRY Y GOBERNANZA (Tests 4-9)
# ==============================================================================


def test_04_unknown_capability_denied():
    """4. Capability desconocida en LIMITED resulta en DENY."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    eval_res = gate.evaluate_authority(
        action="unregistered_action_xyz",
        tool="unregistered_tool",
    )
    assert eval_res.decision == AuthorityDecision.DENY
    assert eval_res.can_execute is False
    assert "no existe en CapabilityRegistry" in eval_res.reason


def test_05_disabled_capability_denied():
    """5. Capability deshabilitada en CapabilityRegistry resulta en DENY."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    reg = get_capability_registry()
    assert reg.disable("files.read") is True

    eval_res = gate.evaluate_authority(
        action="read_file",
        tool="files",
    )
    assert eval_res.decision == AuthorityDecision.DENY
    assert eval_res.can_execute is False
    assert "está deshabilitada" in eval_res.reason


def test_06_low_risk_capability_authorized_allowed():
    """6. Capability LOW autorizada en LIMITED resulta en ALLOW."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    eval_res = gate.evaluate_authority(
        action="read_file",
        tool="files",
        parameters={"path": "test.txt"},
    )
    assert eval_res.decision == AuthorityDecision.ALLOW
    assert eval_res.can_execute is True
    assert eval_res.capability_id == "files.read"
    assert eval_res.risk_tier == ActionRiskTier.LOW


def test_07_unauthorized_medium_risk_capability_denied():
    """7. Capability MEDIUM no autorizada para LIMITED (ej. write general) resulta en DENY."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    # files.write_uncontrolled requiere PROGRESSIVE
    eval_res = gate.evaluate_authority(
        action="write_file",
        tool="files",
        parameters={"path": "d:\\data\\uncontrolled.txt"},
    )
    assert eval_res.decision == AuthorityDecision.DENY
    assert eval_res.can_execute is False
    assert "no está autorizada para modo LIMITED" in eval_res.reason


def test_08_high_risk_excluded_from_limited():
    """8. Acciones de riesgo HIGH quedan incondicionalmente excluidas de LIMITED."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    for high_action in ["delete_file", "kill_process", "write_registry", "system_shutdown"]:
        # Sin confirmación humana: REQUIRE_VERIFICATION (no ejecutable)
        eval_res_unconf = gate.evaluate_authority(
            action=high_action,
            tool="files" if "file" in high_action else "system",
            user_confirmed=False,
        )
        assert eval_res_unconf.decision == AuthorityDecision.REQUIRE_VERIFICATION
        assert eval_res_unconf.can_execute is False

        # Con confirmación humana: DENY (HIGH sigue fuera de LIMITED)
        eval_res_conf = gate.evaluate_authority(
            action=high_action,
            tool="files" if "file" in high_action else "system",
            user_confirmed=True,
        )
        assert eval_res_conf.decision == AuthorityDecision.DENY
        assert eval_res_conf.can_execute is False


def test_09_capability_without_verifier_no_success():
    """9. Ejecución de capability sin verifier nunca produce SUCCESS (resuelve UNKNOWN)."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-09",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "some_file.txt"},
        verification_requirements=[],  # Sin contrato
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {"content": "data"}),
        # verifier_override no suministrado y sin verification_requirements
    )

    assert res.state == DecisionState.UNKNOWN
    assert res.claims_success is False
    assert res.state != DecisionState.SUCCESS


# ==============================================================================
# 3. VERIFICACIÓN Y ANTI-FALSE SUCCESS (Tests 10-12)
# ==============================================================================


def test_10_unknown_verification_results_in_unknown():
    """10. Si la verificación resulta UNVERIFIABLE, el estado final es estrictamente UNKNOWN."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-10",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "test.txt"},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (VerificationStatusType.UNVERIFIABLE, False, {}),
    )

    assert res.state == DecisionState.UNKNOWN
    assert res.verification_status == VerificationStatusType.UNVERIFIABLE


def test_11_unknown_strictly_forbids_claims_success():
    """11. UNKNOWN obliga incondicionalmente claims_success=False."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-11",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "test.txt"},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (VerificationStatusType.UNVERIFIABLE, False, {}),
    )

    assert res.claims_success is False
    assert res.success is False


def test_12_verified_positive_results_in_success():
    """12. Verificación positiva comprobada (VERIFIED_TRUE) produce SUCCESS."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-12",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "test.txt"},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {"content": "ok"}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {"size": 42}),
    )

    assert res.state == DecisionState.SUCCESS
    assert res.claims_success is True
    assert res.success is True


# ==============================================================================
# 4. ACTION RECEIPT E INTEGRIDAD CRIPTOGRÁFICA (Tests 13-14)
# ==============================================================================


def test_13_receipt_mandated_with_capability_traceability():
    """13. Toda operación en LIMITED produce un ActionReceipt con capability y authority_mode."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-13",
        correlation_id="corr-lim-13",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "readme.txt"},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )

    assert res.receipt_id is not None
    assert res.receipt_data is not None
    receipt = ActionReceipt(**res.receipt_data)
    assert receipt.authority_mode == "LIMITED"
    assert receipt.capability == "files.read"
    assert receipt.correlation_id == "corr-lim-13"
    assert receipt.verify_integrity() is True


def test_14_corrupted_receipt_fails_integrity():
    """14. Recibo con datos alterados falla la validación de integridad SHA-256."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-14",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "readme.txt"},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )

    receipt = ActionReceipt(**res.receipt_data)
    assert receipt.verify_integrity() is True

    # Intento de falsificación de estado o parámetros
    tampered_dict = receipt.model_dump()
    tampered_dict["final_status"] = "SUCCESS"
    tampered_dict["parameters"] = {"path": "hacked.txt"}
    tampered_receipt = ActionReceipt(**tampered_dict)
    assert tampered_receipt.verify_integrity() is False


# ==============================================================================
# 5. IDEMPOTENCIA Y PROTECCIÓN ANTI-DOBLE EJECUCIÓN (Tests 15-16)
# ==============================================================================


def test_15_double_execution_impossible():
    """15. Solicitud duplicada no ejecuta dos veces (execution_count == 1)."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)
    executor_mock = Mock(return_value=(ExecutionStatusType.OK, {}))

    req = DecisionRequest(
        request_id="req-test-15-unique",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "unique_read.txt"},
    )

    # 1. Primera ejecución exitosa
    res1 = engine.decide_and_execute(
        request=req,
        executor=executor_mock,
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )
    assert executor_mock.call_count == 1
    assert res1.state == DecisionState.SUCCESS

    # 2. Intento de re-ejecución inmediata de la misma solicitud
    res2 = engine.decide_and_execute(
        request=req,
        executor=executor_mock,
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )
    assert executor_mock.call_count == 1  # No se incrementó
    assert res2.state == DecisionState.NOT_EXECUTED
    assert res2.error_code == "DUPLICATE_EXECUTION_BLOCKED"


def test_16_idempotency_preserves_contract():
    """16. Idempotencia: una solicitud duplicada no modifica estado ni produce doble efecto."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-16-idem",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "idem.txt"},
    )

    res1 = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )
    res2 = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )

    assert res1.state == DecisionState.SUCCESS
    assert res2.state == DecisionState.NOT_EXECUTED
    assert gate.metrics.limited_double_execution == 0


# ==============================================================================
# 6. CONSTRAINTS DE DOMINIO: COMPUTER USE, BROWSER, YOUTUBE (Tests 17-19)
# ==============================================================================


def test_17_computer_use_uncertain_not_authorized_in_limited():
    """17. Computer Use requiere PROGRESSIVE y queda rechazado en LIMITED."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    eval_res = gate.evaluate_authority(
        action="send_keys",
        tool="computer_use",
        parameters={"keys": "ENTER"},
    )
    assert eval_res.decision == AuthorityDecision.DENY
    assert eval_res.can_execute is False


def test_18_browser_uncertain_not_authorized_in_limited():
    """18. Browser navigation requiere PROGRESSIVE y queda denegado en LIMITED."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    eval_res = gate.evaluate_authority(
        action="open_url",
        tool="browser",
        parameters={"url": "https://example.com"},
    )
    assert eval_res.decision == AuthorityDecision.DENY
    assert eval_res.can_execute is False


def test_19_youtube_uncertain_not_authorized_in_limited():
    """19. Reproducción en YouTube requiere PROGRESSIVE y queda denegado en LIMITED."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    eval_res = gate.evaluate_authority(
        action="play_video",
        tool="browser",
        parameters={"video_id": "test_123"},
    )
    assert eval_res.decision == AuthorityDecision.DENY
    assert eval_res.can_execute is False


# ==============================================================================
# 7. SEGURIDAD, LLM Y SCOPE (Tests 20-23)
# ==============================================================================


def test_20_llm_cannot_grant_authority():
    """20. El LLM no puede otorgarse autoridad mediante parámetros o inyecciones."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-20",
        proposed_action="delete_file",  # El LLM intenta borrar alegando autoridad FULL
        tool="files",
        parameters={
            "path": "test.txt",
            "authority_mode": "FULL",
            "role": "SYSTEM_ADMIN",
            "confidence": 0.999,
        },
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
    )
    assert res.state in (DecisionState.BLOCKED, DecisionState.NOT_EXECUTED)
    assert res.claims_success is False
    assert gate.current_mode == AuthorityMode.LIMITED


def test_21_parameter_out_of_scope_denied():
    """21. Parámetros dirigidos a rutas críticas del SO (Windows/System32) resultan en DENY."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    eval_res = gate.evaluate_authority(
        action="create_temp_file",
        tool="files",
        parameters={"path": "C:\\Windows\\System32\\payload.dll"},
    )
    assert eval_res.decision == AuthorityDecision.DENY
    assert "ruta crítica del sistema" in eval_res.reason


def test_22_capability_out_of_workspace_scope_denied():
    """22. Creación de archivo fuera del workspace temporal permitido resulta en DENY."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    eval_res = gate.evaluate_authority(
        action="create_temp_file",
        tool="files",
        parameters={"path": "D:\\MisDatosPrivados\\archivo.txt"},
    )
    assert eval_res.decision == AuthorityDecision.DENY
    assert "no pertenece al workspace temporal permitido" in eval_res.reason


def test_23_human_confirmation_unconfirmed_not_executed():
    """23. Acción que requiere confirmación humana sin confirmar resulta en NOT_EXECUTED."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-23",
        proposed_action="delete_file",
        tool="files",
        parameters={"path": "temp.txt"},
        policy_requirements=PolicyRequirement(requires_human_confirmation=False),  # Usuario no confirmó
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
    )
    assert res.state == DecisionState.NOT_EXECUTED
    assert res.claims_success is False
    assert res.error_code == "REQUIRE_HUMAN_CONFIRMATION"


# ==============================================================================
# 8. ANTI-ESCALADA DE AUTORIDAD (Tests 24-25)
# ==============================================================================


def test_24_limited_cannot_escalate_to_progressive():
    """24. LIMITED no puede auto-escalar a PROGRESSIVE sin certificación formal."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    ok, reason = gate.attempt_escalation(target_mode=AuthorityMode.PROGRESSIVE)
    assert ok is False
    assert gate.current_mode == AuthorityMode.LIMITED
    assert "no puede auto-escalar" in reason


def test_25_limited_cannot_escalate_to_full():
    """25. LIMITED no puede auto-escalar a FULL bajo ninguna circunstancia."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    ok, reason = gate.attempt_escalation(target_mode=AuthorityMode.FULL)
    assert ok is False
    assert gate.current_mode == AuthorityMode.LIMITED
    assert "no puede auto-escalar" in reason


# ==============================================================================
# 9. TELEMETRÍA Y MÉTRICAS (Tests 26-28)
# ==============================================================================


def test_26_audit_receipt_contains_limited_authority_mode():
    """26. El audit trail y receipt generado contiene authority_mode=LIMITED y capability."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-26",
        proposed_action="query_system_info",
        tool="system",
        parameters={},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {"cpu": 15}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {"cpu": 15}),
    )

    assert res.state == DecisionState.SUCCESS
    assert res.receipt_data["authority_mode"] == "LIMITED"
    assert res.receipt_data["capability"] == "system.query"


def test_27_limited_metrics_tracking():
    """27. Las métricas de LIMITED registran actividad correcta."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    # 1. Éxito permitido y verificado
    req1 = DecisionRequest(
        request_id="req-m-1",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "test.txt"},
    )
    engine.decide_and_execute(
        request=req1,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )

    # 2. Denegado por fuera de scope
    req2 = DecisionRequest(
        request_id="req-m-2",
        proposed_action="write_file",
        tool="files",
        parameters={"path": "out.txt"},
    )
    engine.decide_and_execute(
        request=req2,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
    )

    summary = gate.metrics.summary()
    assert summary["limited_total"] >= 2
    assert summary["limited_allowed"] >= 1
    assert summary["limited_denied"] >= 1
    assert summary["limited_success"] >= 1


def test_28_limited_false_success_strictly_zero():
    """28. Invariante fundamental: limited_false_success == 0 en todas las condiciones."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    # Forzar ejecuciones con fallo y UNKNOWN
    for i in range(5):
        req = DecisionRequest(
            request_id=f"req-fs-{i}",
            proposed_action="read_file",
            tool="files",
            parameters={"path": f"f_{i}.txt"},
        )
        engine.decide_and_execute(
            request=req,
            executor=lambda t, p: (ExecutionStatusType.OK, {}),
            verifier_override=lambda p: (VerificationStatusType.UNVERIFIABLE, False, {}),
        )

    summary = gate.metrics.summary()
    assert summary["limited_false_success"] == 0
    assert summary["false_success"] == 0


# ==============================================================================
# 10. MATRIZ FORMAL OBLIGATORIA (Test 29)
# ==============================================================================


@pytest.mark.parametrize(
    "cap_action,tool,risk,params,should_allow,verifier_status,expected_final_state",
    [
        # 1. lectura + LOW + Allowed + Verified -> SUCCESS
        (
            "read_file",
            "files",
            ActionRiskTier.LOW,
            {"path": "data.txt"},
            True,
            VerificationStatusType.VERIFIED_TRUE,
            DecisionState.SUCCESS,
        ),
        # 2. lectura + LOW + Allowed + Not Verified (UNVERIFIABLE) -> UNKNOWN
        (
            "read_file",
            "files",
            ActionRiskTier.LOW,
            {"path": "data.txt"},
            True,
            VerificationStatusType.UNVERIFIABLE,
            DecisionState.UNKNOWN,
        ),
        # 3. escritura temporal + MEDIUM + Allowed (in temp dir) + Verified -> SUCCESS
        (
            "create_temp_file",
            "files",
            ActionRiskTier.MEDIUM,
            {"path": os.path.join(tempfile.gettempdir(), "test_mat.tmp")},
            True,
            VerificationStatusType.VERIFIED_TRUE,
            DecisionState.SUCCESS,
        ),
        # 4. escritura general + MEDIUM + Not Allowed in LIMITED -> BLOCKED (POLICY_DENIED)
        (
            "write_file",
            "files",
            ActionRiskTier.MEDIUM,
            {"path": "D:\\data\\uncontrolled.txt"},
            False,
            VerificationStatusType.VERIFIED_TRUE,
            DecisionState.BLOCKED,
        ),
        # 5. delete + HIGH + Not Allowed in LIMITED -> NOT_EXECUTED (REQUIRE_HUMAN_CONFIRMATION)
        (
            "delete_file",
            "files",
            ActionRiskTier.HIGH,
            {"path": "temp.tmp"},
            False,
            VerificationStatusType.VERIFIED_TRUE,
            DecisionState.NOT_EXECUTED,
        ),
        # 6. kill + HIGH + Not Allowed in LIMITED -> NOT_EXECUTED (REQUIRE_HUMAN_CONFIRMATION)
        (
            "kill_process",
            "process",
            ActionRiskTier.HIGH,
            {"pid": 1234},
            False,
            VerificationStatusType.VERIFIED_TRUE,
            DecisionState.NOT_EXECUTED,
        ),
        # 7. browser uncertain + MEDIUM + Not Allowed -> BLOCKED
        (
            "open_url",
            "browser",
            ActionRiskTier.MEDIUM,
            {"url": "https://example.com"},
            False,
            VerificationStatusType.UNVERIFIABLE,
            DecisionState.BLOCKED,
        ),
        # 8. Computer Use uncertain + MEDIUM + Not Allowed -> BLOCKED
        (
            "send_keys",
            "computer_use",
            ActionRiskTier.MEDIUM,
            {"keys": "TAB"},
            False,
            VerificationStatusType.UNVERIFIABLE,
            DecisionState.BLOCKED,
        ),
        # 9. capability inexistente -> BLOCKED
        (
            "non_existent_capability_action",
            "unregistered",
            ActionRiskTier.MEDIUM,
            {},
            False,
            VerificationStatusType.NOT_RUN,
            DecisionState.BLOCKED,
        ),
    ],
)
def test_29_mandatory_decision_matrix(
    cap_action: str,
    tool: str,
    risk: ActionRiskTier,
    params: dict[str, Any],
    should_allow: bool,
    verifier_status: VerificationStatusType,
    expected_final_state: DecisionState,
):
    """29. Matriz obligatoria de decisiones, capacidades y resultados en LIMITED."""
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    eval_res = gate.evaluate_authority(
        action=cap_action,
        tool=tool,
        parameters=params,
        user_confirmed=False,
    )

    if should_allow:
        assert eval_res.decision == AuthorityDecision.ALLOW
        assert eval_res.can_execute is True
    else:
        assert eval_res.decision in (AuthorityDecision.DENY, AuthorityDecision.REQUIRE_VERIFICATION)
        assert eval_res.can_execute is False

    req = DecisionRequest(
        request_id=f"req-mat-{cap_action}",
        proposed_action=cap_action,
        tool=tool,
        parameters=params,
    )

    is_verified_bool = (verifier_status == VerificationStatusType.VERIFIED_TRUE)
    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (verifier_status, is_verified_bool, {}),
    )

    assert res.state == expected_final_state
    if expected_final_state != DecisionState.SUCCESS:
        assert res.claims_success is False


# ==============================================================================
# 11. PRUEBAS REALES EN DISCO (Test 30)
# ==============================================================================


def test_30_real_execution_flow_success_and_unknown():
    """30. Ejecución real de creación de archivo temporal con verificación en SO y ActionReceipt.

    Prueba Real 1: Flujo real verificado exitosamente -> SUCCESS, execution_count == 1.
    Prueba Real 2: Flujo real con verificación impedida/fallida -> UNKNOWN, execution_count == 1, claims_success == False.
    """
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    # ── PRUEBA REAL 1: SUCCESS VERIFICADO ──
    temp_dir = tempfile.gettempdir()
    real_file_path = os.path.join(temp_dir, "jde_limited_real_test_success.tmp")

    if os.path.exists(real_file_path):
        os.remove(real_file_path)

    executor_calls = 0

    def real_filesystem_executor(t: str, p: dict[str, Any]):
        nonlocal executor_calls
        executor_calls += 1
        with open(p["path"], "w", encoding="utf-8") as f:
            f.write("JDE LIMITED REAL VERIFIED CONTENT")
        return ExecutionStatusType.OK, {"path": p["path"]}

    def real_filesystem_verifier(p: dict[str, Any]):
        target = p["path"]
        exists = os.path.exists(target)
        if exists:
            size = os.path.getsize(target)
            return VerificationStatusType.VERIFIED_TRUE, True, {"size": size, "exists": True}
        return VerificationStatusType.VERIFIED_FALSE, False, {"exists": False}

    req_success = DecisionRequest(
        request_id="req-real-limited-01",
        correlation_id="corr-real-limited-01",
        proposed_action="create_temp_file",
        tool="files",
        parameters={"path": real_file_path},
    )

    try:
        res1 = engine.decide_and_execute(
            request=req_success,
            executor=real_filesystem_executor,
            verifier_override=real_filesystem_verifier,
        )

        assert res1.state == DecisionState.SUCCESS
        assert res1.claims_success is True
        assert executor_calls == 1
        assert os.path.exists(real_file_path)

        receipt = ActionReceipt(**res1.receipt_data)
        assert receipt.authority_mode == "LIMITED"
        assert receipt.capability == "files.create_temp"
        assert receipt.verify_integrity() is True
    finally:
        if os.path.exists(real_file_path):
            os.remove(real_file_path)

    # ── PRUEBA REAL 2: VERIFICACIÓN IMPEDIDA -> UNKNOWN ──
    real_file_path2 = os.path.join(temp_dir, "jde_limited_real_test_unknown.tmp")
    if os.path.exists(real_file_path2):
        os.remove(real_file_path2)

    executor_calls_2 = 0

    def real_executor_2(t: str, p: dict[str, Any]):
        nonlocal executor_calls_2
        executor_calls_2 += 1
        with open(p["path"], "w", encoding="utf-8") as f:
            f.write("CONTENT")
        return ExecutionStatusType.OK, {"path": p["path"]}

    # Verifier simulando imposibilidad de comprobar el estado observable (UNKNOWN)
    def broken_verifier(p: dict[str, Any]):
        return VerificationStatusType.UNVERIFIABLE, False, {"error": "Observer detached"}

    req_unknown = DecisionRequest(
        request_id="req-real-limited-02",
        correlation_id="corr-real-limited-02",
        proposed_action="create_temp_file",
        tool="files",
        parameters={"path": real_file_path2},
    )

    try:
        res2 = engine.decide_and_execute(
            request=req_unknown,
            executor=real_executor_2,
            verifier_override=broken_verifier,
        )

        assert res2.state == DecisionState.UNKNOWN
        assert res2.claims_success is False
        assert executor_calls_2 == 1  # Cero reintentos automáticos en LIMITED ante UNKNOWN

        receipt2 = ActionReceipt(**res2.receipt_data)
        assert receipt2.authority_mode == "LIMITED"
        assert receipt2.final_status == DecisionState.UNKNOWN
        assert receipt2.verify_integrity() is True
    finally:
        if os.path.exists(real_file_path2):
            os.remove(real_file_path2)
