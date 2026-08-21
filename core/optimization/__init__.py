"""Paquete de Optimización de Rendimiento y Recursos para Jessyca 3.0 (Fase 18: System Optimization).

Exporta utilidades de Safe Caching y Optimizador de VRAM (RTX 3060 12GB).
"""

from core.optimization.safe_caching import (
    CacheEntry,
    SafeCache,
)
from core.optimization.vram_optimizer import (
    CoResidencyPlan,
    VRAMOptimizer,
)

__all__ = [
    # Caching
    "CacheEntry",
    "SafeCache",
    # VRAM Optimizer
    "CoResidencyPlan",
    "VRAMOptimizer",
]
