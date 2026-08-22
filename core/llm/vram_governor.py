"""Módulo de reexportación para VRAMGovernor (vram_governor.py).

Garantiza compatibilidad de importación directa desde 'core.llm.vram_governor'.
"""

from __future__ import annotations

from core.llm.vram_manager import (
    DEFAULT_RESERVED_SYSTEM_VRAM_MB,
    DEFAULT_TOTAL_VRAM_MB,
    ModelUsageRecord,
    VRAMBudgetReport,
    VRAMGovernor,
)

__all__ = [
    "DEFAULT_RESERVED_SYSTEM_VRAM_MB",
    "DEFAULT_TOTAL_VRAM_MB",
    "ModelUsageRecord",
    "VRAMBudgetReport",
    "VRAMGovernor",
]
