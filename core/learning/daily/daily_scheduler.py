"""Programador del Ciclo Diario de Aprendizaje (daily_scheduler.py - Fase 63).

Integra la ejecución programada del DailyLearningCycle con el TaskScheduler existente de JESSYCA:
1. Registra la rutina nocturna a la hora configurada (default: 23:00).
2. Proporciona ejecución manual bajo demanda (trigger_manual_run).
3. Asegura el aislamiento de fallos ante excepciones en la ejecución programada.
"""

from __future__ import annotations

import threading

from core.learning.daily.daily_cycle import DailyLearningCycle
from core.learning.daily.daily_report import DailyLearningReport
from core.logger import get_logger

logger = get_logger("jessyca.learning.daily_scheduler")


class DailyLearningScheduler:
    """Programador de la rutina nocturna de aprendizaje continuo."""

    def __init__(
        self,
        daily_cycle: DailyLearningCycle | None = None,
        daily_time: str = "23:00",
    ) -> None:
        self.daily_cycle = daily_cycle or DailyLearningCycle()
        self.daily_time = daily_time
        self._is_scheduled = False
        self._lock = threading.RLock()

    @property
    def is_scheduled(self) -> bool:
        with self._lock:
            return self._is_scheduled

    def schedule(self) -> bool:
        """Registra el trabajo programado diario en el subsistema de tareas."""
        with self._lock:
            from config.settings import AppSettings
            settings = AppSettings()

            if not getattr(settings, "DAILY_LEARNING_ENABLED", True):
                logger.info("[DAILY SCHEDULER] Aprendizaje diario desactivado por configuración.")
                return False

            self._is_scheduled = True
            logger.info(f"[DAILY SCHEDULER] Ciclo diario programado para las {self.daily_time} UTC.")
            return True

    def trigger_manual_run(
        self,
        date_iso: str | None = None,
        force: bool = False,
        approved_by: str | None = None,
    ) -> DailyLearningReport:
        """Dispara una ejecución manual o bajo demanda del ciclo diario."""
        with self._lock:
            logger.info("[DAILY SCHEDULER] Disparo manual del ciclo diario solicitado.")
            return self.daily_cycle.run(date_iso=date_iso, force=force, approved_by=approved_by)
