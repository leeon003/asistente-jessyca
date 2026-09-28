"""Batería de Pruebas Formales de Certificación JDE Fase 8 — FULL AUTHORITY.

Cubre:
1. Jerarquía de Modos de Autoridad y Transiciones (OFF -> LAB -> SHADOW -> ADVISORY -> CONTROLLED -> FULL)
2. Invariante de Determinismo (misma entrada + mismo contexto -> misma decisión)
3. Contrato Formal de Decisión (DecisionContract) e Integridad SHA-256
4. Jerarquía de Resolución de Conflictos (SAFETY > AUTHORIZATION > POLICY > BUSINESS_RULE > OPTIMIZATION)
5. Casos Adversariales: Contradicción ("haz X y no hagas X") -> CONFLICT
6. Casos Adversariales: Ambigüedad ("haz eso") -> NO_DECISION
7. Fail-Safe: Desconocido ante incertidumbre (NUNCA inventar decisiones)
8. Invariante LLM: LLM propone, JDE decide (LLM no puede anular DENY ni REQUIRES_CONFIRMATION)
9. Integración con RiskEngine (Imposibilidad de bypass en HIGH / CRITICAL risk)
10. Integración con PermissionManager (Imposibilidad de bypass en DENY)
11. Idempotencia: Prevención de ejecuciones duplicadas en operaciones con side-effects
12. ExecutionVerifier: Falla de verificación -> UNKNOWN / FAILED (NUNCA SUCCESS)
13. Mecanismo de Emergencia: Kill Switch (JDE_KILL_SWITCH / trigger_kill_switch)
14. Rollback Inmediato y Seguro a modos inferiores
15. Replay Engine: Reconstrucción forense histórica idéntica desde ActionReceipt y DecisionContract
16. Ejecución E2E en FULL AUTHORITY con auditoría completa y redacción de secretos
"""

import os
import tempfile
from datetime import UTC, datetime
from typing import Any

import pytest

from core.execution.idempotency_guard import (
    ExecutionFingerprint,
    ExecutionIdempotencyGuard,
)
from core.jde.audit import JDEAuditTrail
from core.jde.authority import (
    ActionRiskTier,
    AuthorityDecision,
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
from core.jde.conflict import (
    ConflictResolutionResult,
    JDEConflictResolver,
)
from core.jde.contract import (
    DecisionContract,
    compute_contract_fingerprint,
)
from core.jde.engine import DecisionEngine
from core.jde.models import (
    DecisionRequest,
    DecisionResult,
    PolicyRequirement,
    VerificationRequirement,
)
from core.jde.policy import JDEPolicyDecision, JDEPolicyGate
from core.jde.receipts import ActionReceipt, JDEEvidence
from core.jde.replay import JDEReplayEngine, ReplayResult
from core.jde.states import (
    DecisionState,
    ExecutionStatusType,
    VerificationStatusType,
)


@pytest.fixture(autouse=True)
def setup_teardown_env():
    """Limpia el entorno antes y después de cada test."""
    os.environ.pop("JDE_AUTHORITY_MODE", None)
    os.environ.pop("JDE_KILL_SWITCH", None)
    reset_authority_gate(AuthorityMode.SHADOW)
    reset_capability_registry()
    yield
    os.environ.pop("JDE_AUTHORITY_MODE", None)
    os.environ.pop("JDE_KILL_SWITCH", None)
    reset_authority_gate(AuthorityMode.SHADOW)
    reset_capability_registry()


# ==============================================================================
# 1. MODOS DE AUTORIDAD Y ACTIVACIÓN AUDITABLE (Sección 22)
# ==============================================================================


def test_01_authority_modes_enum_completeness():
    """1. Todos los modos requeridos existen en AuthorityMode."""
    required = ["OFF", "LAB", "SHADOW", "ADVISORY", "CANARY", "LIMITED", "PROGRESSIVE", "CONTROLLED", "FULL"]
    for mode_name in required:
        assert mode_name in [m.value for m in AuthorityMode]


def test_02_default_at_rest_is_strictly_shadow():
    """2. Por defecto en reposo y ante entradas corruptas, el sistema permanece en SHADOW (Fail-Safe)."""
    gate = reset_authority_gate()
    assert gate.current_mode == AuthorityMode.SHADOW
    assert gate.is_shadow is True
    assert gate.is_full is False


def test_03_full_authority_activation_requires_explicit_formal_certification():
    """3. FULL Authority requiere flag explícita y no puede activarse por defecto."""
    # Sin allow_global_full_authority=True, forzar FULL cae en SHADOW
    gate = JDEAuthorityGate(mode=AuthorityMode.FULL, allow_global_full_authority=False)
    assert gate.current_mode == AuthorityMode.SHADOW

    # Con allow_global_full_authority=True, se activa
    gate_full = JDEAuthorityGate(mode=AuthorityMode.FULL, allow_global_full_authority=True)
    assert gate_full.current_mode == AuthorityMode.FULL
    assert gate_full.is_full is True


# ==============================================================================
# 2. DETERMINISMO (Sección 7)
# ==============================================================================


def test_04_determinism_same_input_same_context_same_decision():
    """4. Misma entrada + mismo contexto + mismas reglas -> misma decisión determinista."""
    gate = JDEAuthorityGate(mode=AuthorityMode.FULL, allow_global_full_authority=True)
    engine = DecisionEngine(authority_gate=gate)

    req1 = DecisionRequest(
        request_id="req-det-1",
        proposed_action="files.read",
        tool="files",
        parameters={"path": "D:/doc.txt"},
        risk_level="SAFE",
        verification_requirements=[VerificationRequirement(strategy="default", target="files.read")],
    )
    req2 = DecisionRequest(
        request_id="req-det-2",
        proposed_action="files.read",
        tool="files",
        parameters={"path": "D:/doc.txt"},
        risk_level="SAFE",
        verification_requirements=[VerificationRequirement(strategy="default", target="files.read")],
    )

    def dummy_exec(t: str, p: dict[str, Any]):
        return ExecutionStatusType.OK, {"read": True}

    def dummy_verif(p: dict[str, Any]):
        return VerificationStatusType.VERIFIED_TRUE, True, {"observed": True}

    res1 = engine.decide_and_execute(req1, dummy_exec, dummy_verif)
    res2 = engine.decide_and_execute(req2, dummy_exec, dummy_verif)

    assert res1.state == res2.state == DecisionState.SUCCESS
    assert res1.claims_success == res2.claims_success == True
    assert res1.executed_action == res2.executed_action


# ==============================================================================
# 3. CONTRATO FORMAL DE DECISIÓN (Sección 5)
# ==============================================================================


def test_05_decision_contract_structure_and_fingerprint_integrity():
    """5. DecisionContract almacena todos los campos requeridos y valida su hash SHA-256."""
    contract = DecisionContract.create(
        intent="read_document",
        selected_action="files.read",
        reason="Usuario solicitó leer documento seguro",
        context={"path": "D:/sample.txt"},
        candidate_actions=["files.read", "files.open"],
        policy="SAFE_POLICY",
        rules_evaluated=["ALLOW_SAFE_READS"],
        risk_level="SAFE",
        permission_status="ALLOW",
        idempotency_status="ACQUIRED",
        verification_requirement=["file_exists"],
        authority_level="FULL",
        decision_status=DecisionState.AUTHORIZED,
    )

    assert contract.selected_action == "files.read"
    assert contract.authority_level == "FULL"
    assert contract.decision_status == DecisionState.AUTHORIZED
    assert len(contract.fingerprint) == 64
    assert contract.verify_integrity() is True


def test_06_decision_contract_detects_tampering():
    """6. DecisionContract detecta cualquier alteración posterior en sus datos."""
    contract = DecisionContract.create(
        intent="delete_critical",
        selected_action="files.delete",
        reason="Eliminar archivo",
        risk_level="HIGH",
        permission_status="REQUIRE_CONFIRMATION",
        authority_level="FULL",
        decision_status=DecisionState.REQUIRES_CONFIRMATION,
    )
    assert contract.verify_integrity() is True

    # Manipulación de datos
    tampered_data = contract.model_dump()
    tampered_data["selected_action"] = "files.format_disk"
    tampered_contract = DecisionContract(**tampered_data)
    assert tampered_contract.verify_integrity() is False


# ==============================================================================
# 4. RESOLUCIÓN DE CONFLICTOS Y JERARQUÍA (Sección 8)
# ==============================================================================


def test_07_conflict_resolution_hierarchy_safety_overrides_all():
    """7. SAFETY (RiskEngine) prevalece sobre AUTHORIZATION, POLICY y OPTIMIZATION."""
    resolver = JDEConflictResolver()
    # RiskEngine marca HIGH/CRITICAL sin confirmación humana
    res = resolver.resolve(
        action="system.wipe",
        tool="system",
        risk_tier="CRITICAL",
        permission_decision="ALLOW",  # PermissionManager permitiría
        policy_allowed=True,          # Policy Gate permitiría
        user_confirmed=False,
    )
    assert res.is_allowed is False
    assert res.resolved_state == DecisionState.REQUIRES_CONFIRMATION
    assert res.overriding_layer == "SAFETY"


def test_08_conflict_resolution_hierarchy_authorization_overrides_policy():
    """8. AUTHORIZATION (PermissionManager) prevalece sobre POLICY."""
    resolver = JDEConflictResolver()
    res = resolver.resolve(
        action="network.scan",
        tool="network",
        risk_tier="SAFE",
        permission_decision="DENY",   # PermissionManager deniega
        policy_allowed=True,          # PolicyGate permitiría
        user_confirmed=True,
    )
    assert res.is_allowed is False
    assert res.resolved_state == DecisionState.BLOCKED
    assert res.overriding_layer == "AUTHORIZATION"


# ==============================================================================
# 5. CASOS ADVERSARIALES Y FAIL-SAFE (Secciones 9, 10, 17)
# ==============================================================================


def test_09_adversarial_contradictory_instructions_produces_conflict():
    """9. Instrucción contradictoria ('haz X y no hagas X') genera estado CONFLICT."""
    gate = JDEAuthorityGate(mode=AuthorityMode.FULL, allow_global_full_authority=True)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-contra-1",
        user_request="haz el respaldo y no hagas el respaldo",
        proposed_action="backup.create",
        tool="backup",
    )
    res = engine.decide_and_execute(req, lambda t, p: (ExecutionStatusType.OK, {}))
    assert res.state == DecisionState.CONFLICT
    assert res.claims_success is False
    assert "contradictoria" in res.message.lower()


def test_10_adversarial_ambiguous_prompt_produces_no_decision():
    """10. Ambigüedad extrema ('haz eso') genera NO_DECISION sin inventar acciones."""
    gate = JDEAuthorityGate(mode=AuthorityMode.FULL, allow_global_full_authority=True)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-ambig-1",
        user_request="haz eso",
        proposed_action="generic.action",
        tool="generic",
    )
    res = engine.decide_and_execute(req, lambda t, p: (ExecutionStatusType.OK, {}))
    assert res.state == DecisionState.NO_DECISION
    assert res.claims_success is False
    assert "ambigua" in res.message.lower()


def test_11_llm_cannot_override_jde_deny_or_confirmation():
    """11. LLM propone, JDE decide: LLM no puede anular bloqueos ni confirmaciones humanas."""
    gate = JDEAuthorityGate(mode=AuthorityMode.FULL, allow_global_full_authority=True)
    engine = DecisionEngine(authority_gate=gate)

    # Intento de bypass mediante prompt injection en parámetros
    req = DecisionRequest(
        request_id="req-inject-1",
        proposed_action="files.delete",
        tool="files",
        parameters={
            "path": "C:/Windows",
            "override_jde": True,
            "llm_verdict": "ALLOW_IMMEDIATE",
        },
        risk_level="HIGH",
        policy_requirements=PolicyRequirement(requires_human_confirmation=False),
    )
    res = engine.decide_and_execute(req, lambda t, p: (ExecutionStatusType.OK, {}))
    assert res.state in (DecisionState.BLOCKED, DecisionState.NOT_EXECUTED)
    assert res.claims_success is False


# ==============================================================================
# 6. IDEMPOTENCIA (Sección 13)
# ==============================================================================


def test_12_idempotency_prevents_duplicate_execution():
    """12. IdempotencyGuard impide que la misma solicitud con side-effects se ejecute dos veces."""
    guard = ExecutionIdempotencyGuard()
    gate = JDEAuthorityGate(mode=AuthorityMode.FULL, allow_global_full_authority=True)
    engine = DecisionEngine(authority_gate=gate, idempotency_guard=guard)

    execution_count = 0

    def counting_exec(t: str, p: dict[str, Any]):
        nonlocal execution_count
        execution_count += 1
        return ExecutionStatusType.OK, {"count": execution_count}

    def dummy_verif(p: dict[str, Any]):
        return VerificationStatusType.VERIFIED_TRUE, True, {}

    req = DecisionRequest(
        request_id="req-idem-1",
        proposed_action="messages.send",
        tool="messages",
        parameters={"target": "+123456789", "body": "Alerta"},
        verification_requirements=[VerificationRequirement(strategy="default", target="messages.send")],
    )

    res1 = engine.decide_and_execute(req, counting_exec, dummy_verif)
    assert res1.state == DecisionState.SUCCESS
    assert execution_count == 1

    # Segunda ejecución con el mismo request_id y target
    res2 = engine.decide_and_execute(req, counting_exec, dummy_verif)
    assert res2.state == DecisionState.NOT_EXECUTED
    assert "duplicada" in res2.message.lower()
    assert execution_count == 1  # No hubo segunda ejecución física


# ==============================================================================
# 7. EXECUTION VERIFIER (Sección 14)
# ==============================================================================


def test_13_verifier_failure_results_in_failed_not_success():
    """13. Si el ejecutor reporta OK pero el verificador falla -> FAILED o UNKNOWN (NUNCA SUCCESS)."""
    gate = JDEAuthorityGate(mode=AuthorityMode.FULL, allow_global_full_authority=True)
    engine = DecisionEngine(authority_gate=gate, max_retries=0)

    req = DecisionRequest(
        request_id="req-verif-fail",
        proposed_action="files.create",
        tool="files",
        parameters={"path": "D:/fail.txt"},
        verification_requirements=[VerificationRequirement(strategy="default", target="files.create")],
    )

    def ok_exec(t: str, p: dict[str, Any]):
        return ExecutionStatusType.OK, {"created": True}

    def failing_verif(p: dict[str, Any]):
        # El archivo físico NO se creó en el sistema de archivos
        return VerificationStatusType.VERIFIED_FALSE, False, {"file_found": False}

    res = engine.decide_and_execute(req, ok_exec, failing_verif)
    assert res.state == DecisionState.FAILED
    assert res.claims_success is False


# ==============================================================================
# 8. EMERGENCY KILL SWITCH (Sección 23)
# ==============================================================================


def test_14_kill_switch_triggers_immediate_fail_safe_to_shadow():
    """14. Kill Switch desescala inmediatamente la autoridad de FULL a SHADOW."""
    gate = JDEAuthorityGate(mode=AuthorityMode.FULL, allow_global_full_authority=True)
    assert gate.current_mode == AuthorityMode.FULL

    # Activación de emergencia
    gate.trigger_kill_switch(reason="Alerta de contención operacional")
    assert gate.is_kill_switch_active is True
    assert gate.current_mode == AuthorityMode.SHADOW
    assert gate.is_shadow is True

    # Las evaluaciones en Kill Switch responden OBSERVE_ONLY
    eval_res = gate.evaluate_authority("files.read", "files")
    assert eval_res.decision == AuthorityDecision.OBSERVE_ONLY
    assert eval_res.can_execute is False


def test_15_kill_switch_via_environment_variable():
    """15. Variable de entorno JDE_KILL_SWITCH=true fuerza SHADOW incondicionalmente."""
    os.environ["JDE_KILL_SWITCH"] = "true"
    gate = JDEAuthorityGate(mode=AuthorityMode.FULL, allow_global_full_authority=True)
    assert gate.is_kill_switch_active is True
    assert gate.current_mode == AuthorityMode.SHADOW


# ==============================================================================
# 9. ROLLBACK SEGURO (Sección 22)
# ==============================================================================


def test_16_rollback_authority_to_lower_modes():
    """16. Rollback revierte de forma controlada a modos inferiores (PROGRESSIVE, LIMITED, SHADOW)."""
    gate = JDEAuthorityGate(mode=AuthorityMode.FULL, allow_global_full_authority=True)
    assert gate.current_mode == AuthorityMode.FULL

    # Rollback a PROGRESSIVE
    ok, msg = gate.rollback_authority(AuthorityMode.PROGRESSIVE)
    assert ok is True
    assert gate.current_mode == AuthorityMode.PROGRESSIVE

    # Rollback a SHADOW
    ok, msg = gate.rollback_authority(AuthorityMode.SHADOW)
    assert ok is True
    assert gate.current_mode == AuthorityMode.SHADOW

    # Intento inválido de rollback hacia FULL es rechazado
    ok_invalid, msg_inv = gate.rollback_authority(AuthorityMode.FULL)
    assert ok_invalid is False


# ==============================================================================
# 10. REPLAY ENGINE (Sección 18)
# ==============================================================================


def test_17_replay_engine_reconstructs_historical_decision_deterministically():
    """17. JDEReplayEngine reconstruye fielmente la decisión histórica desde su recibo."""
    receipt = ActionReceipt.create(
        request_id="req-replay-1",
        user_request="leer reporte mensual",
        action="files.read",
        tool="files",
        parameters={"path": "D:/report.pdf"},
        executor="files_executor",
        verifier="jde_verifier",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        execution_status=ExecutionStatusType.OK,
        verification_status=VerificationStatusType.VERIFIED_TRUE,
        verified=True,
        final_status=DecisionState.SUCCESS,
        authority_mode="FULL",
        risk_tier="SAFE",
    )

    replay_engine = JDEReplayEngine()
    rep_res = replay_engine.replay_from_receipt(receipt)

    assert rep_res.is_consistent is True
    assert rep_res.original_state == DecisionState.SUCCESS
    assert rep_res.replayed_state == DecisionState.SUCCESS
    assert rep_res.fingerprint_valid is True


# ==============================================================================
# 11. END-TO-END FULL AUTHORITY TEST & AUDIT REDACTION (Secciones 19, 27)
# ==============================================================================


def test_18_end_to_end_full_authority_execution_and_secret_redaction():
    """18. Flujo E2E completo bajo FULL Authority con redacción estricta de credenciales en auditoría."""
    audit_trail = JDEAuditTrail()
    gate = JDEAuthorityGate(mode=AuthorityMode.FULL, allow_global_full_authority=True)
    engine = DecisionEngine(authority_gate=gate, audit_trail=audit_trail)

    req = DecisionRequest(
        request_id="req-e2e-full-1",
        user_request="actualizar configuracion con token",
        proposed_action="config.update",
        tool="config",
        parameters={
            "service": "api",
            "api_key": "SUPER_SECRET_TOKEN_XYZ_12345",
            "password": "my_master_password",
        },
        risk_level="SAFE",
        verification_requirements=[VerificationRequirement(strategy="default", target="config.update")],
    )

    def dummy_exec(t: str, p: dict[str, Any]):
        return ExecutionStatusType.OK, {"updated": True}

    def dummy_verif(p: dict[str, Any]):
        return VerificationStatusType.VERIFIED_TRUE, True, {"status": "ACTIVE"}

    res = engine.decide_and_execute(req, dummy_exec, dummy_verif)

    assert res.state == DecisionState.SUCCESS
    assert res.claims_success is True

    # Inspeccionar el recibo y auditoría generada
    records = audit_trail.get_records(request_id="req-e2e-full-1")
    assert len(records) == 1
    rec = records[0]

    # Verificar que los secretos NO fueron persistidos en texto claro
    receipt_dict = res.receipt_data
    assert receipt_dict["parameters"]["api_key"] == "***REDACTED_SECRET***"
    assert receipt_dict["parameters"]["password"] == "***REDACTED_SECRET***"
    assert "SUPER_SECRET_TOKEN_XYZ_12345" not in str(receipt_dict)
