"""Modelos inmutables de telemetría y estadísticas para Model Performance Learning (performance_models.py - Fase 26).

Define las estructuras de datos para registro de inferencias y métricas agregadas por modelo y tipo de tarea.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. MODEL PERFORMANCE LEARNING != SECURITY AUTHORIZATION (No otorga permisos ni modifica SecurityPipeline).
2. Sanitización estricta: Todo mensaje de error o metadato se procesa por SecretRedactor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.llm.smart_routing_models import TaskType


@dataclass(frozen=True)
class InferenceExecutionRecord:
    """Registro inmutable de una inferencia o ejecución de modelo LLM."""

    model_name: str
    task_type: TaskType
    latency_ms: float
    tokens: int = 0
    success: bool = True
    error_message: str | None = None
    is_timeout: bool = False
    confidence: float = 1.0
    vram_mb: float = 0.0
    is_fallback: bool = False
    validation_passed: bool = True
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "task_type": str(self.task_type),
            "latency_ms": round(self.latency_ms, 2),
            "tokens": self.tokens,
            "success": self.success,
            "error_message": self.error_message,
            "is_timeout": self.is_timeout,
            "confidence": round(self.confidence, 4),
            "vram_mb": round(self.vram_mb, 2),
            "is_fallback": self.is_fallback,
            "validation_passed": self.validation_passed,
            "timestamp": self.timestamp.isoformat(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ModelPerformanceStats:
    """Estadísticas agregadas de rendimiento de un modelo para un tipo de tarea o global."""

    model_name: str
    task_type: TaskType | None
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    timeout_count: int = 0
    fallback_count: int = 0
    success_rate: float = 1.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    avg_tokens: float = 0.0
    avg_vram_mb: float = 0.0
    avg_confidence: float = 1.0
    validation_pass_rate: float = 1.0
    is_cold_start: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "task_type": str(self.task_type) if self.task_type else "ALL",
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "timeout_count": self.timeout_count,
            "fallback_count": self.fallback_count,
            "success_rate": round(self.success_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "avg_tokens": round(self.avg_tokens, 2),
            "avg_vram_mb": round(self.avg_vram_mb, 2),
            "avg_confidence": round(self.avg_confidence, 4),
            "validation_pass_rate": round(self.validation_pass_rate, 4),
            "is_cold_start": self.is_cold_start,
        }
