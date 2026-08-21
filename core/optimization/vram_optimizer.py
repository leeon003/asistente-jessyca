"""Optimizador de VRAM y Prevención de Thrashing (vram_optimizer.py - Fase 18).

Especializado en la gestión eficiente de memoria de video para la GPU NVIDIA RTX 3060 (12 GB).
Evita recargas cíclicas de modelos (thrashing) y orquesta consensos selectivos basados en confianza.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from core.logger import get_logger

logger = get_logger("jessyca.optimization.vram")


@dataclass(frozen=True)
class CoResidencyPlan:
    """Plan determinista de residencia conjunta de modelos en 12 GB de VRAM."""

    resident_models: tuple[str, ...]
    total_allocated_mb: int
    usable_limit_mb: int
    is_safe: bool


class VRAMOptimizer:
    """Optimizador de asignación de GPU y amortiguador anti-thrashing."""

    # Presupuesto: 12,288 MB Total - 1,536 MB Sistema = 10,752 MB utilizables
    USABLE_VRAM_LIMIT_MB = 10752
    MIN_THRASHING_INTERVAL_SECONDS = 5.0

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_evicted_time: dict[str, float] = {}
        self._model_vram_weights: dict[str, int] = {
            "llama3.2:latest": 3500,
            "llama3.1:latest": 8000,
            "qwen3:8b": 6000,
            "qwen3-vl:4b": 4500,
            "gemma4:e4b": 3800,
        }

    def evaluate_co_residency(self, models: list[str] | tuple[str, ...]) -> CoResidencyPlan:
        """Determina si un conjunto de modelos puede co-existir de forma segura en la VRAM de la RTX 3060."""
        with self._lock:
            total_req = sum(self._model_vram_weights.get(m, 4000) for m in models)
            is_safe = total_req <= self.USABLE_VRAM_LIMIT_MB

            return CoResidencyPlan(
                resident_models=tuple(models),
                total_allocated_mb=total_req,
                usable_limit_mb=self.USABLE_VRAM_LIMIT_MB,
                is_safe=is_safe,
            )

    def record_eviction(self, model_name: str) -> None:
        """Registra el timestamp de desalojo de un modelo para control de thrashing."""
        with self._lock:
            self._last_evicted_time[model_name] = time.monotonic()

    def is_thrashing_risk(self, model_name: str) -> bool:
        """Comprueba si un modelo fue desalojado hace menos del umbral anti-thrashing."""
        with self._lock:
            last_evicted = self._last_evicted_time.get(model_name)
            if last_evicted is None:
                return False
            elapsed = time.monotonic() - last_evicted
            return elapsed < self.MIN_THRASHING_INTERVAL_SECONDS

    def should_trigger_consensus(self, single_model_confidence: float, confidence_threshold: float = 0.85) -> bool:
        """Gating de consenso selectivo: evita inferencia redundante multi-modelo si el modelo principal tiene alta confianza."""
        # Si la confianza del modelo primario es alta (>= 0.85), NO se activa consenso para ahorrar VRAM y latencia
        return single_model_confidence < confidence_threshold
