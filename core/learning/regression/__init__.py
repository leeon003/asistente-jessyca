"""Paquete de Aprendizaje de Regresiones (core/learning/regression - Fase 61).

Exporta modelos, validadores, generadores de pruebas, almacenes y motor de regresión
del JESSYCA EXPERIENCE & LEARNING ENGINE.
"""

from __future__ import annotations

from core.learning.regression.regression_engine import RegressionEngine
from core.learning.regression.regression_models import (
    RegressionCase,
    RegressionCategory,
    RegressionSeverity,
    RegressionStatus,
    RegressionSuiteStats,
)
from core.learning.regression.regression_store import (
    InMemoryRegressionStore,
    IRegressionStore,
    SQLiteRegressionStore,
)
from core.learning.regression.regression_validator import (
    FORBIDDEN_DESTRUCTIVE_PATTERNS,
    RegressionValidator,
)
from core.learning.regression.test_generator import RegressionTestGenerator

__all__ = [
    "FORBIDDEN_DESTRUCTIVE_PATTERNS",
    "InMemoryRegressionStore",
    "IRegressionStore",
    "RegressionCase",
    "RegressionCategory",
    "RegressionEngine",
    "RegressionSeverity",
    "RegressionStatus",
    "RegressionSuiteStats",
    "RegressionTestGenerator",
    "RegressionValidator",
    "SQLiteRegressionStore",
]
