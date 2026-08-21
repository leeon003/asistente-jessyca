"""Modelos de datos y métricas para Smart Model Routing 2.0 (smart_routing_models.py - Fase 25).

Define las estructuras inmutables para decisiones de enrutamiento multidimensional,
desglose de puntuaciones y seguimiento de rendimiento histórico de modelos.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. MODEL ROUTER != AUTHORIZATION
2. Capacidades declaradas son estrictas y no negociables (Vision requiere modelo con visión).
3. Fallback determinista y anti-thrashing de VRAM.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.llm.model_profile import ModelProfile


class TaskType(StrEnum):
    """Categorías funcionales de tareas para enrutamiento de modelos."""

    CLASSIFICATION = "classification"        # Clasificación rápida, detección de patrones
    SIMPLE_TASK = "simple_task"              # Órdenes directas de baja complejidad
    CONVERSATION = "conversation"            # Diálogo fluido, preguntas y respuestas generales
    REASONING = "reasoning"                  # Razonamiento deductivo / inductivo profundo
    PLANNING = "planning"                    # Descomposición de planes y secuencias de pasos
    ANALYSIS_VERIFICATION = "analysis"       # Análisis estructurado y verificación de intenciones
    VISION = "vision"                        # Procesamiento multimodal / análisis de imágenes


class TaskComplexity(StrEnum):
    """Niveles de complejidad computacional de una tarea."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ModelRoutingDecision:
    """Decisión inmutable y explicable emitida por el Smart Model Router 2.0."""

    selected_model: ModelProfile
    task_type: TaskType
    complexity: TaskComplexity
    confidence: float = 1.0
    reason: str = ""
    candidate_scores: dict[str, float] = field(default_factory=dict)
    fallback_chain: tuple[str, ...] = field(default_factory=tuple)
    vram_allocated_mb: int = 0
    latency_estimate_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_model": self.selected_model.name,
            "task_type": str(self.task_type),
            "complexity": str(self.complexity),
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "candidate_scores": {k: round(v, 4) for k, v in self.candidate_scores.items()},
            "fallback_chain": list(self.fallback_chain),
            "vram_allocated_mb": self.vram_allocated_mb,
            "latency_estimate_ms": round(self.latency_estimate_ms, 2),
            "timestamp": self.timestamp.isoformat(),
            "metadata": dict(self.metadata),
        }


@dataclass
class ModelTaskStat:
    """Estadísticas acumulativas de rendimiento de un modelo en un tipo de tarea."""

    total_attempts: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    total_tokens: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_attempts == 0:
            return 1.0  # Sin historial -> asumir confianza por defecto
        return self.success_count / self.total_attempts

    @property
    def avg_latency_ms(self) -> float:
        if self.total_attempts == 0:
            return 50.0
        return self.total_latency_ms / self.total_attempts


class ModelPerformanceTracker:
    """Rastreador thread-safe de métricas históricas de rendimiento por modelo y tarea."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # model_name -> task_type -> ModelTaskStat
        self._stats: dict[str, dict[TaskType, ModelTaskStat]] = {}

    def record_result(
        self,
        model_name: str,
        task_type: TaskType,
        latency_ms: float,
        success: bool,
        tokens: int = 0,
    ) -> None:
        """Registra el resultado de una inferencia completada."""
        m_name = model_name.strip().lower()
        with self._lock:
            if m_name not in self._stats:
                self._stats[m_name] = {}
            if task_type not in self._stats[m_name]:
                self._stats[m_name][task_type] = ModelTaskStat()

            stat = self._stats[m_name][task_type]
            stat.total_attempts += 1
            if success:
                stat.success_count += 1
            else:
                stat.failure_count += 1
            stat.total_latency_ms += latency_ms
            stat.total_tokens += tokens

    def get_success_rate(self, model_name: str, task_type: TaskType) -> float:
        """Retorna la tasa de éxito histórica del modelo para el tipo de tarea."""
        m_name = model_name.strip().lower()
        with self._lock:
            return self._stats.get(m_name, {}).get(task_type, ModelTaskStat()).success_rate

    def get_avg_latency_ms(self, model_name: str, task_type: TaskType) -> float:
        """Retorna la latencia promedio histórica del modelo."""
        m_name = model_name.strip().lower()
        with self._lock:
            return self._stats.get(m_name, {}).get(task_type, ModelTaskStat()).avg_latency_ms

    def reset(self) -> None:
        """Limpia las estadísticas históricas para pruebas."""
        with self._lock:
            self._stats.clear()
