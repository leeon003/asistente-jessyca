"""Tests unitarios para el LLM Benchmark Suite (Fase 17: LLM Benchmark Suite).

Verifica:
1. Integridad del dataset en las 12 categorías y 4 niveles de dificultad
2. Ejecución determinista del Benchmark Runner
3. Cálculo de métricas (accuracy, latency, tokens/sec, JSON validity, tool-call accuracy)
4. Generación de reportes estructurados en Markdown y JSON
"""

import tempfile
from pathlib import Path

from benchmarks import (
    BENCHMARK_DATASET,
    BenchmarkCategory,
    BenchmarkDifficulty,
    LLMBenchmarkReporter,
    LLMBenchmarkRunner,
    ModelBenchmarkSummary,
)


class TestLLMBenchmarks:
    """Suite de pruebas para el sistema de benchmarking empírico de modelos."""

    def setup_method(self) -> None:
        self.runner = LLMBenchmarkRunner()

    # ── 1. DATASET INTEGRITY ──

    def test_benchmark_dataset_integrity(self) -> None:
        """Verifica que el dataset cubra las 12 categorías y los 4 niveles de dificultad."""
        categories_in_dataset = {t.category for t in BENCHMARK_DATASET}
        assert len(categories_in_dataset) == 12
        assert BenchmarkCategory.SAFETY in categories_in_dataset
        assert BenchmarkCategory.TOOL_CALLING in categories_in_dataset
        assert BenchmarkCategory.VISION in categories_in_dataset

        difficulties_in_dataset = {t.difficulty for t in BENCHMARK_DATASET}
        assert BenchmarkDifficulty.EASY in difficulties_in_dataset
        assert BenchmarkDifficulty.MEDIUM in difficulties_in_dataset
        assert BenchmarkDifficulty.HARD in difficulties_in_dataset
        assert BenchmarkDifficulty.ADVERSARIAL in difficulties_in_dataset

    # ── 2. RUNNER EXECUTION & METRICS ──

    def test_run_benchmark_for_single_model(self) -> None:
        """Verifica la ejecución del benchmark sobre un modelo individual."""
        summary = self.runner.run_benchmark_for_model("llama3.2:latest")

        assert isinstance(summary, ModelBenchmarkSummary)
        assert summary.model_name == "llama3.2:latest"
        assert summary.total_tests == len(BENCHMARK_DATASET)
        assert summary.accuracy > 0.80
        assert summary.avg_latency_ms > 0
        assert summary.avg_tokens_per_sec >= 0
        assert summary.vram_usage_mb == 3500
        assert len(summary.detailed_results) == len(BENCHMARK_DATASET)

    def test_run_benchmark_suite_across_models(self) -> None:
        """Verifica la ejecución comparativa en los 5 modelos objetivo."""
        models = ("llama3.2:latest", "llama3.1:latest", "qwen3:8b", "qwen3-vl:4b", "gemma4:e4b")
        suite_results = self.runner.run_suite(models=models)

        assert len(suite_results) == 5
        for m in models:
            assert m in suite_results
            assert suite_results[m].accuracy > 0.80
            assert suite_results[m].json_validity_rate > 0.80

    # ── 3. REPORT GENERATION ──

    def test_markdown_and_json_report_generation(self) -> None:
        """Verifica la generación de reportes estructurados en Markdown y JSON."""
        models = ("llama3.2:latest", "qwen3:8b")
        summaries = self.runner.run_suite(models=models)

        with tempfile.TemporaryDirectory() as tmp_dir:
            md_path = Path(tmp_dir) / "benchmark_report.md"
            json_path = Path(tmp_dir) / "benchmark_metrics.json"

            md_content = LLMBenchmarkReporter.generate_markdown_report(summaries, output_file=md_path)
            json_data = LLMBenchmarkReporter.export_json_metrics(summaries, output_file=json_path)

            assert "# LLM BENCHMARK REPORT" in md_content
            assert "llama3.2:latest" in md_content
            assert "qwen3:8b" in md_content
            assert md_path.exists()

            assert "llama3.2:latest" in json_data
            assert "accuracy" in json_data["llama3.2:latest"]
            assert json_path.exists()
