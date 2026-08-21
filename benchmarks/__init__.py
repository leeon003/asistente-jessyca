"""Paquete central de Benchmarking de LLMs para Jessyca 3.0 (Fase 17: LLM Benchmark Suite).

Exporta dataset reproducible, ejecutor de suite y generador de reportes.
"""

from benchmarks.llm_benchmark_dataset import (
    BENCHMARK_DATASET,
    BenchmarkCategory,
    BenchmarkDifficulty,
    BenchmarkTestCase,
)
from benchmarks.llm_benchmark_reporter import LLMBenchmarkReporter
from benchmarks.llm_benchmark_runner import (
    TARGET_BENCHMARK_MODELS,
    LLMBenchmarkRunner,
    ModelBenchmarkSummary,
    TestCaseExecutionResult,
)

__all__ = [
    # Dataset
    "BENCHMARK_DATASET",
    "BenchmarkCategory",
    "BenchmarkDifficulty",
    "BenchmarkTestCase",
    # Runner
    "TARGET_BENCHMARK_MODELS",
    "LLMBenchmarkRunner",
    "ModelBenchmarkSummary",
    "TestCaseExecutionResult",
    # Reporter
    "LLMBenchmarkReporter",
]
