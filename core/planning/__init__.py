"""Sub-sistema de Planificación y Ejecución Estructurada (Fase 23).

Exporta las clases, modelos y utilidades para construir, validar y ejecutar planes
acíclicos (DAG), multi-paso, gobernados y verificables.

INVARIANTE DE SEGURIDAD:
PLANNER != AUTHORIZATION
"""

from core.planning.plan_builder import PlanBuilder
from core.planning.plan_executor import PlanExecutor
from core.planning.plan_models import (
    ExecutionPlan,
    PlanExecutionResult,
    PlanStatus,
    PlanStep,
    PlanStepResult,
    StepStatus,
)
from core.planning.plan_validator import PlanValidationError, PlanValidator
from core.planning.planning_engine import (
    PlanningEngine,
    get_planning_engine,
)

__all__ = [
    "ExecutionPlan",
    "PlanBuilder",
    "PlanExecutionResult",
    "PlanExecutor",
    "PlanStatus",
    "PlanStep",
    "PlanStepResult",
    "PlanValidationError",
    "PlanValidator",
    "PlanningEngine",
    "StepStatus",
    "get_planning_engine",
]
