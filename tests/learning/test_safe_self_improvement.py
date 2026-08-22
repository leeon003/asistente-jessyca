"""Suite de Pruebas Exhaustiva para Safe Self-Improvement (test_safe_self_improvement.py - Fase 60).

Verifica:
1. Aislamiento y límites en SandboxEnvironment.
2. PROTECCIÓN INVIOLABLE DE LA ZONA INMUTABLE DE SEGURIDAD (security_policy, permission_manager, audit_logger, credentials, secrets, etc.).
3. Versionamiento con VersionSnapshot y hashes SHA-256.
4. Evaluación comparativa estricta contra baseline (éxito, fallos, latencia, regresiones).
5. Descarte automático de candidatos con regresiones.
6. Despliegue controlado con aprobación obligatoria (HUMAN_APPROVAL / POLICY_APPROVAL).
7. Bloqueo de auto-despliegue incondicional y sin pruebas.
8. Reversión atómica y auditable (Rollback) validando integridad criptográfica.
9. Orquestación integral con SafeImprovementEngine.
"""

from __future__ import annotations

import pytest

from core.learning.deployment import ApprovalType, ControlledDeployer
from core.learning.evaluator import ImprovementEvaluator
from core.learning.improvement_engine import SafeImprovementEngine
from core.learning.proposal_models import (
    LearningProposal,
    ProposalCategory,
    ProposalRiskLevel,
)
from core.learning.rollback import RollbackManager
from core.learning.sandbox import (
    SandboxEnvironment,
    SandboxSecurityViolation,
    is_in_immutable_security_zone,
)
from core.learning.version_manager import (
    CandidateStatus,
    ImprovementCandidate,
    VersionManager,
    VersionSnapshot,
)

# ── TEST 1: AISLAMIENTO EN SANDBOX Y LÍMITES ──

def test_sandbox_environment_staging_and_limits():
    """Verifica preparación de archivos, límites de tamaño y auditoría en Sandbox."""
    sandbox = SandboxEnvironment(sandbox_id="sbx-test-01", max_files=2, max_file_size_bytes=1000)

    # Preparar archivo válido
    sandbox.stage_file("skills/notepad_hint.py", "def get_hints(): return ['bloc de notas']")
    assert "skills/notepad_hint.py" in sandbox.list_staged_files()
    assert sandbox.get_staged_content("skills/notepad_hint.py") == "def get_hints(): return ['bloc de notas']"

    # Segundo archivo
    sandbox.stage_file("config/vocab_hints.json", '{"notepad": ["bloc de notas"]}')
    assert len(sandbox.list_staged_files()) == 2

    # Límite de archivos excedido
    with pytest.raises(ValueError, match="Límite de archivos en sandbox excedido"):
        sandbox.stage_file("skills/extra.py", "print('overflow')")

    # Auditoría registrada
    audit = sandbox.get_audit_log()
    assert len(audit) >= 2
    assert audit[0]["action"] == "STAGE_FILE"

    # Limpieza
    sandbox.clean()
    assert len(sandbox.list_staged_files()) == 0


# ── TEST 2: PROTECCIÓN DE LA ZONA INMUTABLE DE SEGURIDAD EN SANDBOX ──

@pytest.mark.parametrize("protected_path", [
    "core/security/security_policy.py",
    "core/security/permission_manager.py",
    "core/security/risk_engine.py",
    "core/security/confirmation_manager.py",
    "core/security/audit_logger.py",
    "core/security/execution_boundary.py",
    "services/auth/credential_handling.py",
    "data/secret_storage/tokens.enc",
    "core/emergency_stop.py",
    "mcp/mcp_security_layer.py",
])
def test_sandbox_rejects_modifications_to_immutable_security_zone(protected_path: str):
    """Garantiza que Sandbox lance SandboxSecurityViolation ante cualquier intento de tocar componentes de seguridad."""
    assert is_in_immutable_security_zone(protected_path) is True

    sandbox = SandboxEnvironment(sandbox_id="sbx-sec-test")

    with pytest.raises(SandboxSecurityViolation, match="CRITICAL SECURITY VIOLATION"):
        sandbox.stage_file(protected_path, "# Intento de modificar seguridad")

    # Verificar que quedó registrado en la auditoría como SECURITY_VIOLATION_BLOCKED
    audit = sandbox.get_audit_log()
    assert any(entry["action"] == "SECURITY_VIOLATION_BLOCKED" for entry in audit)


# ── TEST 3: VERSION SNAPSHOT E INTEGRIDAD SHA-256 ──

def test_version_snapshot_cryptographic_integrity():
    """Verifica que cada VersionSnapshot genere y valide su hash SHA-256."""
    snap1 = VersionSnapshot.create_snapshot(
        version_id="v1.0.0",
        files_changed=["skills/math.py"],
        metrics={"success_rate": 0.98},
    )

    assert snap1.version_id == "v1.0.0"
    assert snap1.checksum is not None
    assert len(snap1.checksum) == 64  # SHA-256 hex string

    snap2 = VersionSnapshot.create_snapshot(
        version_id="v1.1.0",
        parent_version="v1.0.0",
        files_changed=["skills/math.py", "skills/notepad.py"],
        metrics={"success_rate": 1.0},
    )

    assert snap2.parent_version == "v1.0.0"
    assert snap2.checksum != snap1.checksum


# ── TEST 4: EVALUADOR COMPARATIVO Y POLÍTICA DE ACEPTACIÓN ──

def test_improvement_evaluator_acceptance_and_rejection():
    """Verifica aprobación de candidatos válidos y rechazo ante regresiones."""
    evaluator = ImprovementEvaluator(latency_tolerance_ratio=1.15)
    vm = VersionManager(initial_version="v1.0.0")
    baseline = vm.active_version

    # 1. Candidato que supera al baseline
    good_cand = ImprovementCandidate(
        version_tag="v2-candidate",
        parent_version="v1.0.0",
        source_proposal_id="prop-01",
        affected_files=["skills/notepad.py"],
        tests_passed=True,
        candidate_metrics={"success_rate": 1.0, "failure_rate": 0.0, "avg_latency_ms": 130.0},
    )
    res_good = evaluator.evaluate(good_cand, baseline)
    assert res_good.is_acceptable is True
    assert res_good.score == 1.0
    assert res_good.regressions_count == 0

    # 2. Candidato con caída en tasa de éxito
    bad_cand_succ = ImprovementCandidate(
        version_tag="v2-candidate-bad",
        parent_version="v1.0.0",
        source_proposal_id="prop-02",
        tests_passed=True,
        candidate_metrics={"success_rate": 0.85, "failure_rate": 0.15, "avg_latency_ms": 130.0},
    )
    res_bad_succ = evaluator.evaluate(bad_cand_succ, baseline)
    assert res_bad_succ.is_acceptable is False
    assert res_bad_succ.regressions_count >= 1
    assert any("éxito" in r.lower() or "tasa" in r.lower() for r in res_bad_succ.regressions)

    # 3. Candidato con degradación severa de latencia
    bad_cand_lat = ImprovementCandidate(
        version_tag="v2-candidate-slow",
        parent_version="v1.0.0",
        source_proposal_id="prop-03",
        tests_passed=True,
        candidate_metrics={"success_rate": 1.0, "failure_rate": 0.0, "avg_latency_ms": 300.0},
    )
    res_bad_lat = evaluator.evaluate(bad_cand_lat, baseline)
    assert res_bad_lat.is_acceptable is False
    assert any("latencia" in r.lower() for r in res_bad_lat.regressions)

    # 4. Candidato con pruebas fallidas
    bad_cand_tests = ImprovementCandidate(
        version_tag="v2-candidate-untested",
        parent_version="v1.0.0",
        source_proposal_id="prop-04",
        tests_passed=False,
        candidate_metrics={"success_rate": 1.0, "failure_rate": 0.0, "avg_latency_ms": 100.0},
    )
    res_untested = evaluator.evaluate(bad_cand_tests, baseline)
    assert res_untested.is_acceptable is False


# ── TEST 5: DESPLIEGUE CONTROLADO CON APROBACIÓN ──

def test_controlled_deployer_requirements():
    """Verifica que el despliegue exija pruebas, evaluación y aprobación explícita."""
    vm = VersionManager(initial_version="v1.0.0")
    deployer = ControlledDeployer(version_manager=vm)
    evaluator = ImprovementEvaluator()

    cand = vm.create_candidate(
        source_proposal_id="prop-100",
        version_tag="v2-candidate",
        affected_files=["skills/notepad_hint.py"],
        staged_changes={"skills/notepad_hint.py": "# hint"},
    )

    # Intento 1: Desplegar sin pruebas pasadas
    eval_res = evaluator.evaluate(cand, vm.active_version)
    with pytest.raises(ValueError, match="no ha aprobado las pruebas requeridas"):
        deployer.deploy_candidate(cand, eval_res, approved_by="admin", approval_type=ApprovalType.HUMAN_APPROVAL)

    # Marcar pruebas aprobadas
    cand_dict = cand.to_dict()
    cand_dict["tests_passed"] = True
    cand_dict["candidate_metrics"] = {"success_rate": 1.0, "failure_rate": 0.0, "avg_latency_ms": 110.0}
    cand_ready = ImprovementCandidate.model_validate(cand_dict)
    eval_res_ready = evaluator.evaluate(cand_ready, vm.active_version)

    # Intento 2: Desplegar sin aprobador explícito
    with pytest.raises(ValueError, match="se requiere un aprobador explícito"):
        deployer.deploy_candidate(cand_ready, eval_res_ready, approved_by="", approval_type=ApprovalType.HUMAN_APPROVAL)

    # Despliegue válido
    dep_res = deployer.deploy_candidate(
        cand_ready,
        eval_res_ready,
        approved_by="Supervisor_Humano",
        approval_type=ApprovalType.HUMAN_APPROVAL,
    )

    assert dep_res.status == "DEPLOYED"
    assert dep_res.deployed_version_id == "v2"
    assert dep_res.previous_version_id == "v1.0.0"
    assert vm.active_version.version_id == "v2"
    assert vm.active_version.parent_version == "v1.0.0"


# ── TEST 6: ROLLBACK ATÓMICO Y VERIFICADO ──

def test_atomic_rollback_to_parent_version():
    """Verifica reversión atómica de v2 a v1.0.0 con verificación de checksum."""
    vm = VersionManager(initial_version="v1.0.0")
    rollback_mgr = RollbackManager(version_manager=vm)

    # Intento de rollback sobre la versión inicial (sin padre)
    with pytest.raises(ValueError, match="no posee una versión padre previa"):
        rollback_mgr.rollback_to_parent(reason="prueba inválida")

    # Simular versión 2 desplegada
    v2_snapshot = VersionSnapshot.create_snapshot(
        version_id="v2.0.0",
        parent_version="v1.0.0",
        files_changed=["skills/notepad_hint.py"],
        status="ACTIVE",
    )
    vm.register_snapshot(v2_snapshot)
    vm.set_active_version("v2.0.0")
    assert vm.active_version.version_id == "v2.0.0"

    # Ejecutar rollback
    res = rollback_mgr.rollback_to_parent(reason="Regresión de latencia detectada en producción")
    assert res.success is True
    assert res.checksum_verified is True
    assert res.from_version_id == "v2.0.0"
    assert res.restored_version_id == "v1.0.0"

    # La versión activa vuelve a ser v1.0.0
    assert vm.active_version.version_id == "v1.0.0"


# ── TEST 7: FLUJO INTEGRAL END-TO-END CON SAFE IMPROVEMENT ENGINE ──

def test_safe_improvement_engine_end_to_end_flow():
    """Verifica el flujo completo: Proposal -> Candidate -> Sandbox Tests -> Evaluation -> Approval -> Deployment -> Rollback."""
    engine = SafeImprovementEngine()
    assert engine.active_version.version_id == "v1.0.0"

    proposal = LearningProposal(
        category=ProposalCategory.STT,
        problem="Ambigüedad STT en 'bloc de notas'",
        evidence=[{"variants": ["blog de notas"]}],
        occurrences=18,
        suggested_improvement="Añadir vocabulario contextual para Bloc de notas",
        expected_benefit="Incrementar precisión a 100%",
        risk=ProposalRiskLevel.LOW,
        affected_components=["voice.stt_contextual_vocabulary"],
        required_tests=["test_stt_notepad_recognition", "test_stt_general_commands"],
    )

    staged_changes = {
        "voice/stt_hints.py": "NOTEPAD_HINTS = ['bloc de notas', 'blog de notas']",
    }

    # 1. Preparar y probar candidato en Sandbox
    candidate, eval_res = engine.prepare_and_test_candidate(
        proposal=proposal,
        staged_changes=staged_changes,
        version_tag="v2-candidate",
        simulated_metrics={"success_rate": 1.0, "failure_rate": 0.0, "avg_latency_ms": 115.0},
    )

    assert candidate.status == CandidateStatus.EVALUATED
    assert candidate.tests_passed is True
    assert eval_res.is_acceptable is True

    # 2. Despliegue con aprobación humana explícita
    dep_res = engine.deploy_candidate(
        candidate_id=candidate.candidate_id,
        approved_by="Auditor_Seguridad",
        approval_type=ApprovalType.HUMAN_APPROVAL,
    )

    assert dep_res.status == "DEPLOYED"
    assert engine.active_version.version_id == "v2"

    # 3. Simulación de regresión post-despliegue y Rollback
    rb_res = engine.rollback(reason="Detección de fallo intermitente post-despliegue")
    assert rb_res.success is True
    assert rb_res.restored_version_id == "v1.0.0"
    assert engine.active_version.version_id == "v1.0.0"


# ── TEST 8: INTENTO DE MODIFICACIÓN DE SEGURIDAD EN ENGINE ES RECHAZADO ──

def test_engine_blocks_security_immutable_zone_modifications():
    """Garantiza que SafeImprovementEngine aborte si se intenta preparar cambios sobre core/security."""
    engine = SafeImprovementEngine()

    unsafe_proposal = LearningProposal(
        category=ProposalCategory.TOOL,
        problem="Bypass permission manager",
        evidence=[{"e": 1}],
        suggested_improvement="Eliminar confirmación",
        expected_benefit="Velocidad",
        risk=ProposalRiskLevel.CRITICAL,
        affected_components=["core.security.permission_manager"],
        required_tests=["test_bypass"],
    )

    unsafe_changes = {
        "core/security/permission_manager.py": "# Bypass permission checks",
    }

    with pytest.raises(ValueError, match="CRITICAL SECURITY VIOLATION"):
        engine.prepare_and_test_candidate(
            proposal=unsafe_proposal,
            staged_changes=unsafe_changes,
        )
