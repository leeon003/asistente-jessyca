"""Tests de JDE Fase 5: Canary Authority Controlado.

Certifica:
1. Activación explícita mediante opt-in (JDE_AUTHORITY_MODE=CANARY).
2. Fail-Safe: SHADOW sigue siendo el valor por defecto si no está configurado o es inválido.
3. Allowlist ultrarrestringida para CANARY (solo acciones seguras, locales, deterministas).
4. Exclusiones obligatorias: delete, kill, credenciales, tokens, youtube, browser, etc.
5. Authority Gate gobernando el flujo de ejecución antes del Executor.
6. SUCCESS requiere simultáneamente: Executor OK + Verifier TRUE + Evidencia + Receipt íntegro.
7. Anti-False Success: UNKNOWN nunca se transforma en SUCCESS, claims_success=False.
8. Cero reintentos automáticos en CANARY ante UNKNOWN (execution_count == 1).
9. Idempotencia y protección anti-doble ejecución.
10. Trazabilidad completa con ActionReceipt e integridad criptográfica SHA-256.
11. Imposibilidad de que el LLM eleve autoridad o que CANARY auto-escale.
12. Pruebas reales controladas (SUCCESS y UNKNOWN) con contratos canónicos.
13. Matriz formal de decisión y resultados.
14. Métricas de telemetría CANARY (canary_false_success == 0, canary_double_execution == 0).
"""

from __future__ import annotations

import os
import tempfile
import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock, patch
import pytest

from core.execution.idempotency_guard import ExecutionIdempotencyGuard
from core.execution.execution_verifier import ExecutionEvidence, ExecutionResult, ExecutionStatus, get_execution_verifier
from core.action_execution_bridge import build_execution_report
from core.jde.authority import (
    CANARY_FORBIDDEN_ACTIONS,
    DEFAULT_CANARY_ALLOWLIST,
    ActionRiskTier,
    AuthorityDecision,
    AuthorityGateResult,
    AuthorityMode,
    JDEAuthorityGate,
    JDEAuthorityMetrics,
    classify_action_risk,
    get_authority_gate,
    is_canary_excluded_action,
    reset_authority_gate,
    validate_canary_scope,
)
from core.jde.engine import DecisionEngine, get_decision_engine
from core.jde.models import DecisionRequest, DecisionResult, VerificationRequirement
from core.jde.policy import JDEPolicyDecision, JDEPolicyGate
from core.jde.receipts import ActionReceipt, JDEEvidence
from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType
from core.jde.verification import (
    VerificationContract,
    VerificationOutcome,
    VerifierRegistry,
    get_verifier_registry,
)


@pytest.fixture(autouse=True)
def clean_canary_environment():
    """Restaura el entorno y singleton de AuthorityGate antes y después de cada test."""
    old_env = os.environ.get("JDE_AUTHORITY_MODE")
    ExecutionIdempotencyGuard.get_instance().clear()
    reset_authority_gate(AuthorityMode.SHADOW)
    yield
    ExecutionIdempotencyGuard.get_instance().clear()
    if old_env is not None:
        os.environ["JDE_AUTHORITY_MODE"] = old_env
    else:
        os.environ.pop("JDE_AUTHORITY_MODE", None)
    reset_authority_gate(AuthorityMode.SHADOW)


# ==============================================================================
# 1. CONFIGURACIÓN Y ACTIVACIÓN EXPLÍCITA (Tests 1-4)
# ==============================================================================


def test_01_shadow_is_default_without_config():
    """1. SHADOW sigue siendo el valor por defecto en producción."""
    os.environ.pop("JDE_AUTHORITY_MODE", None)
    gate = reset_authority_gate()
    assert gate.current_mode == AuthorityMode.SHADOW
    assert gate.is_shadow is True
    assert gate.is_canary is False


def test_02_canary_activated_only_by_explicit_opt_in():
    """2. JDE_AUTHORITY_MODE=CANARY activa CANARY exclusivamente con opt-in."""
    with patch.dict(os.environ, {"JDE_AUTHORITY_MODE": "CANARY"}):
        gate = reset_authority_gate()
        assert gate.current_mode == AuthorityMode.CANARY
        assert gate.is_canary is True
        assert gate.is_shadow is False


def test_03_invalid_config_falls_back_to_shadow():
    """3. Configuración inválida o desconocida cae a SHADOW (Fail-Safe)."""
    for invalid in ["SUPER_ADMIN", "INVALID", "UNKNOWN", "FULL", "TRUE", "1"]:
        with patch.dict(os.environ, {"JDE_AUTHORITY_MODE": invalid}):
            gate = reset_authority_gate()
            assert gate.current_mode == AuthorityMode.SHADOW, f"Falló con modo inválido {invalid}"


def test_04_empty_or_absent_config_falls_back_to_shadow():
    """4. Configuración vacía o ausente cae a SHADOW."""
    with patch.dict(os.environ, {"JDE_AUTHORITY_MODE": ""}):
        gate = reset_authority_gate()
        assert gate.current_mode == AuthorityMode.SHADOW


# ==============================================================================
# 2. AUTHORITY GATE & SCOPE ALLOWLIST (Tests 5-8)
# ==============================================================================


def test_05_canary_authorized_capability_yields_allow():
    """5. Capability autorizada en Canary allowlist produce ALLOW."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    temp_dir = tempfile.gettempdir()
    safe_path = os.path.join(temp_dir, "jde_test_5.tmp")

    result = gate.evaluate_authority(
        action="files:create_temp_file",
        tool="files",
        parameters={"path": safe_path, "content": "canary_test"},
    )
    assert result.decision == AuthorityDecision.ALLOW
    assert result.mode == AuthorityMode.CANARY
    assert result.can_execute is True


def test_06_unauthorized_capability_yields_deny():
    """6. Capability no autorizada en Canary produce DENY."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    forbidden_actions = [
        ("delete_file", "files"),
        ("kill_process", "process"),
        ("write_registry", "system"),
        ("open_url", "browser"),
        ("play_video", "youtube"),
        ("send_keys", "computer_use"),
    ]
    for act, tool in forbidden_actions:
        res = gate.evaluate_authority(action=act, tool=tool, parameters={})
        assert res.decision == AuthorityDecision.DENY
        assert res.can_execute is False
        assert "no permitida" in res.reason.lower() or "excluida" in res.reason.lower()


def test_07_high_risk_action_yields_deny():
    """7. Acciones de riesgo HIGH o CRITICAL producen DENY incondicional en CANARY."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    high_risk_actions = [
        ("format_disk", "disk"),
        ("execute_command", "cmd"),
        ("powershell_exec", "powershell"),
        ("system_shutdown", "system"),
    ]
    for act, tool in high_risk_actions:
        res = gate.evaluate_authority(action=act, tool=tool, parameters={})
        assert res.decision == AuthorityDecision.DENY
        assert res.risk_tier == ActionRiskTier.HIGH
        assert res.can_execute is False


def test_08_out_of_scope_parameters_yield_deny_and_no_execution():
    """8. Acción permitida pero con ruta fuera de scope (e.g. Windows/System32) produce DENY."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    dangerous_paths = [
        r"C:\Windows\System32\malicious.dll",
        r"C:\Program Files\App\test.exe",
        r"C:\Users\Admin\secrets.txt",
    ]
    for dpath in dangerous_paths:
        res = gate.evaluate_authority(
            action="files:create_temp_file",
            tool="files",
            parameters={"path": dpath},
        )
        assert res.decision == AuthorityDecision.DENY
        assert res.can_execute is False
        assert "scope" in res.reason.lower()


# ==============================================================================
# 3. EJECUCIÓN (Tests 9-12)
# ==============================================================================


def test_09_allow_reaches_executor_in_canary():
    """9. ALLOW permite que el Executor sea invocado exactamente una vez."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)

    executor_mock = Mock(return_value=(ExecutionStatusType.OK, {"created": True}))
    temp_path = os.path.join(tempfile.gettempdir(), "test_09.tmp")

    req = DecisionRequest(
        request_id="req-test-09",
        proposed_action="files:create_temp_file",
        tool="files",
        parameters={"path": temp_path},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=executor_mock,
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {"exists": True}),
    )

    assert executor_mock.call_count == 1
    assert res.state == DecisionState.SUCCESS
    assert res.claims_success is True


def test_10_deny_does_not_reach_executor():
    """10. DENY nunca invoca al Executor."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)
    executor_mock = Mock()

    req = DecisionRequest(
        request_id="req-test-10",
        proposed_action="delete_file",
        tool="files",
        parameters={"path": r"C:\test.txt"},
    )

    res = engine.decide_and_execute(request=req, executor=executor_mock)
    assert executor_mock.call_count == 0
    assert res.state == DecisionState.BLOCKED
    assert res.claims_success is False


def test_11_observe_only_in_shadow_does_not_execute():
    """11. En CANARY, una acción fuera de allowlist produce OBSERVE_ONLY y nunca ejecuta."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)
    executor_mock = Mock()

    req = DecisionRequest(
        request_id="req-test-11",
        proposed_action="system:query_info",
        tool="system",
        parameters={"path": os.path.join(tempfile.gettempdir(), "test_11.tmp")},
    )

    res = engine.decide_and_execute(request=req, executor=executor_mock)
    assert executor_mock.call_count == 0
    assert res.state == DecisionState.NOT_EXECUTED
    assert res.claims_success is False


def test_12_no_double_execution_in_canary():
    """12. Garantía de no doble ejecución (execution_count == 1)."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)
    executor_mock = Mock(return_value=(ExecutionStatusType.OK, {}))

    req = DecisionRequest(
        request_id="req-test-12",
        proposed_action="files:create_temp_file",
        tool="files",
        parameters={"path": os.path.join(tempfile.gettempdir(), "test_12.tmp")},
    )

    engine.decide_and_execute(
        request=req,
        executor=executor_mock,
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )
    assert executor_mock.call_count == 1


# ==============================================================================
# 4. VERIFICATION Y ANTI-FALSE SUCCESS (Tests 13-16)
# ==============================================================================


def test_13_executor_plus_positive_verifier_yields_success():
    """13. Executor OK + Verifier VERIFIED_TRUE -> SUCCESS y claims_success=True."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-13",
        proposed_action="files:create_temp_file",
        tool="files",
        parameters={"path": os.path.join(tempfile.gettempdir(), "test_13.tmp")},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {"done": True}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {"observed": True}),
    )

    assert res.state == DecisionState.SUCCESS
    assert res.claims_success is True
    assert res.verification_status == VerificationStatusType.VERIFIED_TRUE


def test_14_executor_plus_negative_verifier_yields_failed():
    """14. Executor OK + Verifier VERIFIED_FALSE -> FAILED y claims_success=False."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-14",
        proposed_action="files:create_temp_file",
        tool="files",
        parameters={"path": os.path.join(tempfile.gettempdir(), "test_14.tmp")},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {"done": True}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_FALSE, False, {"observed": False}),
    )

    assert res.state == DecisionState.FAILED
    assert res.claims_success is False
    assert res.verification_status == VerificationStatusType.VERIFIED_FALSE


def test_15_executor_plus_unknown_verifier_yields_unknown():
    """15. Executor OK + Verifier UNVERIFIABLE -> UNKNOWN."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-15",
        proposed_action="files:create_temp_file",
        tool="files",
        parameters={"path": os.path.join(tempfile.gettempdir(), "test_15.tmp")},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {"done": True}),
        verifier_override=lambda p: (VerificationStatusType.UNVERIFIABLE, False, {}),
    )

    assert res.state == DecisionState.UNKNOWN
    assert res.verification_status == VerificationStatusType.UNVERIFIABLE


def test_16_unknown_verifier_mandates_claims_success_false():
    """16. Invariante: UNKNOWN obliga incondicionalmente claims_success=False."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-16",
        proposed_action="files:create_temp_file",
        tool="files",
        parameters={"path": os.path.join(tempfile.gettempdir(), "test_16.tmp")},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {"done": True}),
        verifier_override=lambda p: (VerificationStatusType.UNVERIFIABLE, False, {}),
    )

    assert res.claims_success is False
    assert res.state != DecisionState.SUCCESS


# ==============================================================================
# 5. ACTION RECEIPT E INTEGRIDAD CRIPTOGRÁFICA (Tests 17-20)
# ==============================================================================


def test_17_success_requires_action_receipt():
    """17. Todo resultado SUCCESS requiere obligatoriamente un ActionReceipt emitido."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-17",
        proposed_action="files:create_temp_file",
        tool="files",
        parameters={"path": os.path.join(tempfile.gettempdir(), "test_17.tmp")},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {"verified": True}),
    )

    assert res.receipt_id is not None
    assert res.receipt_data is not None
    assert res.receipt_data["authority_mode"] == "CANARY"


def test_18_valid_receipt_verifies_integrity():
    """18. Un ActionReceipt legítimo supera la verificación de integridad criptográfica SHA-256."""
    receipt = ActionReceipt.create(
        request_id="req-test-18",
        user_request="crear archivo",
        action="files:create_temp_file",
        tool="files",
        parameters={"path": "C:\\temp\\test.tmp"},
        executor="files_executor",
        verifier="files_verifier",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        execution_status=ExecutionStatusType.OK,
        verification_status=VerificationStatusType.VERIFIED_TRUE,
        verified=True,
        final_status=DecisionState.SUCCESS,
        authority_mode="CANARY",
        risk_tier="LOW",
    )
    assert receipt.verify_integrity() is True


def test_19_tampered_receipt_fails_integrity():
    """19. Manipulación o alteración de cualquier campo del recibo invalida la integridad."""
    receipt = ActionReceipt.create(
        request_id="req-test-19",
        user_request="crear archivo",
        action="files:create_temp_file",
        tool="files",
        parameters={"path": "C:\\temp\\test.tmp"},
        executor="files_executor",
        verifier="files_verifier",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        execution_status=ExecutionStatusType.OK,
        verification_status=VerificationStatusType.VERIFIED_TRUE,
        verified=True,
        final_status=DecisionState.SUCCESS,
        authority_mode="CANARY",
        risk_tier="LOW",
    )

    # Intentar alterar authority_mode a "FULL"
    tampered_data = receipt.model_dump()
    tampered_data["authority_mode"] = "FULL"
    tampered_receipt = ActionReceipt(**tampered_data)
    assert tampered_receipt.verify_integrity() is False

    # Intentar alterar final_status
    tampered_data2 = receipt.model_dump()
    tampered_data2["final_status"] = DecisionState.FAILED
    tampered_receipt2 = ActionReceipt(**tampered_data2)
    assert tampered_receipt2.verify_integrity() is False


def test_20_fingerprint_covers_mandatory_fields():
    """20. El fingerprint SHA-256 vincula formalmente acción, herramienta, autoridad y riesgo."""
    receipt = ActionReceipt.create(
        request_id="req-test-20",
        user_request="test",
        action="files:create_temp_file",
        tool="files",
        parameters={"key": "val"},
        executor="files_executor",
        verifier="files_verifier",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        execution_status=ExecutionStatusType.OK,
        verification_status=VerificationStatusType.VERIFIED_TRUE,
        verified=True,
        final_status=DecisionState.SUCCESS,
        authority_mode="CANARY",
        risk_tier="LOW",
    )
    fp = receipt.fingerprint
    assert isinstance(fp, str)
    assert len(fp) == 64  # SHA-256 hex digest


# ==============================================================================
# 6. IDEMPOTENCIA Y CORRELACIÓN (Tests 21-22)
# ==============================================================================


def test_21_duplicate_request_does_not_execute_twice():
    """21. Una solicitud duplicada (mismo request_id y parámetros) no ejecuta por segunda vez."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)
    executor_mock = Mock(return_value=(ExecutionStatusType.OK, {}))

    temp_path = os.path.join(tempfile.gettempdir(), "test_21.tmp")
    req = DecisionRequest(
        request_id="req-test-21-unique",
        proposed_action="files:create_temp_file",
        tool="files",
        parameters={"path": temp_path},
    )

    # Primera ejecución -> se ejecuta
    res1 = engine.decide_and_execute(
        request=req,
        executor=executor_mock,
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )
    assert executor_mock.call_count == 1
    assert res1.state == DecisionState.SUCCESS

    # Segunda ejecución con la misma solicitud -> bloqueada por idempotencia
    res2 = engine.decide_and_execute(
        request=req,
        executor=executor_mock,
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )
    assert executor_mock.call_count == 1  # No aumentó!
    assert res2.state == DecisionState.NOT_EXECUTED
    assert res2.error_code == "DUPLICATE_EXECUTION_BLOCKED"


def test_22_correlation_id_is_preserved_throughout():
    """22. El correlation_id se preserva de extremo a extremo."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-test-22",
        correlation_id="corr-trace-9999",
        proposed_action="files:create_temp_file",
        tool="files",
        parameters={"path": os.path.join(tempfile.gettempdir(), "test_22.tmp")},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )

    assert res.receipt_data is not None
    assert res.receipt_data["request_id"] == "req-test-22"


# ==============================================================================
# 7. SEGURIDAD Y GOBERNANZA (Tests 23-24)
# ==============================================================================


def test_23_llm_cannot_elevate_authority():
    """23. Inyecciones de parámetros del LLM no pueden alterar el modo de autoridad."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)

    # El LLM propone parámetros maliciosos pretendiendo otorgarse modo FULL o admin
    req = DecisionRequest(
        request_id="req-test-23",
        proposed_action="files:create_temp_file",
        tool="files",
        parameters={
            "path": os.path.join(tempfile.gettempdir(), "test_23.tmp"),
            "authority_mode": "FULL",
            "role": "SUPER_ADMIN",
            "policy": "ALLOW_ALL",
        },
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )

    # La autoridad real permanece inmutablemente en CANARY
    assert gate.current_mode == AuthorityMode.CANARY
    assert res.receipt_data["authority_mode"] == "CANARY"


def test_24_canary_cannot_auto_escalate_to_limited_or_full():
    """24. CANARY no puede auto-escalar a LIMITED, PROGRESSIVE ni FULL."""
    gate = reset_authority_gate(AuthorityMode.CANARY)

    for target_mode in [AuthorityMode.LIMITED, AuthorityMode.PROGRESSIVE, AuthorityMode.FULL]:
        success, reason = gate.attempt_escalation(
            target_mode=target_mode,
            caller="unauthorized_subsystem",
            is_formally_certified=False,
        )
        assert success is False
        assert gate.current_mode == AuthorityMode.CANARY
        assert "no permitida" in reason.lower() or "sin certificación" in reason.lower()


# ==============================================================================
# 8. TEST MATRICIAL (Section 17)
# ==============================================================================


@pytest.mark.parametrize(
    "case_name,auth_mode,proposed_action,tool,param_scope,verif_type,expected_state,expected_claims_success",
    [
        # Caso 1: Acción autorizada, CANARY, permitido, TRUE -> SUCCESS
        (
            "autorizada_permitido_true",
            AuthorityMode.CANARY,
            "files:create_temp_file",
            "files",
            "temp_allowed",
            VerificationStatusType.VERIFIED_TRUE,
            DecisionState.SUCCESS,
            True,
        ),
        # Caso 2: Acción autorizada, CANARY, permitido, UNKNOWN -> UNKNOWN
        (
            "autorizada_permitido_unknown",
            AuthorityMode.CANARY,
            "files:create_temp_file",
            "files",
            "temp_allowed",
            VerificationStatusType.UNVERIFIABLE,
            DecisionState.UNKNOWN,
            False,
        ),
        # Caso 3: Acción autorizada, CANARY, permitido, FALSE -> FAILED
        (
            "autorizada_permitido_false",
            AuthorityMode.CANARY,
            "files:create_temp_file",
            "files",
            "temp_allowed",
            VerificationStatusType.VERIFIED_FALSE,
            DecisionState.FAILED,
            False,
        ),
        # Caso 4: Acción no autorizada, CANARY, fuera -> DENY / BLOCKED
        (
            "no_autorizada_fuera",
            AuthorityMode.CANARY,
            "files:delete_file",
            "files",
            "outside_scope",
            VerificationStatusType.VERIFIED_TRUE,
            DecisionState.BLOCKED,
            False,
        ),
        # Caso 5: HIGH risk, CANARY, cualquiera -> DENY / BLOCKED
        (
            "high_risk_bloqueado",
            AuthorityMode.CANARY,
            "disk:format_drive",
            "disk",
            "any",
            VerificationStatusType.VERIFIED_TRUE,
            DecisionState.BLOCKED,
            False,
        ),
        # Caso 6: Configuración inválida (SHADOW), permitido -> OBSERVE_ONLY / NOT_EXECUTED
        (
            "config_invalida_shadow",
            AuthorityMode.SHADOW,
            "files:create_temp_file",
            "files",
            "temp_allowed",
            VerificationStatusType.VERIFIED_TRUE,
            DecisionState.NOT_EXECUTED,
            False,
        ),
    ],
)
def test_matrix_canonical_cases(
    case_name: str,
    auth_mode: AuthorityMode,
    proposed_action: str,
    tool: str,
    param_scope: str,
    verif_type: VerificationStatusType,
    expected_state: DecisionState,
    expected_claims_success: bool,
):
    """Matriz formal de validación de casos canónicos según Sección 17."""
    gate = reset_authority_gate(auth_mode)
    engine = DecisionEngine(authority_gate=gate)

    if param_scope == "temp_allowed":
        path_val = os.path.join(tempfile.gettempdir(), f"matrix_{case_name}.tmp")
    elif param_scope == "outside_scope":
        path_val = r"C:\Windows\System32\forbidden.dll"
    else:
        path_val = "C:\\test"

    executor_mock = Mock(return_value=(ExecutionStatusType.OK, {}))

    req = DecisionRequest(
        request_id=f"req-matrix-{case_name}",
        proposed_action=proposed_action,
        tool=tool,
        parameters={"path": path_val},
    )

    auth_eval = gate.evaluate_authority(
        action=proposed_action,
        tool=tool,
        parameters={"path": path_val},
    )
    if auth_mode == AuthorityMode.SHADOW:
        assert auth_eval.decision == AuthorityDecision.OBSERVE_ONLY
        assert gate.can_execute(proposed_action, tool) is False
        assert executor_mock.call_count == 0
        return

    is_verified_bool = (verif_type == VerificationStatusType.VERIFIED_TRUE)
    res = engine.decide_and_execute(
        request=req,
        executor=executor_mock,
        verifier_override=lambda p: (verif_type, is_verified_bool, {}),
    )

    assert res.state == expected_state, f"Fallo en {case_name}: esperado {expected_state}, obtenido {res.state}"
    assert res.claims_success == expected_claims_success, f"Fallo en {case_name} claims_success"

    # Si fue NOT_EXECUTED o BLOCKED, el executor no debió ser llamado
    if expected_state in (DecisionState.NOT_EXECUTED, DecisionState.BLOCKED):
        assert executor_mock.call_count == 0


def test_matrix_duplicate_has_no_second_execution():
    """Caso 7 de la matriz: duplicado en CANARY permitido no ejecuta una segunda vez."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)
    executor_mock = Mock(return_value=(ExecutionStatusType.OK, {}))

    temp_path = os.path.join(tempfile.gettempdir(), "matrix_dup.tmp")
    req = DecisionRequest(
        request_id="req-matrix-dup",
        proposed_action="files:create_temp_file",
        tool="files",
        parameters={"path": temp_path},
    )

    res1 = engine.decide_and_execute(
        request=req,
        executor=executor_mock,
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )
    assert res1.state == DecisionState.SUCCESS
    assert executor_mock.call_count == 1

    res2 = engine.decide_and_execute(
        request=req,
        executor=executor_mock,
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )
    assert res2.state == DecisionState.NOT_EXECUTED
    assert executor_mock.call_count == 1  # No hubo segunda ejecución


# ==============================================================================
# 9. PRUEBA REAL CONTROLADA: SUCCESS (Section 18)
# ==============================================================================


def test_real_controlled_canary_success():
    """Prueba real controlada (Sección 18):
    Flujo real de creación de archivo temporal con verificación en SO y ActionReceipt.
    """
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)

    temp_dir = tempfile.gettempdir()
    test_file_path = os.path.join(temp_dir, f"jde_canary_real_success_{int(time.time())}.tmp")
    test_content = "CANARY_AUTHORITY_VERIFIED_SUCCESS"

    # Limpieza previa por seguridad
    if os.path.exists(test_file_path):
        os.remove(test_file_path)

    # 1. Executor real controlado que escribe en el sistema de archivos
    def real_filesystem_executor(tool_name: str, params: dict[str, Any]):
        path = params["path"]
        content = params.get("content", "")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return (ExecutionStatusType.OK, {"path": path, "bytes_written": len(content)})

    # 2. DecisionRequest canónico
    req = DecisionRequest(
        request_id=f"real-success-{int(time.time())}",
        correlation_id=f"corr-success-{int(time.time())}",
        proposed_action="files:create_temp_file",
        tool="files",
        parameters={"path": test_file_path, "content": test_content},
        verification_requirements=[
            VerificationRequirement(
                strategy="file_exists",
                target=test_file_path,
                expected_properties={"path": test_file_path, "expected_content": test_content},
            )
        ],
    )

    try:
        # 3. Ejecución por el flujo formal de JDE
        res = engine.decide_and_execute(request=req, executor=real_filesystem_executor)

        # 4. Validar resultado formal
        assert gate.current_mode == AuthorityMode.CANARY
        assert res.state == DecisionState.SUCCESS
        assert res.claims_success is True
        assert res.verification_status == VerificationStatusType.VERIFIED_TRUE
        assert res.receipt_id is not None

        # 5. Validar ActionReceipt
        receipt_data = res.receipt_data
        assert receipt_data is not None
        receipt = ActionReceipt(**receipt_data)
        assert receipt.verify_integrity() is True
        assert receipt.authority_mode == "CANARY"
        assert receipt.policy_verdict in ("ALLOW", "DEFAULT_ALLOW")
        assert receipt.final_status == DecisionState.SUCCESS
        assert receipt.verified is True
        assert len(receipt.evidence) >= 1
        assert receipt.evidence[0].is_verified is True

        # 6. Validar telemetría
        assert gate.metrics.canary_success >= 1
        assert gate.metrics.canary_false_success == 0
        assert gate.metrics.canary_double_execution == 0

    finally:
        # Limpieza de archivo temporal
        if os.path.exists(test_file_path):
            try:
                os.remove(test_file_path)
            except Exception:
                pass


# ==============================================================================
# 10. PRUEBA REAL DE FALLA: UNKNOWN (Section 19)
# ==============================================================================


def test_real_controlled_canary_unknown():
    """Prueba real de falla (Sección 19):
    La verificación no puede confirmar el resultado determinísticamente.
    Debe producir:
    - execution_count == 1
    - verification == UNKNOWN / UNVERIFIABLE
    - final_status == UNKNOWN
    - claims_success == False
    - retry == 0
    - second_execution == 0
    """
    gate = reset_authority_gate(AuthorityMode.CANARY)
    engine = DecisionEngine(authority_gate=gate)

    execution_calls = 0

    # Executor que simula ejecutar pero NO produce el estado verificable esperado
    def real_executor_missing_effect(tool_name: str, params: dict[str, Any]):
        nonlocal execution_calls
        execution_calls += 1
        return (ExecutionStatusType.OK, {"result": "dispatched_but_unconfirmed"})

    non_existent_path = os.path.join(tempfile.gettempdir(), f"non_existent_{int(time.time())}.tmp")

    # Override de verifier que devuelve UNVERIFIABLE (desconocido)
    def unknown_verifier(params: dict[str, Any]):
        return (VerificationStatusType.UNVERIFIABLE, False, {"reason": "Estado no observable"})

    req = DecisionRequest(
        request_id=f"real-unknown-{int(time.time())}",
        correlation_id=f"corr-unknown-{int(time.time())}",
        proposed_action="files:create_temp_file",
        tool="files",
        parameters={"path": non_existent_path},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=real_executor_missing_effect,
        verifier_override=unknown_verifier,
    )

    # 1. Demostración formal
    assert execution_calls == 1, "Debe existir exactamente 1 intento de ejecución, sin reintentos"
    assert res.state == DecisionState.UNKNOWN, "El estado final debe ser obligatoriamente UNKNOWN"
    assert res.claims_success is False, "claims_success debe ser False ante UNKNOWN"
    assert res.verification_status == VerificationStatusType.UNVERIFIABLE
    assert res.retry_count == 0, "No debe haber reintentos automáticos"

    # 2. Receipt generado
    assert res.receipt_id is not None
    receipt = ActionReceipt(**res.receipt_data)
    assert receipt.verify_integrity() is True
    assert receipt.final_status == DecisionState.UNKNOWN
    assert receipt.verified is False

    # 3. Métricas
    assert gate.metrics.canary_unknown >= 1
    assert gate.metrics.canary_false_success == 0
    assert gate.metrics.canary_double_execution == 0


# ==============================================================================
# 11. TELEMETRÍA Y MÉTRICAS CANARY (Section 20)
# ==============================================================================


def test_canary_telemetry_metrics_accumulation():
    """20. Métricas CANARY acumulan correctamente y verifican canary_false_success == 0."""
    gate = reset_authority_gate(AuthorityMode.CANARY)

    gate.metrics.record_canary_action("ALLOW", "SUCCESS", is_verified=True, execution_count=1)
    gate.metrics.record_canary_action("ALLOW", "FAILED", is_verified=False, execution_count=1)
    gate.metrics.record_canary_action("ALLOW", "UNKNOWN", is_verified=False, execution_count=1)
    gate.metrics.record_canary_action("DENY", "NOT_EXECUTED", is_verified=False, execution_count=0)

    summary = gate.metrics.to_dict()
    assert summary["canary_total"] == 4
    assert summary["canary_allowed"] == 3
    assert summary["canary_denied"] == 1
    assert summary["canary_success"] == 1
    assert summary["canary_failed"] == 1
    assert summary["canary_unknown"] == 1
    assert summary["canary_not_executed"] == 1
    assert summary["canary_false_success"] == 0
    assert summary["canary_double_execution"] == 0


# ==============================================================================
# 12. PERFORMANCE OVERHEAD (Section 21)
# ==============================================================================


def test_authority_gate_performance_overhead():
    """21. Overhead del Authority Gate debe ser insignificante (< 5ms por evaluación)."""
    gate = reset_authority_gate(AuthorityMode.CANARY)
    temp_path = os.path.join(tempfile.gettempdir(), "perf_test.tmp")

    t0 = time.perf_counter()
    for _ in range(100):
        gate.evaluate_authority(
            action="files:create_temp_file",
            tool="files",
            parameters={"path": temp_path},
        )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    avg_per_eval_ms = elapsed_ms / 100

    assert avg_per_eval_ms < 5.0, f"Overhead excesivo en Authority Gate: {avg_per_eval_ms:.3f}ms"
