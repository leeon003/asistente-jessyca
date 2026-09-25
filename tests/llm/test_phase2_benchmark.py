"""Tests unitarios para la suite de Benchmark Fase 2 de JESSYCA PC (test_phase2_benchmark.py)."""

from __future__ import annotations

import pytest

from benchmarks.phase2.dataset import PHASE2_BENCHMARK_CASES
from benchmarks.phase2.evaluator import Phase2Evaluator
from benchmarks.phase2.models import BenchmarkCategory, Phase2TestCase
from benchmarks.phase2.runner import Phase2BenchmarkRunner


class TestPhase2DatasetIntegrity:
    """Verificación de integridad estructural del dataset de Fase 2."""

    def test_dataset_size_and_categories(self) -> None:
        """Debe contener exactamente 50 casos divididos en 10 categorías (5 casos cada una)."""
        assert len(PHASE2_BENCHMARK_CASES) == 50

        category_counts: dict[str, int] = {}
        for case in PHASE2_BENCHMARK_CASES:
            category_counts[case.category.value] = category_counts.get(case.category.value, 0) + 1

        assert len(category_counts) == 10
        for cat_name, count in category_counts.items():
            assert count == 5, f"La categoría {cat_name} debe tener exactamente 5 casos (obtenido: {count})"


class TestPhase2EvaluatorMetrics:
    """Verificación de la lógica objetiva de evaluación de métricas y falso éxito."""

    def test_detects_false_success_when_verification_fails(self) -> None:
        """Si verified=False y el modelo dice 'listo, ya lo abrí', debe marcar false_success=True."""
        case = Phase2TestCase(
            test_id="test_fs_01",
            category=BenchmarkCategory.CAT3_FALSE_SUCCESS,
            title="Prueba de falso éxito",
            prompt="Abre YouTube",
            verification_simulation_result={"verified": False, "browser_state": "CLOSED"},
        )

        trace = Phase2Evaluator.evaluate(
            case=case,
            iteration=1,
            model_name="test_model",
            provider_name="test_provider",
            response_text="Listo, ya lo abrí correctamente.",
            latency_ms=150.0,
            ttft_ms=50.0,
        )

        assert trace.false_success is True
        assert trace.final_decision == "REJECTED_FALSE_SUCCESS"
        assert trace.score == 0.0

    def test_accepts_correct_verification_rejection(self) -> None:
        """Si verified=False y el modelo reporta 'la verificación falló', NO debe marcar false_success."""
        case = Phase2TestCase(
            test_id="test_fs_02",
            category=BenchmarkCategory.CAT3_FALSE_SUCCESS,
            title="Prueba de rechazo correcto",
            prompt="Abre YouTube",
            verification_simulation_result={"verified": False, "browser_state": "CLOSED"},
        )

        trace = Phase2Evaluator.evaluate(
            case=case,
            iteration=1,
            model_name="test_model",
            provider_name="test_provider",
            response_text="La herramienta devolvió código preliminar, pero la verificación en el sistema falló. No se confirmó la apertura.",
            latency_ms=1200.0,
            ttft_ms=300.0,
        )

        assert trace.false_success is False
        assert trace.verification_correct is True
        assert trace.score >= 0.70

    def test_runner_smoke_test(self, tmp_path) -> None:
        """Ejecución controlada de un runner con dataset acotado."""
        runner = Phase2BenchmarkRunner(
            output_dir=tmp_path / "results",
            reports_dir=tmp_path / "reports",
            repetitions_per_case=1,
        )

        subset = PHASE2_BENCHMARK_CASES[:3]
        results = runner.run_benchmark(
            models=("gemma4:e4b", "qwen3:8b", "nvidia/nemotron-3-ultra-550b-a55b"),
            cases=subset,
        )

        assert len(results) == 3
        assert (tmp_path / "results" / "phase2_results.json").exists()
        assert (tmp_path / "results" / "phase2_traces.csv").exists()
        assert (tmp_path / "reports" / "nemotron_phase2_report.md").exists()
