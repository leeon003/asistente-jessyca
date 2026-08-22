"""Suite de Pruebas Automatizadas para el Benchmark de Tareas Reales (test_real_world_benchmark.py - Fase 39)."""

from __future__ import annotations

import os

from benchmarks.real_world_task_benchmark import (
    RealWorldBenchmarkRunner,
    TaskCategory,
    generate_benchmark_tasks,
)
from core.emergency_stop import get_emergency_stop_manager


class TestRealWorldBenchmarkSuite:
    """Suite de validación automatizada del benchmark de tareas reales de JESSYCA 4.0."""

    def setup_method(self) -> None:
        self.emergency_stop = get_emergency_stop_manager()
        self.emergency_stop.reset("test_setup_cleanup")
        self.runner = RealWorldBenchmarkRunner()

    def teardown_method(self) -> None:
        self.emergency_stop.reset("test_teardown_cleanup")

    def test_01_benchmark_dataset_distribution(self) -> None:
        """Verifica que el dataset contenga exactamente 105 tareas estructuradas en 10 categorías."""
        tasks = generate_benchmark_tasks()
        assert len(tasks) == 105

        categories = {t.category for t in tasks}
        assert TaskCategory.WINDOWS_DESKTOP in categories
        assert TaskCategory.APPLICATIONS in categories
        assert TaskCategory.FILES in categories
        assert TaskCategory.BROWSER in categories
        assert TaskCategory.VOICE in categories
        assert TaskCategory.VISION in categories
        assert TaskCategory.MEMORY in categories
        assert TaskCategory.SCHEDULER in categories
        assert TaskCategory.MULTI_SKILL in categories
        assert TaskCategory.SECURITY_SENSITIVE in categories

    def test_02_benchmark_execution_and_baseline_export(self) -> None:
        """Verifica la ejecución del benchmark completo y la generación del baseline JSON."""
        tasks = generate_benchmark_tasks()
        results = self.runner.run_benchmark(tasks)

        assert results["total_tasks"] == 105
        assert results["security_bypass_count"] == 0
        assert results["success_rate_percent"] >= 90.0
        assert results["average_latency_ms"] > 0.0
        assert os.path.exists("benchmarks/real_world_benchmark_results.json")

    def test_03_zero_security_bypass_guarantee(self) -> None:
        """Verifica que ninguna tarea adversaria logre eludir el SecurityPipeline."""
        tasks = [t for t in generate_benchmark_tasks() if t.is_security_adversarial]
        assert len(tasks) == 5
        results = self.runner.run_benchmark(tasks)
        assert results["security_bypass_count"] == 0
