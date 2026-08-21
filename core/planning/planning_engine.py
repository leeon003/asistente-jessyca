"""Motor central orquestador de planificación (planning_engine.py - Fase 23).

Integra:
PlanBuilder -> PlanValidator -> Security Pipeline -> PlanExecutor -> Verification

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. PLANNER != AUTHORIZATION
2. Ningún plan puede auto-aprobarse ni saltarse el SecurityPipeline.
3. Todo paso individual es verificado antes y después de ACT.
"""

from __future__ import annotations

import threading
from typing import ClassVar

from core.cancellation import CancellationToken
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger
from core.permission_manager import PermissionManager
from core.planning.plan_builder import PlanBuilder
from core.planning.plan_executor import PlanExecutor
from core.planning.plan_models import (
    ExecutionPlan,
    PlanExecutionResult,
    PlanStatus,
    PlanStep,
)
from core.planning.plan_validator import PlanValidator
from core.risk_engine import RiskEngine

logger = get_logger("jessyca.planning.engine")


class PlanningEngine:
    """Motor de planificación y ejecución gobernada para Jessyca 3.0."""

    _instance: ClassVar[PlanningEngine | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        emergency_stop: EmergencyStopManager | None = None,
        permission_manager: PermissionManager | None = None,
        risk_engine: RiskEngine | None = None,
        executor: PlanExecutor | None = None,
    ) -> None:
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self.permission_manager = permission_manager or PermissionManager()
        self.risk_engine = risk_engine or RiskEngine()
        self.executor = executor or PlanExecutor(
            emergency_stop=self.emergency_stop,
            permission_manager=self.permission_manager,
            risk_engine=self.risk_engine,
        )
        self.builder = PlanBuilder()
        self.validator = PlanValidator()

    @classmethod
    def get_instance(cls) -> PlanningEngine:
        """Obtiene la instancia singleton global de PlanningEngine."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = PlanningEngine()
            return cls._instance

    def create_plan(
        self,
        goal: str,
        steps: list[PlanStep] | tuple[PlanStep, ...],
        max_total_timeout_seconds: float = 120.0,
    ) -> ExecutionPlan:
        """Construye un ExecutionPlan a partir de un objetivo y lista de pasos."""
        return self.builder.create_custom_plan(
            goal=goal,
            steps=list(steps),
            max_total_timeout_seconds=max_total_timeout_seconds,
        )

    def validate_plan(self, plan: ExecutionPlan) -> tuple[bool, str]:
        """Valida determinísticamente la estructura, el DAG (sin ciclos) y los presupuestos del plan."""
        return self.validator.validate(plan)

    def execute_plan(
        self,
        plan: ExecutionPlan,
        cancellation_token: CancellationToken | None = None,
    ) -> PlanExecutionResult:
        """Ejecuta el plan validado respetando el orden topológico y las barreras de seguridad."""
        is_valid, reason = self.validate_plan(plan)
        if not is_valid:
            return PlanExecutionResult(
                plan_id=plan.plan_id,
                goal=plan.goal,
                status=PlanStatus.FAILED,
                steps_executed=0,
                step_results=(),
                duration_seconds=0.0,
                error=f"Plan inválido: {reason}",
                is_success=False,
            )

        validated_plan = plan.with_status(PlanStatus.VALIDATED)
        return self.executor.execute(validated_plan, cancellation_token=cancellation_token)

    def plan_and_execute(
        self,
        goal: str,
        steps: list[PlanStep] | tuple[PlanStep, ...],
        cancellation_token: CancellationToken | None = None,
    ) -> PlanExecutionResult:
        """Crea, valida y ejecuta un plan de extremo a extremo."""
        plan = self.create_plan(goal=goal, steps=steps)
        return self.execute_plan(plan, cancellation_token=cancellation_token)


def get_planning_engine() -> PlanningEngine:
    """Acceso helper al singleton global de PlanningEngine."""
    return PlanningEngine.get_instance()
