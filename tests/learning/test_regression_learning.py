"""Suite de Pruebas Exhaustiva para Regression Learning (test_regression_learning.py - Fase 61).

Verifica:
1. Generación de candidatos de regresión a partir de experiencias y propuestas.
2. Ciclo de vida y máquina de estados (CANDIDATE -> VALIDATED -> ACTIVE -> DISABLED -> RETIRED).
3. FILTRO DE SEGURIDAD CONTRA TESTS DESTRUCTIVOS (rmdir, del, format, registry, etc.).
4. Deduplicación criptográfica estricta basada en SHA-256 (failure_signature).
5. Generación y ejecución determinista de tests para STT, Intent, Clarification, Tool, Memory, Performance.
6. Integración con Fase 60: Bloqueo de despliegue ante fallos en la suite de regresiones activas (DEPLOYMENT BLOCKED).
7. Trazabilidad completa a la experiencia y propuesta de origen.
8. Estadísticas dinámicas de la suite de regresiones.
9. Persistencia en InMemoryRegressionStore y SQLiteRegressionStore.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.experience.models import (
    ErrorInfo,
    ExecutionResult,
    ExecutionStatus,
    Experience,
    ExperienceCategory,
    ExperienceInput,
    InputSource,
    IntentResult,
    STTResult,
    TargetInfo,
)
from core.learning.deployment import ApprovalType, ControlledDeployer
from core.learning.evaluator import ImprovementEvaluator
from core.learning.regression.regression_engine import RegressionEngine
from core.learning.regression.regression_models import (
    RegressionCase,
    RegressionCategory,
    RegressionStatus,
)
from core.learning.regression.regression_store import (
    InMemoryRegressionStore,
    SQLiteRegressionStore,
)
from core.learning.regression.regression_validator import (
    RegressionValidator,
)
from core.learning.version_manager import (
    ImprovementCandidate,
    VersionManager,
)


def _create_faulty_experience(
    raw_text: str = "abre el bloc de notaciones",
    category: ExperienceCategory = ExperienceCategory.LOW_STT_CONFIDENCE,
    error_msg: str = "STT Low Confidence Discrepancy",
    intent_name: str = "open_application",
    target_val: str = "notepad",
) -> Experience:
    ts = datetime.now(UTC)
    return Experience(
        timestamp=ts,
        category=category,
        input=ExperienceInput(source=InputSource.VOICE, raw_text=raw_text, timestamp=ts),
        stt=STTResult(text=raw_text, confidence=0.45, is_low_confidence=True),
        intent=IntentResult(name=intent_name, confidence=0.90),
        target=TargetInfo(target_type="application", value=target_val),
        execution=ExecutionResult(status=ExecutionStatus.SUCCESS, tool_name="windows.apps"),
        error=ErrorInfo(error_type="STTRecognitionError", message=error_msg),
    )


# ── TEST 1: GENERACIÓN DE CANDIDATO Y TRAZABILIDAD ──

def test_create_candidate_from_faulty_experience():
    """Verifica que un fallo de experiencia se convierta en candidato con trazabilidad."""
    store = InMemoryRegressionStore()
    engine = RegressionEngine(store=store)

    exp = _create_faulty_experience(raw_text="abre bloc de notaciones", target_val="bloc de notas")
    proposal_id = "prop-stt-001"

    candidate = engine.create_candidate_from_experience(exp, proposal_id=proposal_id)

    assert candidate is not None
    assert candidate.status == RegressionStatus.CANDIDATE
    assert candidate.category == RegressionCategory.STT
    assert candidate.source_experience_id == exp.experience_id
    assert candidate.source_proposal_id == proposal_id
    assert candidate.failure_signature is not None
    assert candidate.expected_behavior.get("canonical_target") == "bloc de notas"
    assert "def test_regression_stt_" in candidate.test_code_snippet


# ── TEST 2: DEDUPLICACIÓN DE CASOS DE REGRESIÓN ──

def test_regression_deduplication():
    """Verifica que experiencias con la misma firma de fallo no creen casos duplicados."""
    store = InMemoryRegressionStore()
    engine = RegressionEngine(store=store)

    exp1 = _create_faulty_experience(raw_text="abre bloc de notaciones")
    exp2 = _create_faulty_experience(raw_text="abre bloc de notaciones")

    case1 = engine.create_candidate_from_experience(exp1)
    case2 = engine.create_candidate_from_experience(exp2)

    assert case1 is not None and case2 is not None
    assert case1.case_id == case2.case_id
    assert store.count() == 1


# ── TEST 3: FILTRO DE SEGURIDAD CONTRA TESTS DESTRUCTIVOS ──

@pytest.mark.parametrize("destructive_cmd", [
    "rmdir /s /q C:\\Windows",
    "del /f /q *.*",
    "format D:",
    "reg delete HKLM\\Software",
    "shutdown -s -t 0",
    "drop database production",
])
def test_security_filter_blocks_destructive_regression_cases(destructive_cmd: str):
    """Garantiza que cualquier caso de regresión con comandos destructivos sea rechazado."""
    case = RegressionCase(
        category=RegressionCategory.TOOL,
        description="Test malicioso",
        input_text=destructive_cmd,
        expected_behavior={"action": destructive_cmd},
        failure_signature="sig-unsafe-001",
        test_reference="test_unsafe",
    )

    is_valid, errors = RegressionValidator.validate_case(case)
    assert is_valid is False
    assert any("CRITICAL SECURITY VIOLATION" in err for err in errors)

    store = InMemoryRegressionStore()
    engine = RegressionEngine(store=store)
    store.save(case)

    with pytest.raises(ValueError, match="CRITICAL SECURITY VIOLATION"):
        engine.validate_and_activate(case.case_id)


# ── TEST 4: CICLO DE VIDA (CANDIDATE -> VALIDATED -> ACTIVE -> DISABLED -> RETIRED) ──

def test_regression_case_lifecycle():
    """Verifica el ciclo de vida completo de un caso de prueba de regresión."""
    store = InMemoryRegressionStore()
    engine = RegressionEngine(store=store)

    exp = _create_faulty_experience(raw_text="calcula 10 + 20", category=ExperienceCategory.AMBIGUOUS_INTENT)
    candidate = engine.create_candidate_from_experience(exp)
    assert candidate.status == RegressionStatus.CANDIDATE

    # 1. Validar y Activar
    active = engine.validate_and_activate(candidate.case_id)
    assert active.status == RegressionStatus.ACTIVE

    # 2. Desactivar temporalmente
    disabled = engine.disable_regression(active.case_id, reason="Desactivado por refactorización de skill")
    assert disabled.status == RegressionStatus.DISABLED
    assert disabled.metadata.get("status_change_reason") == "Desactivado por refactorización de skill"

    # 3. Retirar definitivamente
    retired = engine.retire_regression(disabled.case_id, reason="Prueba obsoleta tras versión v3")
    assert retired.status == RegressionStatus.RETIRED


# ── TEST 5: EJECUCIÓN DETERMINISTA DE LA SUITE DE REGRESIONES ──

def test_deterministic_regression_suite_execution():
    """Verifica la ejecución determinista de casos de regresión para diversas categorías."""
    store = InMemoryRegressionStore()
    engine = RegressionEngine(store=store)

    # 1. Caso STT
    case_stt = RegressionCase(
        category=RegressionCategory.STT,
        description="Regresión de bloc de notas",
        input_text="abre blog de notas",
        expected_behavior={"canonical_target": "bloc de notas"},
        failure_signature="sig-stt-1",
        test_reference="test_stt_notepad",
        status=RegressionStatus.ACTIVE,
    )
    # 2. Caso Intent
    case_intent = RegressionCase(
        category=RegressionCategory.INTENT,
        description="Regresión de calculadora",
        input_text="cuanto es 2+2",
        expected_behavior={"intent": "math_calculation"},
        failure_signature="sig-intent-1",
        test_reference="test_intent_math",
        status=RegressionStatus.ACTIVE,
    )
    # 3. Caso Clarification
    case_clarif = RegressionCase(
        category=RegressionCategory.CLARIFICATION,
        description="Regresión de comando incompleto",
        input_text="abre",
        expected_behavior={"needs_clarification": True},
        failure_signature="sig-clarif-1",
        test_reference="test_clarif_open",
        status=RegressionStatus.ACTIVE,
    )

    store.save(case_stt)
    store.save(case_intent)
    store.save(case_clarif)

    all_passed, tests_run, failures = engine.run_regression_suite(active_only=True)
    assert all_passed is True
    assert tests_run == 3
    assert len(failures) == 0


# ── TEST 6: BLOQUEO DE DESPLIEGUE EN FASE 60 ANTE REGRESIONES ACTIVAS FALLIDAS ──

def test_failing_active_regression_blocks_deployment():
    """Garantiza que una regresión activa defectuosa aborte el despliegue de una nueva versión."""
    store = InMemoryRegressionStore()
    regression_engine = RegressionEngine(store=store)

    # Crear caso de regresión activo con expectativa rota
    bad_case = RegressionCase(
        category=RegressionCategory.STT,
        description="Regresión con fallo forzado",
        input_text="comando roto",
        expected_behavior={},  # Falta canonical_target -> provocará fallo
        failure_signature="sig-fail-forced",
        test_reference="test_regression_broken",
        status=RegressionStatus.ACTIVE,
    )
    store.save(bad_case)

    # Configurar Deployer de Fase 60
    vm = VersionManager(initial_version="v1.0.0")
    deployer = ControlledDeployer(version_manager=vm, regression_engine=regression_engine)
    evaluator = ImprovementEvaluator()

    cand = vm.create_candidate(
        source_proposal_id="prop-test",
        version_tag="v2-candidate",
        affected_files=["skills/notepad.py"],
        staged_changes={"skills/notepad.py": "# code"},
    )
    cand_dict = cand.to_dict()
    cand_dict["tests_passed"] = True
    cand_dict["candidate_metrics"] = {"success_rate": 1.0, "failure_rate": 0.0, "avg_latency_ms": 100.0}
    cand_ready = ImprovementCandidate.model_validate(cand_dict)
    eval_res = evaluator.evaluate(cand_ready, vm.active_version)

    # El despliegue DEBE ser bloqueado
    with pytest.raises(ValueError, match="DEPLOYMENT BLOCKED: Falla en suite de regresiones activas"):
        deployer.deploy_candidate(
            candidate=cand_ready,
            evaluation=eval_res,
            approved_by="Auditor_Humano",
            approval_type=ApprovalType.HUMAN_APPROVAL,
        )


# ── TEST 7: ESTADÍSTICAS DINÁMICAS DE LA SUITE ──

def test_regression_suite_dynamic_stats():
    """Verifica el cálculo de estadísticas dinámicas y acumulativas."""
    store = InMemoryRegressionStore()
    engine = RegressionEngine(store=store, baseline_tests_count=2093)

    c1 = RegressionCase(
        category=RegressionCategory.STT,
        description="c1",
        input_text="t1",
        expected_behavior={"canonical_target": "app1"},
        failure_signature="s1",
        test_reference="ref1",
        status=RegressionStatus.ACTIVE,
    )
    c2 = RegressionCase(
        category=RegressionCategory.INTENT,
        description="c2",
        input_text="t2",
        expected_behavior={"intent": "i1"},
        failure_signature="s2",
        test_reference="ref2",
        status=RegressionStatus.ACTIVE,
    )
    c3 = RegressionCase(
        category=RegressionCategory.TOOL,
        description="c3",
        input_text="t3",
        expected_behavior={"tool_name": "tool1"},
        failure_signature="s3",
        test_reference="ref3",
        status=RegressionStatus.DISABLED,
    )

    store.save(c1)
    store.save(c2)
    store.save(c3)

    stats = engine.get_stats()
    assert stats.initial_tests == 2093
    assert stats.generated_tests == 3
    assert stats.active_regressions == 2
    assert stats.disabled_regressions == 1
    assert stats.retired_regressions == 0
    assert stats.total_tests == 2095


# ── TEST 8: PERSISTENCIA EN SQLITE REGRESSION STORE ──

def test_sqlite_regression_store_persistence():
    """Verifica persistencia determinista y consultas en SQLiteRegressionStore."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_regressions.db")
        store = SQLiteRegressionStore(db_path=db_path)

        case = RegressionCase(
            category=RegressionCategory.STT,
            description="Persisted case",
            input_text="test pers",
            expected_behavior={"canonical_target": "target_pers"},
            failure_signature="sig-pers-1",
            test_reference="test_pers_01",
            status=RegressionStatus.ACTIVE,
        )
        store.save(case)

        assert store.count() == 1
        assert store.count(status=RegressionStatus.ACTIVE) == 1

        # Reabrir almacén
        store2 = SQLiteRegressionStore(db_path=db_path)
        retrieved = store2.get_by_signature("sig-pers-1")
        assert retrieved is not None
        assert retrieved.case_id == case.case_id
        assert retrieved.description == "Persisted case"

        store2.clear()
        assert store2.count() == 0
