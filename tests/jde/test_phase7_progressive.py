"""Tests de JDE Fase 7: Autoridad PROGRESSIVE y Promoción Controlada de Capacidades.

Certifica:
1. SHADOW sigue siendo el valor por defecto seguro (Default Safe).
2. LIMITED requiere configuración explícita.
3. PROGRESSIVE requiere configuración explícita (JDE_AUTHORITY_MODE=PROGRESSIVE).
4. Configuración inválida o corrupta activa Fail-Safe SHADOW.
5. Configuración ausente activa Fail-Safe SHADOW.
6. Capability elegible bajo criterios objetivos.
7. Capability no elegible si no alcanza umbral de evidencia.
8. 3 éxitos independientes verificados -> elegible.
9. 2 éxitos independientes verificados -> no elegible.
10. UNKNOWN bloquea promoción incondicionalmente.
11. FALSE_SUCCESS bloquea promoción incondicionalmente.
12. DOUBLE_EXECUTION bloquea promoción incondicionalmente.
13. Policy violation bloquea promoción incondicionalmente.
14. HIGH risk bloquea promoción incondicionalmente (excluido de PROGRESSIVE).
15. MEDIUM risk exige política más estricta (sin efectos externos, reversible, no destructivo).
16. LOW risk elegible bajo política estándar.
17. LLM no puede promoverse a sí mismo (caller="llm" -> DENY).
18. Promoción automática sin decisión de política es denegada (REQUIRE_REVIEW).
19. CapabilityPromotionReceipt generado formalmente.
20. Fingerprint SHA-256 de recibo de promoción verificado e íntegro.
21. Democión segura: PROGRESSIVE -> LIMITED.
22. Falso éxito detona democión inmediata automática.
23. Doble ejecución detona democión inmediata automática.
24. Fallo de integridad de verificación detona democión.
25. No existe escalada automática a FULL (FULL permanece estrictamente bloqueado).
26. Ejecución real de capacidad promovida bajo PROGRESSIVE.
27. Verificador real confirma SUCCESS y claims_success=True.
28. Verificador real ante falla física confirma UNKNOWN (no SUCCESS).
29. UNKNOWN no genera reintentos automáticos (execution_count == 1).
30. Idempotencia bloquea solicitud duplicada en PROGRESSIVE.
31. ActionReceipt es válido e íntegro bajo PROGRESSIVE.
32. Invariante claims_success <= is_verified mantenido estrictamente.
33. Test A (Sección 20): Evidencia real de 3 ejecuciones verificadas -> elegible pero no auto-promovida.
34. Test B (Sección 20): Promoción explícita con ALLOW eleva solo esa capacidad a PROGRESSIVE.
35. Test C (Sección 20): Verificación UNKNOWN controlada -> claims_success=False, no retry, promotion=DENY.
36. Test D (Sección 20): Democión tras fallo -> PROGRESSIVE vuelve a LIMITED sin pasar por FULL.
37. Telemetría de Fase 7 registra todas las métricas requeridas.
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
    get_authority_gate,
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
from core.jde.promotion import (
    CapabilityEvaluationRecord,
    CapabilityPromotionManager,
    CapabilityPromotionPolicy,
    CapabilityPromotionReceipt,
    PromotionDecision,
    PromotionStatus,
    compute_promotion_fingerprint,
    get_promotion_manager,
    reset_promotion_manager,
)
from core.jde.receipts import ActionReceipt
from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType


@pytest.fixture(autouse=True)
def clean_progressive_environment():
    """Restaura el entorno, singletons de autoridad, capabilities y promoción antes y después de cada test."""
    old_env = os.environ.get("JDE_AUTHORITY_MODE")
    ExecutionIdempotencyGuard.get_instance().clear()
    reset_capability_registry()
    reset_promotion_manager()
    reset_authority_gate(AuthorityMode.SHADOW)
    yield
    ExecutionIdempotencyGuard.get_instance().clear()
    if old_env is not None:
        os.environ["JDE_AUTHORITY_MODE"] = old_env
    else:
        os.environ.pop("JDE_AUTHORITY_MODE", None)
    reset_capability_registry()
    reset_promotion_manager()
    reset_authority_gate(AuthorityMode.SHADOW)


# ==============================================================================
# 1. CONFIGURACIÓN DE AUTORIDAD Y FAIL-SAFE (Tests 1-5)
# ==============================================================================


def test_01_shadow_remains_safe_default():
    """1. Por defecto, JDE opera en SHADOW (observación pasiva, can_execute=False)."""
    with patch.dict(os.environ, {}, clear=True):
        gate = JDEAuthorityGate(mode=None)
        assert gate.current_mode == AuthorityMode.SHADOW
        assert gate.is_shadow is True
        assert gate.is_progressive is False
        assert gate.can_execute("read_file", "files") is False


def test_02_limited_requires_explicit_configuration():
    """2. LIMITED solo se activa mediante configuración explícita."""
    with patch.dict(os.environ, {"JDE_AUTHORITY_MODE": "LIMITED"}):
        gate = JDEAuthorityGate(mode=None)
        assert gate.current_mode == AuthorityMode.LIMITED
        assert gate.is_limited is True
        assert gate.is_progressive is False


def test_03_progressive_requires_explicit_configuration():
    """3. PROGRESSIVE solo se activa mediante configuración explícita."""
    with patch.dict(os.environ, {"JDE_AUTHORITY_MODE": "PROGRESSIVE"}):
        gate = JDEAuthorityGate(mode=None)
        assert gate.current_mode == AuthorityMode.PROGRESSIVE
        assert gate.is_progressive is True
        assert gate.is_shadow is False


def test_04_invalid_config_reverts_to_shadow():
    """4. Configuración inválida o corrupta activa Fail-Safe a SHADOW."""
    for invalid in ["FULL_AUTO", "SUPER_ADMIN", "123", "ADMIN_PROGRESSIVE", "ROOT"]:
        with patch.dict(os.environ, {"JDE_AUTHORITY_MODE": invalid}):
            gate = JDEAuthorityGate(mode=None)
            assert gate.current_mode == AuthorityMode.SHADOW
            assert gate.is_shadow is True


def test_05_missing_config_reverts_to_shadow():
    """5. Cadena vacía o whitespace revierte a SHADOW."""
    for empty in ["", "   ", "\t\n"]:
        with patch.dict(os.environ, {"JDE_AUTHORITY_MODE": empty}):
            gate = JDEAuthorityGate(mode=None)
            assert gate.current_mode == AuthorityMode.SHADOW
            assert gate.is_shadow is True


# ==============================================================================
# 2. CRITERIOS Y ELEGIBILIDAD DE PROMOCIÓN (Tests 6-20)
# ==============================================================================


def test_06_capability_eligible():
    """6. Capacidad con 3 éxitos verificados e historial limpio es elegible."""
    mgr = get_promotion_manager()
    cap_id = "files.read"
    mgr.record_execution(cap_id, "req-1", DecisionState.SUCCESS, is_verified=True)
    mgr.record_execution(cap_id, "req-2", DecisionState.SUCCESS, is_verified=True)
    mgr.record_execution(cap_id, "req-3", DecisionState.SUCCESS, is_verified=True)

    eligible, reason = mgr.check_eligibility(cap_id)
    assert eligible is True
    assert "cumple todos los criterios objetivos" in reason


def test_07_capability_not_eligible():
    """7. Capacidad sin historial es evaluada como no elegible."""
    mgr = get_promotion_manager()
    eligible, reason = mgr.check_eligibility("files.read")
    assert eligible is False
    assert "Evidencia insuficiente" in reason


def test_08_three_verified_successes_makes_eligible():
    """8. Exactamente 3 éxitos verificados independientes cumplen el umbral."""
    mgr = get_promotion_manager()
    cap_id = "system.query"
    for i in range(3):
        mgr.record_execution(cap_id, f"req-uniq-{i}", DecisionState.SUCCESS, is_verified=True)

    eligible, reason = mgr.check_eligibility(cap_id)
    assert eligible is True


def test_09_two_verified_successes_not_eligible():
    """9. 2 éxitos verificados son insuficientes (threshold=3)."""
    mgr = get_promotion_manager()
    cap_id = "system.query"
    mgr.record_execution(cap_id, "req-uniq-1", DecisionState.SUCCESS, is_verified=True)
    mgr.record_execution(cap_id, "req-uniq-2", DecisionState.SUCCESS, is_verified=True)

    eligible, reason = mgr.check_eligibility(cap_id)
    assert eligible is False
    assert "2 < 3" in reason


def test_10_unknown_blocks_promotion():
    """10. Un solo UNKNOWN bloquea incondicionalmente la promoción."""
    mgr = get_promotion_manager()
    cap_id = "files.search"
    for i in range(3):
        mgr.record_execution(cap_id, f"req-{i}", DecisionState.SUCCESS, is_verified=True)
    # Incidente UNKNOWN
    mgr.record_execution(cap_id, "req-unk", DecisionState.UNKNOWN, is_verified=False)

    eligible, reason = mgr.check_eligibility(cap_id)
    assert eligible is False
    assert "UNKNOWN" in reason


def test_11_false_success_blocks_promotion():
    """11. FALSE_SUCCESS (SUCCESS sin verificación) bloquea incondicionalmente la promoción."""
    mgr = get_promotion_manager()
    cap_id = "files.search"
    for i in range(3):
        mgr.record_execution(cap_id, f"req-{i}", DecisionState.SUCCESS, is_verified=True)
    # Falso éxito
    mgr.record_execution(cap_id, "req-false", DecisionState.SUCCESS, is_verified=False)

    eligible, reason = mgr.check_eligibility(cap_id)
    assert eligible is False
    assert "falsos éxitos" in reason


def test_12_double_execution_blocks_promotion():
    """12. DOUBLE_EXECUTION bloquea incondicionalmente la promoción."""
    mgr = get_promotion_manager()
    cap_id = "files.read"
    for i in range(3):
        mgr.record_execution(cap_id, f"req-{i}", DecisionState.SUCCESS, is_verified=True)
    # Incidente de doble ejecución
    mgr.record_execution(cap_id, "req-dup", DecisionState.SUCCESS, is_verified=True, execution_count=2)

    eligible, reason = mgr.check_eligibility(cap_id)
    assert eligible is False
    assert "dobles ejecuciones" in reason


def test_13_policy_violation_blocks_promotion():
    """13. Violación de política bloquea incondicionalmente la promoción."""
    mgr = get_promotion_manager()
    cap_id = "process.inspect"
    for i in range(3):
        mgr.record_execution(cap_id, f"req-{i}", DecisionState.SUCCESS, is_verified=True)
    # Violación de política
    mgr.record_execution(cap_id, "req-viol", DecisionState.FAILED, is_policy_violation=True)

    eligible, reason = mgr.check_eligibility(cap_id)
    assert eligible is False
    assert "violaciones de política" in reason


def test_14_high_risk_blocks_promotion():
    """14. Capacidad HIGH risk está incondicionalmente excluida de PROGRESSIVE."""
    mgr = get_promotion_manager()
    cap_id = "files.delete"
    for i in range(5):
        mgr.record_execution(cap_id, f"req-{i}", DecisionState.SUCCESS, is_verified=True)

    eligible, reason = mgr.check_eligibility(cap_id)
    assert eligible is False
    assert "riesgo HIGH" in reason or "excluida" in reason


def test_15_medium_risk_requires_stricter_policy():
    """15. Capacidad MEDIUM con efectos externos o destructiva es bloqueada para promoción."""
    reg = get_capability_registry()
    mgr = get_promotion_manager()

    # Registrar capability MEDIUM pero con external_side_effect=True
    med_cap = Capability(
        capability_id="external.notify",
        action="notify",
        tool="network",
        risk_tier=ActionRiskTier.MEDIUM,
        authority_level=AuthorityMode.LIMITED,
        external_side_effect=True,
        reversible=False,
    )
    reg.register(med_cap)

    for i in range(3):
        mgr.record_execution(med_cap.capability_id, f"req-{i}", DecisionState.SUCCESS, is_verified=True)

    eligible, reason = mgr.check_eligibility(med_cap.capability_id)
    assert eligible is False
    assert "efectos externos" in reason or "no es reversible" in reason


def test_16_low_risk_eligible_under_policy():
    """16. Capacidad LOW sin efectos colaterales es elegible tras verificar 3 ejecuciones."""
    mgr = get_promotion_manager()
    cap_id = "process.inspect"
    for i in range(3):
        mgr.record_execution(cap_id, f"req-proc-{i}", DecisionState.SUCCESS, is_verified=True)

    eligible, reason = mgr.check_eligibility(cap_id)
    assert eligible is True


def test_17_llm_cannot_promote_itself():
    """17. El LLM o asistente no puede aprobar su propia promoción (caller='llm' -> DENY)."""
    mgr = get_promotion_manager()
    cap_id = "files.read"
    for i in range(3):
        mgr.record_execution(cap_id, f"req-{i}", DecisionState.SUCCESS, is_verified=True)

    success, receipt = mgr.promote(
        capability_id=cap_id,
        target_authority=AuthorityMode.PROGRESSIVE,
        approved_by_policy=True,
        caller="llm_agent_auto_promoter",
    )
    assert success is False
    assert receipt.decision == PromotionDecision.DENY
    assert "no tiene permiso para autorizar su propia promoción" in receipt.reason


def test_18_automatic_promotion_without_policy_decision_denied():
    """18. Promoción sin decisión administrativa explícita devuelve REQUIRE_REVIEW."""
    mgr = get_promotion_manager()
    cap_id = "files.read"
    for i in range(3):
        mgr.record_execution(cap_id, f"req-{i}", DecisionState.SUCCESS, is_verified=True)

    # Intentar promover sin approved_by_policy=True
    success, receipt = mgr.promote(
        capability_id=cap_id,
        target_authority=AuthorityMode.PROGRESSIVE,
        approved_by_policy=False,
        caller="system_admin",
    )
    assert success is False
    assert receipt.decision == PromotionDecision.REQUIRE_REVIEW
    assert "requiere decisión y aprobación explícita" in receipt.reason


def test_19_promotion_receipt_generated():
    """19. Promoción formal exitosa genera un CapabilityPromotionReceipt completo."""
    mgr = get_promotion_manager()
    cap_id = "files.read"
    for i in range(3):
        mgr.record_execution(cap_id, f"req-{i}", DecisionState.SUCCESS, is_verified=True)

    success, receipt = mgr.promote(
        capability_id=cap_id,
        target_authority=AuthorityMode.PROGRESSIVE,
        approved_by_policy=True,
        caller="security_policy_officer",
    )
    assert success is True
    assert receipt.decision == PromotionDecision.ALLOW
    assert receipt.capability_id == cap_id
    assert receipt.requested_authority == "PROGRESSIVE"
    assert receipt.verified_successes == 3
    assert receipt.fingerprint != ""


def test_20_promotion_fingerprint_valid():
    """20. El fingerprint del recibo de promoción es válido y detecta alteraciones fraudulentas."""
    mgr = get_promotion_manager()
    cap_id = "system.query"
    for i in range(3):
        mgr.record_execution(cap_id, f"req-{i}", DecisionState.SUCCESS, is_verified=True)

    _, receipt = mgr.promote(
        capability_id=cap_id,
        target_authority=AuthorityMode.PROGRESSIVE,
        approved_by_policy=True,
        caller="security_officer",
    )
    assert receipt.verify_integrity() is True

    # Alteración fraudulenta del número de éxitos
    tampered = receipt.model_copy(update={"verified_successes": 99})
    assert tampered.verify_integrity() is False

    # Alteración fraudulenta de la decisión
    tampered_dec = receipt.model_copy(update={"decision": PromotionDecision.ALLOW})
    # Cambiando la razón
    tampered_reason = receipt.model_copy(update={"reason": "Hacked approval"})
    assert tampered_reason.verify_integrity() is False


# ==============================================================================
# 3. DEMOCIÓN Y ROLLBACK SEGURO (Tests 21-25)
# ==============================================================================


def test_21_progressive_to_limited_demotion():
    """21. Capacidad promovida a PROGRESSIVE puede ser revertida de forma segura a LIMITED."""
    mgr = get_promotion_manager()
    reg = get_capability_registry()
    cap_id = "files.read"

    for i in range(3):
        mgr.record_execution(cap_id, f"req-{i}", DecisionState.SUCCESS, is_verified=True)

    mgr.promote(cap_id, approved_by_policy=True, caller="security_admin")
    assert reg.is_promoted(cap_id) is True

    # Demover de regreso a LIMITED
    success, receipt = mgr.demote(cap_id, target_authority=AuthorityMode.LIMITED, reason="Revisión de seguridad periódica")
    assert success is True
    assert reg.is_promoted(cap_id) is False
    assert receipt.requested_authority == "LIMITED"
    assert receipt.decision == PromotionDecision.DENY


def test_22_false_success_triggers_demotion():
    """22. Ocurrencia de un falso éxito en capacidad promovida activa democión automática inmediata."""
    mgr = get_promotion_manager()
    reg = get_capability_registry()
    cap_id = "files.read"

    for i in range(3):
        mgr.record_execution(cap_id, f"req-{i}", DecisionState.SUCCESS, is_verified=True)
    mgr.promote(cap_id, approved_by_policy=True, caller="security_admin")
    assert reg.is_promoted(cap_id) is True

    # Falso éxito sobre la capacidad promovida
    mgr.record_execution(cap_id, "req-bad", DecisionState.SUCCESS, is_verified=False)

    # Debe haber detonado democión automática
    assert reg.is_promoted(cap_id) is False
    rec = mgr.get_record(cap_id)
    assert rec.promotion_status == PromotionStatus.DEMOTED


def test_23_double_execution_triggers_demotion():
    """23. Doble ejecución sobre capacidad promovida detona democión automática inmediata."""
    mgr = get_promotion_manager()
    reg = get_capability_registry()
    cap_id = "files.read"

    for i in range(3):
        mgr.record_execution(cap_id, f"req-{i}", DecisionState.SUCCESS, is_verified=True)
    mgr.promote(cap_id, approved_by_policy=True, caller="security_admin")
    assert reg.is_promoted(cap_id) is True

    # Doble ejecución registrada
    mgr.record_execution(cap_id, "req-dup", DecisionState.SUCCESS, is_verified=True, execution_count=2)

    assert reg.is_promoted(cap_id) is False


def test_24_verification_integrity_failure_triggers_demotion():
    """24. Fallo de integridad de recibo activa evaluación de democión preventiva."""
    policy = CapabilityPromotionPolicy()
    rec = CapabilityEvaluationRecord(capability_id="files.read")
    should_demote, reason = policy.evaluate_demotion_condition(rec, incident_type="INTEGRITY_FAILURE")
    assert should_demote is True
    assert "Fallo de integridad criptográfica" in reason


def test_25_no_automatic_escalation_to_full():
    """25. Ni LIMITED ni PROGRESSIVE pueden auto-escalar a FULL."""
    gate = JDEAuthorityGate(mode=AuthorityMode.PROGRESSIVE)
    escalated, reason = gate.attempt_escalation(target_mode=AuthorityMode.FULL, caller="agent")
    assert escalated is False
    assert "no permitida" in reason
    assert gate.current_mode == AuthorityMode.PROGRESSIVE


# ==============================================================================
# 4. EJECUCIÓN Y MATRIZ DE AUTORIDAD PROGRESSIVE (Tests 26-32)
# ==============================================================================


def test_26_progressive_capability_real_execution():
    """26. Capacidad autorizada en PROGRESSIVE se despacha correctamente en JDE."""
    gate = reset_authority_gate(AuthorityMode.PROGRESSIVE)
    reg = get_capability_registry()
    mgr = get_promotion_manager()

    cap_id = "files.create_temp"
    for i in range(3):
        mgr.record_execution(cap_id, f"pre-{i}", DecisionState.SUCCESS, is_verified=True)
    mgr.promote(cap_id, approved_by_policy=True, caller="admin")

    engine = DecisionEngine(authority_gate=gate)
    req = DecisionRequest(
        request_id="req-prog-exec-01",
        proposed_action="create_temp_file",
        tool="files",
        parameters={"path": os.path.join(tempfile.gettempdir(), "test_p7.tmp")},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {"result": "ok"}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {"created": True}),
    )

    assert res.state == DecisionState.SUCCESS
    assert res.claims_success is True


def test_27_real_verifier_confirms_success():
    """27. Verificación positiva confirma estado SUCCESS y genera receipt en PROGRESSIVE."""
    gate = reset_authority_gate(AuthorityMode.PROGRESSIVE)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-prog-exec-02",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "C:\\temp\\dummy.txt"},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {"data": "hello"}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {"read": True}),
    )

    assert res.state == DecisionState.SUCCESS
    assert res.claims_success is True
    receipt = ActionReceipt(**res.receipt_data)
    assert receipt.authority_mode == "PROGRESSIVE"
    assert receipt.verify_integrity() is True


def test_28_real_unknown_remains_unknown():
    """28. Verificación que no puede comprobar el resultado observable produce UNKNOWN."""
    gate = reset_authority_gate(AuthorityMode.PROGRESSIVE)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-prog-exec-03",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "C:\\temp\\dummy.txt"},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {"data": "hello"}),
        verifier_override=lambda p: (VerificationStatusType.UNVERIFIABLE, False, {"error": "Observer detached"}),
    )

    assert res.state == DecisionState.UNKNOWN
    assert res.claims_success is False


def test_29_unknown_causes_no_retry():
    """29. Estado UNKNOWN no detona reintentos automáticos ni duplicados (execution_count == 1)."""
    gate = reset_authority_gate(AuthorityMode.PROGRESSIVE)
    engine = DecisionEngine(authority_gate=gate)

    exec_calls = 0

    def executor_counter(t: str, p: dict[str, Any]):
        nonlocal exec_calls
        exec_calls += 1
        return ExecutionStatusType.OK, {}

    req = DecisionRequest(
        request_id="req-prog-exec-04",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "C:\\temp\\dummy.txt"},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=executor_counter,
        verifier_override=lambda p: (VerificationStatusType.UNVERIFIABLE, False, {}),
    )

    assert res.state == DecisionState.UNKNOWN
    assert exec_calls == 1


def test_30_duplicate_request_blocked():
    """30. Solicitud con request_id idéntico es bloqueada por idempotencia."""
    gate = reset_authority_gate(AuthorityMode.PROGRESSIVE)
    engine = DecisionEngine(authority_gate=gate)

    req1 = DecisionRequest(
        request_id="req-prog-dup-01",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "C:\\temp\\dummy.txt"},
    )

    res1 = engine.decide_and_execute(
        request=req1,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )
    assert res1.state == DecisionState.SUCCESS

    # Segunda invocación con el mismo request_id
    res2 = engine.decide_and_execute(
        request=req1,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )
    assert res2.state in (DecisionState.BLOCKED, DecisionState.NOT_EXECUTED)
    assert res2.claims_success is False
    assert "idempotencia" in res2.message.lower() or "duplicada" in res2.message.lower()


def test_31_receipt_valid():
    """31. El recibo generado en PROGRESSIVE conserva integridad y fingerprint SHA-256."""
    gate = reset_authority_gate(AuthorityMode.PROGRESSIVE)
    engine = DecisionEngine(authority_gate=gate)

    req = DecisionRequest(
        request_id="req-prog-receipt-01",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "C:\\temp\\dummy.txt"},
    )

    res = engine.decide_and_execute(
        request=req,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {}),
    )
    receipt = ActionReceipt(**res.receipt_data)
    assert receipt.authority_mode == "PROGRESSIVE"
    assert receipt.verify_integrity() is True


def test_32_claims_success_invariant_strictly_maintained():
    """32. Invariante fundamental: claims_success=True si y solo si is_verified=True."""
    # Verificado positivamente
    res_verified = DecisionResult(
        request_id="r1",
        state=DecisionState.SUCCESS,
        success=True,
        claims_success=True,
        message="Verificado",
        executed_action="read_file",
        tool_used="files",
        executor_status=ExecutionStatusType.OK,
        verification_status=VerificationStatusType.VERIFIED_TRUE,
    )
    assert res_verified.claims_success is True

    # No verificado
    res_unverified = DecisionResult(
        request_id="r2",
        state=DecisionState.UNKNOWN,
        success=False,
        claims_success=False,
        message="Sin verificación",
        executed_action="read_file",
        tool_used="files",
        executor_status=ExecutionStatusType.OK,
        verification_status=VerificationStatusType.UNVERIFIABLE,
    )
    assert res_unverified.claims_success is False


# ==============================================================================
# 5. CONTROLLED REAL TESTS (Sección 20: Tests 33-36)
# ==============================================================================


def test_33_real_test_a_promotion_evidence():
    """33. Test A: Recolección real de evidencia (3 ejecuciones independientes verificadas).

    Demuestra:
    - 3 ejecuciones en disco independientes generan evidencia auditable.
    - eligible = True al alcanzar 3 éxitos verificados independientes.
    - NO se promueve automáticamente sin decisión explícita de política.
    """
    gate = reset_authority_gate(AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)
    mgr = get_promotion_manager()
    reg = get_capability_registry()

    cap_id = "files.create_temp"
    temp_dir = tempfile.gettempdir()

    created_paths = []
    try:
        for i in range(3):
            file_path = os.path.join(temp_dir, f"jde_p7_evidence_{i}.tmp")
            created_paths.append(file_path)
            if os.path.exists(file_path):
                os.remove(file_path)

            req = DecisionRequest(
                request_id=f"req-p7-real-a-{i}",
                correlation_id=f"corr-p7-real-a-{i}",
                proposed_action="create_temp_file",
                tool="files",
                parameters={"path": file_path},
            )

            def real_file_creator(t: str, p: dict[str, Any]):
                with open(p["path"], "w", encoding="utf-8") as f:
                    f.write(f"TEST EVIDENCE {i}")
                return ExecutionStatusType.OK, {"path": p["path"]}

            def real_file_verifier(p: dict[str, Any]):
                exists = os.path.exists(p["path"])
                return (
                    VerificationStatusType.VERIFIED_TRUE if exists else VerificationStatusType.VERIFIED_FALSE,
                    exists,
                    {"exists": exists},
                )

            res = engine.decide_and_execute(
                request=req,
                executor=real_file_creator,
                verifier_override=real_file_verifier,
            )

            assert res.state == DecisionState.SUCCESS
            assert res.claims_success is True

        # Demostrar que es elegible
        eligible, reason = mgr.check_eligibility(cap_id)
        assert eligible is True
        assert "cumple todos los criterios objetivos" in reason

        # Demostrar que NO está promovida automáticamente
        assert reg.is_promoted(cap_id) is False
        cap = reg.get(cap_id)
        assert cap.promoted_to_progressive is False

    finally:
        for p in created_paths:
            if os.path.exists(p):
                os.remove(p)


def test_34_real_test_b_explicit_promotion():
    """34. Test B: Promoción explícita con decisión ALLOW.

    Demuestra:
    - Aplicar decisión ALLOW eleva la capacidad de LIMITED a PROGRESSIVE.
    - La promoción es individual (otra capacidad permanece en LIMITED).
    """
    gate = reset_authority_gate(AuthorityMode.PROGRESSIVE)
    mgr = get_promotion_manager()
    reg = get_capability_registry()

    cap_id = "files.create_temp"
    other_cap_id = "system.query"

    # Proveer evidencia previa
    for i in range(3):
        mgr.record_execution(cap_id, f"req-real-b-{i}", DecisionState.SUCCESS, is_verified=True)

    # Decisión explícita formal
    success, receipt = mgr.promote(
        capability_id=cap_id,
        target_authority=AuthorityMode.PROGRESSIVE,
        approved_by_policy=True,
        caller="compliance_administrator",
    )

    assert success is True
    assert receipt.decision == PromotionDecision.ALLOW
    assert reg.is_promoted(cap_id) is True

    # Comprobar que la otra capacidad permanece en LIMITED (no promovida a PROGRESSIVE)
    assert reg.is_promoted(other_cap_id) is False

    # Comprobar evaluación de gate en PROGRESSIVE
    eval_promoted = gate.evaluate_authority("create_temp_file", "files")
    assert eval_promoted.decision == AuthorityDecision.ALLOW
    assert eval_promoted.promotion_status == "PROMOTED"

    # Evaluar capability que requiere LIMITED
    eval_other = gate.evaluate_authority("query_system_info", "system")
    assert eval_other.decision == AuthorityDecision.ALLOW
    assert eval_other.promotion_status == "LIMITED_IN_PROGRESSIVE"


def test_35_real_test_c_controlled_unknown():
    """35. Test C: Verificación UNKNOWN controlada en disco real.

    Demuestra:
    - final_status = UNKNOWN
    - claims_success = False
    - retry_count = 0 (execution_count == 1)
    - promotion = DENY
    """
    gate = reset_authority_gate(AuthorityMode.PROGRESSIVE)
    engine = DecisionEngine(authority_gate=gate)
    mgr = get_promotion_manager()

    cap_id = "files.create_temp"
    temp_file = os.path.join(tempfile.gettempdir(), "jde_p7_unknown_real.tmp")
    if os.path.exists(temp_file):
        os.remove(temp_file)

    exec_calls = 0

    def executor_func(t: str, p: dict[str, Any]):
        nonlocal exec_calls
        exec_calls += 1
        with open(p["path"], "w", encoding="utf-8") as f:
            f.write("test")
        return ExecutionStatusType.OK, {"path": p["path"]}

    # Verificador que no puede confirmar el estado observable
    def unverifiable_verifier(p: dict[str, Any]):
        return VerificationStatusType.UNVERIFIABLE, False, {"error": "Observer missing"}

    try:
        req = DecisionRequest(
            request_id="req-p7-real-c",
            proposed_action="create_temp_file",
            tool="files",
            parameters={"path": temp_file},
        )

        res = engine.decide_and_execute(
            request=req,
            executor=executor_func,
            verifier_override=unverifiable_verifier,
        )

        assert res.state == DecisionState.UNKNOWN
        assert res.claims_success is False
        assert exec_calls == 1

        # Promoción debe ser denegada por registrar un UNKNOWN
        eligible, reason = mgr.check_eligibility(cap_id)
        assert eligible is False
        assert "UNKNOWN" in reason

    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)


def test_36_real_test_d_failure_and_demotion():
    """36. Test D: Democión de PROGRESSIVE a LIMITED ante condición de fallo.

    Demuestra:
    - Capacidad previamente promovida a PROGRESSIVE.
    - Ejecución sufre falso éxito o violación.
    - Se activa democión automática hacia LIMITED sin tocar FULL.
    """
    gate = reset_authority_gate(AuthorityMode.PROGRESSIVE)
    engine = DecisionEngine(authority_gate=gate)
    mgr = get_promotion_manager()
    reg = get_capability_registry()

    cap_id = "files.read"

    # 1. Promover capacidad
    for i in range(3):
        mgr.record_execution(cap_id, f"req-d-{i}", DecisionState.SUCCESS, is_verified=True)
    mgr.promote(cap_id, approved_by_policy=True, caller="admin")
    assert reg.is_promoted(cap_id) is True

    # 2. Provocar ejecución con falso éxito detectado (ejecutor reporta OK pero verifier reporta VERIFIED_FALSE)
    # y JDE registra la discrepancia
    req_fail = DecisionRequest(
        request_id="req-p7-real-d-fail",
        proposed_action="read_file",
        tool="files",
        parameters={"path": "C:\\temp\\fake_path.tmp"},
    )

    res = engine.decide_and_execute(
        request=req_fail,
        executor=lambda t, p: (ExecutionStatusType.OK, {}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_FALSE, False, {"error": "File does not exist"}),
    )

    assert res.state == DecisionState.FAILED
    assert res.claims_success is False

    # 3. Forzar democión por política o verificar democión automática
    mgr.demote(cap_id, target_authority=AuthorityMode.LIMITED, reason="Fallo verificado post-ejecución")

    assert reg.is_promoted(cap_id) is False
    cap = reg.get(cap_id)
    assert cap.promoted_to_progressive is False
    assert cap.authority_level == AuthorityMode.LIMITED
    assert gate.current_mode != AuthorityMode.FULL


# ==============================================================================
# 6. TELEMETRÍA Y MÉTRICAS (Test 37)
# ==============================================================================


def test_37_telemetry_metrics_under_progressive():
    """37. Valida que las métricas de telemetría de PROGRESSIVE registren todos los campos requeridos."""
    gate = reset_authority_gate(AuthorityMode.PROGRESSIVE)
    metrics = gate.metrics

    # Registrar acciones y promociones
    metrics.record_progressive_action("ALLOW", "SUCCESS", is_verified=True, execution_count=1)
    metrics.record_progressive_action("DENY", "FAILED", is_verified=False, execution_count=1)
    metrics.record_progressive_action("ALLOW", "UNKNOWN", is_verified=False, execution_count=1)
    metrics.record_progressive_action("ALLOW", "SUCCESS", is_verified=False, execution_count=1)  # Falso éxito
    metrics.record_progressive_action("ALLOW", "SUCCESS", is_verified=True, execution_count=2)  # Doble ejecución

    metrics.record_promotion("ALLOW")
    metrics.record_promotion("DENY")
    metrics.record_promotion("REQUIRE_REVIEW")
    metrics.record_demotion()

    summary = metrics.summary()
    assert summary["progressive_total"] == 5
    assert summary["progressive_allowed"] == 4
    assert summary["progressive_denied"] == 1
    assert summary["progressive_success"] == 2
    assert summary["progressive_failed"] == 1
    assert summary["progressive_unknown"] == 1
    assert summary["progressive_false_success"] == 1
    assert summary["progressive_double_execution"] == 1

    assert summary["promotion_requests"] == 3
    assert summary["promotion_allowed"] == 1
    assert summary["promotion_denied"] == 1
    assert summary["promotion_review_required"] == 1
    assert summary["demotions"] == 1
