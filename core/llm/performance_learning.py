"""Motor de aprendizaje y observación del rendimiento de modelos LLM (performance_learning.py - Fase 26).

Coordina el registro de inferencias, persistencia, cálculo de estadísticas agregadas y
optimización continua del enrutador de modelos.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. MODEL PERFORMANCE LEARNING != AUTHORIZATION
2. El aprendizaje NUNCA puede modificar SecurityPipeline, RiskEngine, PermissionManager,
   ConfirmationManager o EmergencyStopManager.
3. El aprendizaje ÚNICAMENTE puede optimizar la selección de modelos compatibles.
"""

from __future__ import annotations

import threading
from typing import Any, ClassVar

from core.llm.performance_models import (
    InferenceExecutionRecord,
    ModelPerformanceStats,
)
from core.llm.performance_store import ModelPerformanceStore
from core.llm.smart_routing_models import TaskType
from core.logger import get_logger

logger = get_logger("jessyca.llm.performance_learning")


class ModelPerformanceLearner:
    """Coordinador de observación, persistencia y análisis de rendimiento de modelos."""

    _instance: ClassVar[ModelPerformanceLearner | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, store: ModelPerformanceStore | None = None) -> None:
        self._lock = threading.RLock()
        self.store = store or ModelPerformanceStore()

    @classmethod
    def get_instance(cls) -> ModelPerformanceLearner:
        """Obtiene la instancia singleton global del motor de aprendizaje."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = ModelPerformanceLearner()
            return cls._instance

    def record_inference(
        self,
        model_name: str,
        task_type: TaskType,
        latency_ms: float,
        tokens: int = 0,
        success: bool = True,
        error_message: str | None = None,
        is_timeout: bool = False,
        confidence: float = 1.0,
        vram_mb: float = 0.0,
        is_fallback: bool = False,
        validation_passed: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Registra una inferencia en el almacén persistente con sanitización."""
        record = InferenceExecutionRecord(
            model_name=model_name,
            task_type=task_type,
            latency_ms=latency_ms,
            tokens=tokens,
            success=success,
            error_message=error_message,
            is_timeout=is_timeout,
            confidence=confidence,
            vram_mb=vram_mb,
            is_fallback=is_fallback,
            validation_passed=validation_passed,
            metadata=metadata or {},
        )
        self.store.record_execution(record)

    def get_model_stats(
        self,
        model_name: str,
        task_type: TaskType | None = None,
    ) -> ModelPerformanceStats:
        """Obtiene las estadísticas de un modelo para un tipo de tarea o global."""
        return self.store.get_stats(model_name=model_name, task_type=task_type)

    def get_task_ranking(self, task_type: TaskType) -> list[tuple[str, float]]:
        """Genera un ranking de modelos para un tipo de tarea según su tasa de éxito y latencia."""
        task_stats = self.store.get_aggregated_task_stats(task_type=task_type)
        ranked: list[tuple[str, float]] = []

        for model_name, stats in task_stats.items():
            if stats.total_executions == 0:
                score = 0.50
            else:
                # Puntuación combinada: tasa de éxito (70%) + eficiencia de latencia (30%)
                lat_score = max(0.10, 1.0 - (stats.avg_latency_ms / 1000.0))
                score = (0.70 * stats.success_rate) + (0.30 * lat_score)
            ranked.append((model_name, score))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def get_performance_summary(self) -> dict[str, Any]:
        """Retorna un resumen global de telemetría de rendimiento."""
        recent = self.store.get_recent_records(limit=20)
        return {
            "recent_inferences_count": len(recent),
            "recent_records": [r.to_dict() for r in recent],
        }

    def reset(self) -> None:
        """Limpia el almacenamiento para pruebas."""
        self.store.clear()


def get_model_performance_learner() -> ModelPerformanceLearner:
    """Acceso helper al singleton global de ModelPerformanceLearner."""
    return ModelPerformanceLearner.get_instance()
