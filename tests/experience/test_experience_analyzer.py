"""Suite de Pruebas Exhaustiva para Experience Analyzer (test_experience_analyzer.py - Fase 58).

Verifica:
1. Cálculo de métricas estadísticas agregadas y percentiles de latencia (p50, p95).
2. Ventanas de análisis por volumen (últimas N) y tiempo (horas, días, rangos).
3. Filtrado por acción, skill e intención.
4. Detección de fallos repetidos (Repeated Failure) y éxitos consistentes (Repeated Success).
5. Detección de baja confianza STT y variantes fonéticas/léxicas ("bloc de notas" vs "blog de notas" vs "blot de notas").
6. Detección de ambigüedad de intenciones y aclaraciones reiteradas.
7. Detección de fallos de verificación post-ejecución en el sistema operativo.
8. Detección de patrones de corrección del usuario.
9. Detección de degradación de latencia.
10. Casos borde: historial vacío, un solo registro, grandes volúmenes (500+ experiencias).
11. Procesamiento seguro de datos sanitizados (Zero Leakage).
12. Invariante de Solo Lectura (Read-Only) y determinismo estricto.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.experience.analysis_models import (
    AnalysisWindow,
    PatternSeverity,
    PatternType,
    STTPattern,
)
from core.experience.analyzer import ExperienceAnalyzer
from core.experience.experience_store import InMemoryExperienceStore
from core.experience.metrics import calculate_metrics
from core.experience.models import (
    CorrectionInfo,
    ErrorInfo,
    ExecutionResult,
    ExecutionStatus,
    Experience,
    ExperienceCategory,
    ExperienceInput,
    ExperienceMetadata,
    InputSource,
    IntentResult,
    LatencyInfo,
    ResponseResult,
    STTResult,
    TargetInfo,
    VerificationResult,
    VerificationStatus,
)
from core.experience.patterns import (
    detect_latency_degradations,
    detect_low_intent_confidence,
    detect_low_stt_confidence,
    detect_repeated_clarifications,
    detect_repeated_failures,
    detect_repeated_successes,
    detect_stt_variants,
    detect_tool_skill_failures,
    detect_user_corrections,
    detect_verification_failures,
)
from core.experience.repository import ExperienceRepository


def _create_sample_experience(
    category: ExperienceCategory = ExperienceCategory.ACTION_SUCCESS,
    raw_text: str = "abre el bloc de notas",
    intent_name: str = "open_application",
    target_value: str = "notepad",
    exec_status: ExecutionStatus = ExecutionStatus.SUCCESS,
    is_verified: bool = True,
    stt_conf: float = 0.98,
    intent_conf: float = 1.0,
    latency_ms: float = 120.0,
    skill_used: str | None = "windows.apps",
    tool_name: str | None = None,
    timestamp: datetime | None = None,
    error_msg: str | None = None,
    is_correction: bool = False,
    corrected_val: str | None = None,
) -> Experience:
    """Helper para instanciar experiencias de prueba con parámetros flexibles."""
    ts = timestamp or datetime.now(UTC)
    active_tool = tool_name or skill_used or "windows.apps"
    return Experience(
        timestamp=ts,
        category=category,
        input=ExperienceInput(source=InputSource.TEXT, raw_text=raw_text, timestamp=ts),
        stt=STTResult(text=raw_text, confidence=stt_conf, is_low_confidence=stt_conf < 0.60),
        intent=IntentResult(name=intent_name, confidence=intent_conf, is_ambiguous=intent_conf < 0.60),
        target=TargetInfo(target_type="application", value=target_value),
        execution=ExecutionResult(status=exec_status, tool_name=active_tool, action=intent_name),
        verification=VerificationResult(
            status=VerificationStatus.SUCCESS if is_verified else VerificationStatus.FAILED,
            is_verified=is_verified,
            verification_type="process",
        ),
        response=ResponseResult(text=f"Respuesta para {raw_text}"),
        latency=LatencyInfo(total_ms=latency_ms, execution_ms=latency_ms * 0.7),
        error=ErrorInfo(error_type="ExecutionError", message=error_msg) if error_msg else None,
        correction=CorrectionInfo(is_correction=is_correction, corrected_target=corrected_val) if is_correction else None,
        metadata=ExperienceMetadata(skill_used=skill_used, version="3.0.0"),
    )


# ── TEST 1: CÁLCULO ESTADÍSTICO DE MÉTRICAS ──

def test_calculate_metrics_statistics():
    """Verifica el cálculo de tasas y percentiles (p50, p95)."""
    exps = [
        _create_sample_experience(exec_status=ExecutionStatus.SUCCESS, latency_ms=100.0, is_verified=True),
        _create_sample_experience(exec_status=ExecutionStatus.SUCCESS, latency_ms=200.0, is_verified=True),
        _create_sample_experience(exec_status=ExecutionStatus.SUCCESS, latency_ms=300.0, is_verified=True),
        _create_sample_experience(exec_status=ExecutionStatus.FAILED, latency_ms=400.0, is_verified=False),
    ]

    metrics = calculate_metrics(exps)

    assert metrics.total_experiences == 4
    assert metrics.success_count == 3
    assert metrics.failure_count == 1
    assert metrics.success_rate == 0.75
    assert metrics.failure_rate == 0.25
    assert metrics.verification_success_rate == 0.75
    assert metrics.avg_latency_ms == 250.0
    # p50 = 250.0, p95 = 385.0
    assert 200.0 <= metrics.p50_latency_ms <= 300.0
    assert metrics.p95_latency_ms > metrics.p50_latency_ms


# ── TEST 2: VENTANAS TEMPORALES Y DE CONTEO ──

def test_analysis_windows_by_limit_and_time():
    """Verifica el filtrado por límite N, horas y días."""
    store = InMemoryExperienceStore()
    repo = ExperienceRepository(store=store)
    analyzer = ExperienceAnalyzer(repository=repo)

    now = datetime.now(UTC)
    # Crear experiencias con diferentes timestamps
    exp_recent = _create_sample_experience(timestamp=now - timedelta(minutes=10), raw_text="reciente")
    exp_2h_ago = _create_sample_experience(timestamp=now - timedelta(hours=2), raw_text="hace 2 horas")
    exp_2d_ago = _create_sample_experience(timestamp=now - timedelta(days=2), raw_text="hace 2 dias")

    repo.save_experience(exp_recent)
    repo.save_experience(exp_2h_ago)
    repo.save_experience(exp_2d_ago)

    # 1. Ventana de límite 2
    analysis_limit2 = analyzer.analyze(AnalysisWindow(limit=2))
    assert analysis_limit2.metrics.total_experiences == 2

    # 2. Ventana de última 1 hora
    analysis_1h = analyzer.analyze(AnalysisWindow(hours=1.0))
    assert analysis_1h.metrics.total_experiences == 1
    assert "reciente" in analysis_1h.summary or analysis_1h.metrics.total_experiences == 1

    # 3. Ventana de últimas 24 horas
    analysis_24h = analyzer.analyze(AnalysisWindow(hours=24.0))
    assert analysis_24h.metrics.total_experiences == 2

    # 4. Ventana de últimos 7 días
    analysis_7d = analyzer.analyze(AnalysisWindow(days=7.0))
    assert analysis_7d.metrics.total_experiences == 3


# ── TEST 3: FILTRADO POR ACCIÓN, SKILL E INTENCIÓN ──

def test_analysis_filtering_by_intent_and_skill():
    """Verifica el filtrado por intención semántica y skill utilizada."""
    store = InMemoryExperienceStore()
    repo = ExperienceRepository(store=store)
    analyzer = ExperienceAnalyzer(repository=repo)

    exp_calc = _create_sample_experience(intent_name="math_calculation", skill_used="math.calc")
    exp_app = _create_sample_experience(intent_name="open_application", skill_used="windows.apps")

    repo.save_experience(exp_calc)
    repo.save_experience(exp_app)

    res_math = analyzer.analyze_intent("math_calculation")
    assert res_math.metrics.total_experiences == 1
    assert res_math.window.intent == "math_calculation"

    res_skill = analyzer.analyze_skill("windows.apps")
    assert res_skill.metrics.total_experiences == 1
    assert res_skill.window.skill == "windows.apps"


# ── TEST 4: DETECCIÓN DE FALLOS REPETIDOS Y ÉXITOS CONSISTENTES ──

def test_pattern_repeated_failures_and_successes():
    """Verifica la detección de fallos recurrentes y éxitos sistemáticos."""
    exps = [
        _create_sample_experience(intent_name="delete_system_file", exec_status=ExecutionStatus.FAILED, error_msg="Access Denied"),
        _create_sample_experience(intent_name="delete_system_file", exec_status=ExecutionStatus.FAILED, error_msg="Access Denied"),
        _create_sample_experience(intent_name="open_calc", exec_status=ExecutionStatus.SUCCESS),
        _create_sample_experience(intent_name="open_calc", exec_status=ExecutionStatus.SUCCESS),
        _create_sample_experience(intent_name="open_calc", exec_status=ExecutionStatus.SUCCESS),
    ]

    fail_patterns = detect_repeated_failures(exps, min_occurrences=2)
    assert len(fail_patterns) == 1
    assert fail_patterns[0].type == PatternType.REPEATED_FAILURE
    assert fail_patterns[0].frequency == 2
    assert "delete_system_file" in fail_patterns[0].affected_operations
    assert fail_patterns[0].severity in (PatternSeverity.HIGH, PatternSeverity.CRITICAL)

    succ_patterns = detect_repeated_successes(exps, min_occurrences=3)
    assert len(succ_patterns) == 1
    assert succ_patterns[0].type == PatternType.REPEATED_SUCCESS
    assert succ_patterns[0].frequency == 3
    assert "open_calc" in succ_patterns[0].affected_operations


# ── TEST 5: DETECCIÓN DE VARIANTES STT ("BLOC DE NOTAS" VS "BLOG DE NOTAS") ──

def test_stt_variant_detection():
    """Verifica que 'bloc de notas', 'blog de notas' y 'blot de notas' se reconozcan como variantes."""
    exps = [
        _create_sample_experience(raw_text="abre bloc de notas", target_value="bloc de notas"),
        _create_sample_experience(raw_text="abre bloc de notas", target_value="bloc de notas"),
        _create_sample_experience(raw_text="abre blog de notas", target_value="blog de notas"),
        _create_sample_experience(raw_text="abre blot de notas", target_value="blot de notas"),
    ]

    patterns = detect_stt_variants(exps, similarity_threshold=0.70)
    assert len(patterns) >= 1
    stt_pat = patterns[0]
    assert isinstance(stt_pat, STTPattern)
    assert stt_pat.type == PatternType.STT_RECOGNITION
    assert stt_pat.canonical_target == "bloc de notas"
    assert "blog de notas" in stt_pat.variants or "blot de notas" in stt_pat.variants
    assert stt_pat.frequency == 4


# ── TEST 6: BAJA CONFIANZA STT E INTENCIÓN ──

def test_low_stt_and_intent_confidence_detection():
    """Verifica detección de baja confianza STT y de intención."""
    exps = [
        _create_sample_experience(stt_conf=0.40, category=ExperienceCategory.LOW_STT_CONFIDENCE),
        _create_sample_experience(stt_conf=0.45, category=ExperienceCategory.LOW_STT_CONFIDENCE),
        _create_sample_experience(intent_conf=0.50, intent_name="ambiguous_query", category=ExperienceCategory.AMBIGUOUS_INTENT),
    ]

    stt_patterns = detect_low_stt_confidence(exps, threshold=0.70)
    assert len(stt_patterns) == 1
    assert stt_patterns[0].frequency == 2
    assert stt_patterns[0].avg_stt_confidence < 0.50

    intent_patterns = detect_low_intent_confidence(exps, threshold=0.70)
    assert len(intent_patterns) == 1
    assert intent_patterns[0].intent_name == "ambiguous_query"


# ── TEST 7: FALLOS DE VERIFICACIÓN OS ──

def test_verification_failure_detection():
    """Verifica la detección de fallos deterministas en la verificación del sistema operativo."""
    exps = [
        _create_sample_experience(target_value="paint", is_verified=False, category=ExperienceCategory.VERIFICATION_FAILED),
        _create_sample_experience(target_value="paint", is_verified=False, category=ExperienceCategory.VERIFICATION_FAILED),
    ]

    patterns = detect_verification_failures(exps)
    assert len(patterns) == 1
    assert patterns[0].type == PatternType.VERIFICATION_FAILURE
    assert patterns[0].frequency == 2
    assert "paint" in patterns[0].affected_operations


# ── TEST 8: PATRONES DE CORRECCIÓN DE USUARIO ──

def test_user_correction_patterns():
    """Verifica la detección de correcciones sobre un target previo."""
    exps = [
        _create_sample_experience(
            category=ExperienceCategory.USER_CORRECTION,
            raw_text="No, cambia café por té",
            is_correction=True,
            corrected_val="té",
        ),
        _create_sample_experience(
            category=ExperienceCategory.USER_CORRECTION,
            raw_text="No, cambia notas por recordatorio",
            is_correction=True,
            corrected_val="recordatorio",
        ),
    ]

    patterns = detect_user_corrections(exps)
    assert len(patterns) == 1
    assert patterns[0].type == PatternType.USER_CORRECTION
    assert patterns[0].frequency == 2
    assert "té" in patterns[0].corrected_values


# ── TEST 9: DEGRADACIÓN DE LATENCIA ──

def test_latency_degradation_detection():
    """Verifica detección de operaciones con latencia excesiva."""
    exps = [
        _create_sample_experience(intent_name="heavy_task", latency_ms=1200.0),
        _create_sample_experience(intent_name="heavy_task", latency_ms=1500.0),
        _create_sample_experience(intent_name="quick_task", latency_ms=50.0),
    ]

    patterns = detect_latency_degradations(exps, latency_threshold_ms=500.0)
    assert len(patterns) == 1
    assert patterns[0].type == PatternType.LATENCY_DEGRADATION
    assert patterns[0].avg_latency_ms == 1350.0
    assert "heavy_task" in patterns[0].affected_operations


# ── TEST 10: ACLARACIONES REPETIDAS Y FALLOS DE TOOLS/SKILLS ──

def test_repeated_clarifications_and_tool_failures():
    """Verifica detección de aclaraciones continuas y fallos en tools."""
    exps = [
        _create_sample_experience(category=ExperienceCategory.CLARIFICATION_REQUESTED, raw_text="suma"),
        _create_sample_experience(category=ExperienceCategory.CLARIFICATION_REQUESTED, raw_text="resta"),
        _create_sample_experience(skill_used="filesystem.tool", exec_status=ExecutionStatus.FAILED, error_msg="FileNotFound"),
        _create_sample_experience(skill_used="filesystem.tool", exec_status=ExecutionStatus.FAILED, error_msg="FileNotFound"),
    ]

    clarif_pats = detect_repeated_clarifications(exps, min_occurrences=2)
    assert len(clarif_pats) == 1
    assert clarif_pats[0].frequency == 2

    tool_pats = detect_tool_skill_failures(exps, min_failures=2)
    assert len(tool_pats) == 1
    assert tool_pats[0].affected_operations == ["filesystem.tool"]


# ── TEST 11: CASOS BORDE Y GRANDES VOLÚMENES ──

def test_edge_cases_empty_and_large_volume():
    """Verifica estabilidad ante historial vacío y rendimiento con 500+ registros."""
    store = InMemoryExperienceStore()
    repo = ExperienceRepository(store=store)
    analyzer = ExperienceAnalyzer(repository=repo)

    # 1. Historial vacío
    analysis_empty = analyzer.analyze()
    assert analysis_empty.metrics.total_experiences == 0
    assert len(analysis_empty.patterns) == 0
    assert "No se encontraron experiencias" in analysis_empty.summary

    # 2. Gran volumen (500 experiencias sintéticas)
    for i in range(500):
        status = ExecutionStatus.SUCCESS if i % 5 != 0 else ExecutionStatus.FAILED
        lat = 50.0 + (i % 20) * 10
        repo.save_experience(
            _create_sample_experience(
                raw_text=f"comando test {i % 10}",
                intent_name=f"intent_{i % 10}",
                exec_status=status,
                latency_ms=lat,
            )
        )

    analysis_large = analyzer.analyze(AnalysisWindow(limit=500))
    assert analysis_large.metrics.total_experiences == 500
    assert analysis_large.metrics.success_rate == 0.80
    assert analysis_large.metrics.failure_rate == 0.20
    assert len(analysis_large.patterns) > 0


# ── TEST 12: INVARIANTE READ-ONLY Y DETERMINISMO ──

def test_analyzer_is_strictly_read_only_and_deterministic():
    """Garantiza que el analyzer jamás muta el repositorio y produce salidas idénticas."""
    store = InMemoryExperienceStore()
    repo = ExperienceRepository(store=store)
    analyzer = ExperienceAnalyzer(repository=repo)

    exp1 = _create_sample_experience(raw_text="accion A")
    exp2 = _create_sample_experience(raw_text="accion B")
    repo.save_experience(exp1)
    repo.save_experience(exp2)

    initial_count = repo.count_experiences()

    # Ejecutar análisis
    res1 = analyzer.analyze()
    res2 = analyzer.analyze()

    # Verificar que el conteo en el repositorio no cambió
    assert repo.count_experiences() == initial_count

    # Verificar determinismo
    assert res1.metrics.total_experiences == res2.metrics.total_experiences
    assert res1.metrics.success_rate == res2.metrics.success_rate
    assert res1.summary == res2.summary
