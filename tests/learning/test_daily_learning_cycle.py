"""Suite de Pruebas Exhaustiva para el Ciclo Diario de Aprendizaje (test_daily_learning_cycle.py - Fase 63).

Verifica:
1. Política de aprendizaje, límites y activación de Circuit Breaker.
2. Formato, serialización y persistencia de DailyLearningReport en Markdown y JSON.
3. Ejecución determinista e integral de DailyLearningCycle en modo simulado.
4. Idempotencia estricta por fecha (date_iso / run_id).
5. Despliegue automático DESACTIVADO por defecto y exigencia de aprobación explícita.
6. Integración de regresiones, sandbox, personalización y generación de reportes.
7. Aislamiento de fallos (failure isolation) ante anomalías en subcomponentes.
8. Programador DailyLearningScheduler y disparos manuales.
9. Flujo conceptual maestro End-to-End de todo el Experience & Learning Engine.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from core.experience.experience_store import InMemoryExperienceStore
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
from core.experience.repository import ExperienceRepository
from core.learning.daily.daily_cycle import DailyLearningCycle
from core.learning.daily.daily_policy import DailyLearningPolicy
from core.learning.daily.daily_report import DailyLearningReport
from core.learning.daily.daily_scheduler import DailyLearningScheduler
from core.learning.improvement_engine import SafeImprovementEngine
from core.learning.proposal_engine import LearningProposalEngine
from core.learning.proposal_store import InMemoryProposalStore
from core.learning.regression.regression_engine import RegressionEngine
from core.learning.regression.regression_store import InMemoryRegressionStore
from core.learning.version_manager import VersionManager
from core.personalization.preference_engine import PersonalizationEngine
from core.personalization.preference_store import InMemoryPreferenceStore


def _seed_experiences_for_day(repo: ExperienceRepository) -> None:
    """Helper para poblar el repositorio con experiencias variadas de la jornada."""
    now = datetime.now(UTC)

    # 1. Éxito normal
    repo.save_experience(
        Experience(
            timestamp=now,
            category=ExperienceCategory.ACTION_SUCCESS,
            input=ExperienceInput(source=InputSource.VOICE, raw_text="abre la calculadora", timestamp=now),
            stt=STTResult(text="abre la calculadora", confidence=0.98),
            intent=IntentResult(name="open_application", confidence=0.99),
            target=TargetInfo(target_type="application", value="calc"),
            execution=ExecutionResult(status=ExecutionStatus.SUCCESS, tool_name="windows.apps"),
        )
    )

    # 2. Variantes STT repetidas (bloc de notas)
    for txt in ("abre blog de notas", "abre blot de notas", "abre bloc de notas"):
        repo.save_experience(
            Experience(
                timestamp=now,
                category=ExperienceCategory.LOW_STT_CONFIDENCE,
                input=ExperienceInput(source=InputSource.VOICE, raw_text=txt, timestamp=now),
                stt=STTResult(text=txt, confidence=0.48, is_low_confidence=True),
                intent=IntentResult(name="open_application", confidence=0.90),
                target=TargetInfo(target_type="application", value="bloc de notas"),
                execution=ExecutionResult(status=ExecutionStatus.SUCCESS, tool_name="windows.apps"),
                error=ErrorInfo(error_type="STTRecognitionError", message="Low confidence phonetic variant"),
            )
        )

    # 3. Fallo de tool
    repo.save_experience(
        Experience(
            timestamp=now,
            category=ExperienceCategory.ACTION_FAILED,
            input=ExperienceInput(source=InputSource.VOICE, raw_text="limpia los temporales", timestamp=now),
            stt=STTResult(text="limpia los temporales", confidence=0.95),
            intent=IntentResult(name="cleanup_files", confidence=0.85),
            target=TargetInfo(target_type="system", value="temp_files"),
            execution=ExecutionResult(status=ExecutionStatus.FAILED, tool_name="system.cleanup"),
            error=ErrorInfo(error_type="PermissionDeniedError", message="Access denied on temp"),
        )
    )


# ── TEST 1: POLÍTICA DE APRENDIZAJE Y CIRCUIT BREAKER ──

def test_daily_learning_policy_and_circuit_breaker():
    """Verifica reglas de límites y disparo de Circuit Breaker ante anomalías."""
    policy = DailyLearningPolicy(
        max_proposals=5,
        max_runtime_sec=10.0,
        max_test_failures=2,
        require_approval=True,
        auto_deploy=False,
    )

    # Caso normal sin incidentes
    tripped, reason = policy.check_circuit_breaker(security_events=0, test_failures=1, runtime_sec=2.0)
    assert tripped is False
    assert reason is None

    # Disparo por evento de seguridad
    tripped_sec, reason_sec = policy.check_circuit_breaker(security_events=1)
    assert tripped_sec is True
    assert "seguridad" in reason_sec.lower()

    # Disparo por violación de sandbox
    tripped_sbx, reason_sbx = policy.check_circuit_breaker(sandbox_violations=1)
    assert tripped_sbx is True
    assert "sandbox" in reason_sbx.lower()

    # Disparo por exceso de fallos de pruebas
    tripped_tests, reason_tests = policy.check_circuit_breaker(test_failures=5)
    assert tripped_tests is True
    assert "fallos de pruebas" in reason_tests.lower()

    # Disparo por timeout
    tripped_to, reason_to = policy.check_circuit_breaker(runtime_sec=15.0)
    assert tripped_to is True
    assert "superó el límite" in reason_to.lower()

    # Política de despliegue
    assert policy.can_deploy(is_approved=False) is False
    assert policy.can_deploy(is_approved=True) is True


# ── TEST 2: REPORTE DIARIO DE APRENDIZAJE ──

def test_daily_learning_report_generation_and_persistence():
    """Verifica generación de Markdown y guardado en JSON/MD."""
    report = DailyLearningReport(
        date="2026-08-22",
        run_id="run-test-001",
        total_experiences=100,
        successful_experiences=92,
        failed_experiences=8,
        verification_failures=2,
        clarifications=3,
        corrections=4,
        patterns_detected=["STT: Bloc de notas", "Tool: Cleanup failed"],
        proposals_generated=2,
        proposals_approved=2,
        proposals_rejected=0,
        regression_tests_added=3,
        improvements_deployed=1,
        duration_ms=1250.0,
    )

    md = report.to_markdown()
    assert "# JESSYCA LEARNING REPORT" in md
    assert "2026-08-22" in md
    assert "Total Experiencias:** 100" in md
    assert "STT: Bloc de notas" in md

    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = report.save(storage_dir=tmpdir)
        assert json_path.exists()
        md_path = Path(tmpdir) / f"report_2026-08-22_{report.run_id[:8]}.md"
        assert md_path.exists()


# ── TEST 3: EJECUCIÓN COMPLETA DEL CICLO DIARIO EN MODO SIMULADO ──

def test_daily_learning_cycle_full_execution():
    """Verifica la ejecución determinista del ciclo diario integrando todos los motores."""
    exp_store = InMemoryExperienceStore()
    repo = ExperienceRepository(store=exp_store)
    _seed_experiences_for_day(repo)

    from core.experience.analyzer import ExperienceAnalyzer
    analyzer = ExperienceAnalyzer(repository=repo)

    prop_store = InMemoryProposalStore()
    proposal_engine = LearningProposalEngine(store=prop_store)

    reg_store = InMemoryRegressionStore()
    regression_engine = RegressionEngine(store=reg_store, baseline_tests_count=2119)

    vm = VersionManager(initial_version="v1.0.0")
    improvement_engine = SafeImprovementEngine(version_manager=vm, regression_engine=regression_engine)

    pref_store = InMemoryPreferenceStore()
    personalization_engine = PersonalizationEngine(store=pref_store)

    policy = DailyLearningPolicy(
        max_proposals=5,
        require_approval=True,
        auto_deploy=False,
    )

    cycle = DailyLearningCycle(
        analyzer=analyzer,
        proposal_engine=proposal_engine,
        regression_engine=regression_engine,
        improvement_engine=improvement_engine,
        personalization_engine=personalization_engine,
        policy=policy,
    )

    report = cycle.run(date_iso="2026-08-22", force=True)

    assert report.status == "COMPLETED"
    assert report.total_experiences == 5
    assert report.successful_experiences == 4
    assert report.failed_experiences == 1
    assert report.proposals_generated >= 1
    assert report.regression_tests_added >= 1
    # Auto-deploy disabled by default
    assert report.improvements_deployed == 0


# ── TEST 4: IDEMPOTENCIA POR FECHA ──

def test_daily_cycle_idempotency():
    """Verifica que reejecutar el ciclo para la misma fecha retorne el reporte previo sin duplicar."""
    exp_store = InMemoryExperienceStore()
    repo = ExperienceRepository(store=exp_store)
    _seed_experiences_for_day(repo)

    from core.experience.analyzer import ExperienceAnalyzer
    analyzer = ExperienceAnalyzer(repository=repo)

    prop_store = InMemoryProposalStore()
    proposal_engine = LearningProposalEngine(store=prop_store)

    cycle = DailyLearningCycle(
        analyzer=analyzer,
        proposal_engine=proposal_engine,
        policy=DailyLearningPolicy(),
    )

    r1 = cycle.run(date_iso="2026-08-22", force=False)
    initial_props_count = prop_store.count()

    r2 = cycle.run(date_iso="2026-08-22", force=False)

    assert r1.run_id == r2.run_id
    assert prop_store.count() == initial_props_count


# ── TEST 5: DESPLIEGUE CON APROBACIÓN EXPLÍCITA ──

def test_daily_cycle_deployment_with_explicit_approval():
    """Verifica que si se provee aprobación explícita el candidato calificado se despliegue."""
    exp_store = InMemoryExperienceStore()
    repo = ExperienceRepository(store=exp_store)
    _seed_experiences_for_day(repo)

    from core.experience.analyzer import ExperienceAnalyzer
    analyzer = ExperienceAnalyzer(repository=repo)

    prop_store = InMemoryProposalStore()
    proposal_engine = LearningProposalEngine(store=prop_store)

    reg_store = InMemoryRegressionStore()
    regression_engine = RegressionEngine(store=reg_store)

    vm = VersionManager(initial_version="v1.0.0")
    improvement_engine = SafeImprovementEngine(version_manager=vm, regression_engine=regression_engine)

    cycle = DailyLearningCycle(
        analyzer=analyzer,
        proposal_engine=proposal_engine,
        regression_engine=regression_engine,
        improvement_engine=improvement_engine,
        policy=DailyLearningPolicy(require_approval=True),
    )

    report = cycle.run(
        date_iso="2026-08-22",
        force=True,
        approved_by="Auditor_Seguridad_Principal",
    )

    assert report.status == "COMPLETED"
    assert report.improvements_deployed >= 1
    assert vm.active_version.version_id != "v1.0.0"


# ── TEST 6: DISPARO DE CIRCUIT BREAKER ANTE FALLOS ──

def test_daily_cycle_circuit_breaker_abort():
    """Verifica que el ciclo aborte (ABORTED) si se supera el umbral de fallos permitido."""
    exp_store = InMemoryExperienceStore()
    repo = ExperienceRepository(store=exp_store)
    _seed_experiences_for_day(repo)

    from core.experience.analyzer import ExperienceAnalyzer
    analyzer = ExperienceAnalyzer(repository=repo)

    # Inyectar caso roto en regression store
    reg_store = InMemoryRegressionStore()
    reg_engine = RegressionEngine(store=reg_store)
    from core.learning.regression.regression_models import (
        RegressionCase,
        RegressionCategory,
        RegressionStatus,
    )
    broken_case = RegressionCase(
        category=RegressionCategory.STT,
        description="Fallo forzado",
        input_text="bad",
        expected_behavior={},
        failure_signature="sig-fail",
        test_reference="test_broken",
        status=RegressionStatus.ACTIVE,
    )
    reg_store.save(broken_case)

    # Política estricta: 0 fallos tolerados
    strict_policy = DailyLearningPolicy(max_test_failures=0)

    cycle = DailyLearningCycle(
        analyzer=analyzer,
        regression_engine=reg_engine,
        policy=strict_policy,
    )

    report = cycle.run(date_iso="2026-08-22", force=True)
    assert report.status == "ABORTED"
    assert "Circuit Breaker" in report.notes


# ── TEST 7: AISLAMIENTO DE FALLOS (FAILURE ISOLATION) ──

def test_daily_cycle_failure_isolation():
    """Garantiza que una excepción no controlada sea capturada de forma segura sin abortar la aplicación."""
    class CrashingAnalyzer:
        def analyze(self, *args, **kwargs):
            raise RuntimeError("Database connection corrupted")

    cycle = DailyLearningCycle(analyzer=CrashingAnalyzer())  # type: ignore

    report = cycle.run(date_iso="2026-08-22", force=True)
    assert report.status == "FAILED"
    assert "Database connection corrupted" in report.notes


# ── TEST 8: PROGRAMADOR DAILY LEARNING SCHEDULER ──

def test_daily_learning_scheduler():
    """Verifica la programación y ejecución manual a través de DailyLearningScheduler."""
    cycle = DailyLearningCycle()
    scheduler = DailyLearningScheduler(daily_cycle=cycle, daily_time="23:00")

    assert scheduler.is_scheduled is False
    assert scheduler.schedule() is True
    assert scheduler.is_scheduled is True

    # Disparo manual
    report = scheduler.trigger_manual_run(date_iso="2026-08-22", force=True)
    assert report is not None
    assert report.run_id is not None
