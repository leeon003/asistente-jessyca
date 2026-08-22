"""Administrador y gobernador de presupuesto de memoria de video (VRAMGovernor - Fase 3: Model Manager + VRAM Governor).

Diseñado específicamente para hardware con memoria dedicada acotada (e.g. NVIDIA RTX 3060 12 GB).
Garantiza que no se sobrecargue la VRAM y calcula planes de desalojo deterministas (LRU / Prioridad)
para prevenir fallos Out-Of-Memory (OOM).

GARANTÍA DE SEGURIDAD:
Este módulo contiene lógica de cálculo y asignación de presupuesto de memoria.
NO ejecuta código no confiable, NO ejecuta herramientas de sistema.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import ClassVar

from core.llm.model_profile import ModelProfile
from core.logger import get_logger

logger = get_logger("jessyca.llm.vram")

# Presupuesto por defecto para RTX 3060 (12 GB = 12,288 MB)
DEFAULT_TOTAL_VRAM_MB = 12288
DEFAULT_RESERVED_SYSTEM_VRAM_MB = 1536  # Reservado para Windows DWM, display y aplicaciones


@dataclass(frozen=True)
class VRAMBudgetReport:
    """Informe inmutable del estado del presupuesto de VRAM."""

    total_vram_mb: int
    reserved_system_mb: int
    usable_budget_mb: int
    currently_allocated_mb: int
    remaining_budget_mb: int
    loaded_models_count: int


@dataclass
class ModelUsageRecord:
    """Registro mutable de uso temporal de un modelo para políticas de desalojo."""

    model_name: str
    vram_estimate_mb: int
    priority: int = 1
    last_used_timestamp: float = 0.0


class VRAMGovernor:
    """Gobernador de memoria de video con control de presupuesto y cálculo de desalojos LRU."""

    _instance: ClassVar[VRAMGovernor | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        total_vram_mb: int = DEFAULT_TOTAL_VRAM_MB,
        reserved_system_mb: int = DEFAULT_RESERVED_SYSTEM_VRAM_MB,
        vram_limit_mb: float | None = None,
    ) -> None:
        self._lock = threading.RLock()
        if vram_limit_mb is not None:
            self.vram_limit_mb = float(vram_limit_mb)
            self.total_vram_mb = int(vram_limit_mb)
        else:
            self.total_vram_mb = total_vram_mb
            self.vram_limit_mb = float(total_vram_mb)
        self.reserved_system_mb = reserved_system_mb
        self.usable_budget_mb = max(0, self.total_vram_mb - reserved_system_mb)
        self._loaded_models: dict[str, ModelUsageRecord] = {}

    def can_allocate(self, mb: float) -> bool:
        """Determina si una cantidad de MB puede ser asignada dentro del límite de VRAM."""
        with self._lock:
            allocated = sum(m.vram_estimate_mb for m in self._loaded_models.values())
            return (allocated + mb) <= self.vram_limit_mb

    @classmethod
    def get_instance(cls) -> VRAMGovernor:
        """Obtiene la instancia singleton global del gobernador de VRAM."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = VRAMGovernor()
            return cls._instance

    def get_budget_report(self) -> VRAMBudgetReport:
        """Genera un informe completo del estado de asignación de VRAM."""
        with self._lock:
            allocated = sum(m.vram_estimate_mb for m in self._loaded_models.values())
            remaining = max(0, self.usable_budget_mb - allocated)
            return VRAMBudgetReport(
                total_vram_mb=self.total_vram_mb,
                reserved_system_mb=self.reserved_system_mb,
                usable_budget_mb=self.usable_budget_mb,
                currently_allocated_mb=allocated,
                remaining_budget_mb=remaining,
                loaded_models_count=len(self._loaded_models),
            )

    def can_fit(self, model_profile: ModelProfile) -> bool:
        """Determina si el modelo solicitado cabe en la VRAM libre sin desalojar."""
        with self._lock:
            needed_mb = model_profile.vram_estimate_mb or 4000
            allocated = sum(m.vram_estimate_mb for m in self._loaded_models.values())
            # Si ya está cargado, no requiere VRAM adicional
            if model_profile.name in self._loaded_models:
                return True
            return (allocated + needed_mb) <= self.usable_budget_mb

    def calculate_eviction_plan(
        self,
        target_model: ModelProfile,
    ) -> list[str]:
        """Calcula la lista óptima de modelos a desalojar (LRU / menor prioridad) para dar cabida al modelo solicitado."""
        with self._lock:
            if target_model.name in self._loaded_models:
                return []

            needed_mb = target_model.vram_estimate_mb or 4000
            if needed_mb > self.usable_budget_mb:
                logger.warning(
                    f"[VRAM GOVERNOR] El modelo '{target_model.name}' requiere {needed_mb}MB, "
                    f"lo cual excede el presupuesto total utilizable ({self.usable_budget_mb}MB)."
                )

            allocated = sum(m.vram_estimate_mb for m in self._loaded_models.values())
            deficit_mb = (allocated + needed_mb) - self.usable_budget_mb

            if deficit_mb <= 0:
                return []

            # Ordenar candidatos a desalojo:
            # 1. Menor prioridad primero (número más bajo)
            # 2. Menos recientemente usado (LRU timestamp más bajo)
            candidates = sorted(
                self._loaded_models.values(),
                key=lambda m: (m.priority, m.last_used_timestamp)
            )

            to_evict: list[str] = []
            freed_mb = 0

            for candidate in candidates:
                to_evict.append(candidate.model_name)
                freed_mb += candidate.vram_estimate_mb
                if freed_mb >= deficit_mb:
                    break

            logger.info(
                f"[VRAM GOVERNOR] Para cargar '{target_model.name}' ({needed_mb}MB), "
                f"se requiere desalojar: {to_evict} (liberando {freed_mb}MB)"
            )
            return to_evict

    def register_loaded(
        self,
        model_name: str,
        vram_mb: int,
        priority: int = 1,
        timestamp: float = 0.0,
    ) -> None:
        """Registra o actualiza un modelo como residente en VRAM."""
        with self._lock:
            self._loaded_models[model_name] = ModelUsageRecord(
                model_name=model_name,
                vram_estimate_mb=vram_mb,
                priority=priority,
                last_used_timestamp=timestamp,
            )
            logger.debug(f"[VRAM GOVERNOR] Modelo registrado en VRAM: '{model_name}' ({vram_mb}MB)")

    def register_unloaded(self, model_name: str) -> bool:
        """Registra la descarga de un modelo liberando su cuota de VRAM."""
        with self._lock:
            if model_name in self._loaded_models:
                del self._loaded_models[model_name]
                logger.debug(f"[VRAM GOVERNOR] Modelo descargado de VRAM: '{model_name}'")
                return True
            return False

    def touch_model(self, model_name: str, timestamp: float) -> None:
        """Actualiza el timestamp de último uso de un modelo residente."""
        with self._lock:
            if model_name in self._loaded_models:
                self._loaded_models[model_name].last_used_timestamp = timestamp

    def reset(self) -> None:
        """Limpia el estado interno del gobernador."""
        with self._lock:
            self._loaded_models.clear()
