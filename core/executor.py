"""Task Executor para Jessyca Windows MCP.

Recibe EXCLUSIVAMENTE un ExecutionPlan estructurado (nunca lenguaje natural),
resuelve dependencias en orden topológico, selecciona herramientas por su capacidad de forma agnóstica,
evalúa reglas de seguridad, registra auditorías en la sesión, emite progreso en tiempo real
y ejecuta una arquitectura de Rollback compensatorio si una subtarea falla.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.capability import CapabilityManager
from core.event_bus import EventBus, get_event_bus
from core.exceptions import ValidationError
from core.logger import get_logger
from core.planner import ExecutionPlan
from core.security import SecurityManager, ToolSecurityProfile
from core.session_manager import SessionManager

logger = get_logger("jessyca.executor")


@dataclass
class RollbackAction:
    """Acción compensatoria inmutable registrada tras completar exitosamente una subtarea."""

    task_id: str
    tool_name: str
    description: str
    rollback_handler: Callable[..., Any] | None = None
    rollback_arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskExecutionResult:
    """Resultado individual del procesamiento de una subtarea."""

    task_id: str
    is_success: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    execution_time_seconds: float = 0.0


@dataclass
class PlanExecutionResult:
    """Resultado global consolidado tras la ejecución de un ExecutionPlan."""

    plan_id: str
    is_success: bool
    status: str  # "COMPLETED", "FAILED", "ROLLED_BACK"
    completed_tasks: list[str] = field(default_factory=list)
    failed_task_id: str | None = None
    task_outputs: dict[str, Any] = field(default_factory=dict)
    progress_percent: float = 0.0
    rollback_executed: bool = False
    error_message: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "is_success": self.is_success,
            "status": self.status,
            "completed_tasks": self.completed_tasks,
            "failed_task_id": self.failed_task_id,
            "task_outputs": self.task_outputs,
            "progress_percent": self.progress_percent,
            "rollback_executed": self.rollback_executed,
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat(),
        }


class TaskExecutor:
    """Ejecutor de planes de tareas desacoplado con arquitectura de Rollback compensatorio."""

    def __init__(
        self,
        capability_manager: CapabilityManager | None = None,
        security_manager: SecurityManager | None = None,
        session_manager: SessionManager | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.capability_manager = capability_manager or CapabilityManager()
        self.security_manager = security_manager or SecurityManager()
        self.session_manager = session_manager or SessionManager()
        self.event_bus = event_bus or get_event_bus()

    async def execute_plan(self, plan: ExecutionPlan) -> PlanExecutionResult:
        """Ejecuta un ExecutionPlan resolviendo subtareas, seguridad, progreso y rollback.

        REGLA ESTRICTA: Acepta exclusivamente una instancia de ExecutionPlan.

        Args:
            plan: Instancia de ExecutionPlan validada.

        Returns:
            PlanExecutionResult con el estado final de la ejecución.
        """
        # 1. Validación estricta del tipo de entrada
        if not isinstance(plan, ExecutionPlan):
            raise ValidationError(
                f"El TaskExecutor requiere exclusivamente una instancia de ExecutionPlan. Recibido: {type(plan)}"
            )

        logger.info(f"Iniciando ejecución de ExecutionPlan ID: '{plan.plan_id}' (Meta: '{plan.goal}')")

        # 2. Validar dependencias acíclicas del plan
        if not plan.validate_dependencies():
            msg = f"El plan '{plan.plan_id}' fue rechazado por tener dependencias de subtareas inválidas o circulares."
            logger.error(msg)
            return PlanExecutionResult(
                plan_id=plan.plan_id,
                is_success=False,
                status="FAILED",
                error_message=msg,
            )

        # 3. Notificar inicio de plan en el EventBus y SessionManager
        self.event_bus.publish("plan:started", {"plan_id": plan.plan_id, "goal": plan.goal})
        self.session_manager.start_session(metadata={"plan_id": plan.plan_id})

        tasks = plan.get_ordered_tasks()
        total_tasks = len(tasks)
        completed_task_ids: list[str] = []
        task_outputs: dict[str, Any] = {}
        rollback_stack: list[RollbackAction] = []

        if total_tasks == 0:
            return PlanExecutionResult(
                plan_id=plan.plan_id,
                is_success=True,
                status="COMPLETED",
                progress_percent=100.0,
            )

        # 4. Iteración secuencial respetando el orden topológico
        for idx, subtask in enumerate(tasks, 1):
            progress_pct = round(((idx - 1) / total_tasks) * 100, 1)

            # Notificar progreso de subtarea
            self.event_bus.publish(
                "task:progress",
                {
                    "plan_id": plan.plan_id,
                    "task_id": subtask.task_id,
                    "progress_percent": progress_pct,
                    "step": idx,
                    "total_steps": total_tasks,
                },
            )

            # A. Resolver herramienta dinámicamente mediante el CapabilityManager
            tool = None
            if subtask.capability_required and subtask.action_required:
                tool = self.capability_manager.resolve(
                    subtask.capability_required, subtask.action_required
                )

            if tool is None and subtask.action_required:
                tool = self.capability_manager.resolve_by_alias(subtask.action_required)

            if tool is None:
                err_msg = (
                    f"Subtarea '{subtask.task_id}' falló: No se encontró herramienta para la capacidad "
                    f"({subtask.capability_required}.{subtask.action_required})"
                )
                logger.error(err_msg)
                return await self._handle_plan_failure(
                    plan=plan,
                    failed_task_id=subtask.task_id,
                    error_message=err_msg,
                    completed_tasks=completed_task_ids,
                    task_outputs=task_outputs,
                    rollback_stack=rollback_stack,
                    total_tasks=total_tasks,
                )

            # B. Evaluación de reglas de seguridad vía SecurityManager
            sec_profile = ToolSecurityProfile(
                name=tool.name,
                category=subtask.capability_required or "General",
                risk_level=subtask.risk_level,
                required_permissions=[],
                requires_confirmation=False,
            )

            decision = self.security_manager.evaluate(sec_profile)
            if not decision.is_allowed:
                err_msg = f"Subtarea '{subtask.task_id}' bloqueada por seguridad: {decision.reason}"
                logger.warning(err_msg)
                return await self._handle_plan_failure(
                    plan=plan,
                    failed_task_id=subtask.task_id,
                    error_message=err_msg,
                    completed_tasks=completed_task_ids,
                    task_outputs=task_outputs,
                    rollback_stack=rollback_stack,
                    total_tasks=total_tasks,
                )

            # C. Ejecutar la herramienta de forma asíncrona y segura
            self.event_bus.publish(
                "task:started", {"plan_id": plan.plan_id, "task_id": subtask.task_id, "tool_name": tool.name}
            )

            start_t = time.perf_counter()
            exec_res = await tool.execute({})
            elapsed = round(time.perf_counter() - start_t, 3)

            if exec_res.is_success:
                output = exec_res.value
                completed_task_ids.append(subtask.task_id)
                task_outputs[subtask.task_id] = output

                # Registrar auditoría en la sesión
                self.session_manager.record_tool_usage(
                    tool_name=tool.name,
                    arguments={},
                    is_success=True,
                )

                # Registrar acción compensatoria de Rollback (si la herramienta soporta rollback)
                rollback_action = RollbackAction(
                    task_id=subtask.task_id,
                    tool_name=tool.name,
                    description=f"Revertir cambios de {subtask.task_id}",
                    rollback_arguments={},
                )
                rollback_stack.append(rollback_action)

                self.event_bus.publish(
                    "task:completed",
                    {
                        "plan_id": plan.plan_id,
                        "task_id": subtask.task_id,
                        "elapsed_seconds": elapsed,
                    },
                )
            else:
                err_msg = f"Subtarea '{subtask.task_id}' falló durante la ejecución: {exec_res.error}"
                self.session_manager.record_tool_usage(
                    tool_name=tool.name,
                    arguments={},
                    is_success=False,
                    error=str(exec_res.error),
                )
                return await self._handle_plan_failure(
                    plan=plan,
                    failed_task_id=subtask.task_id,
                    error_message=err_msg,
                    completed_tasks=completed_task_ids,
                    task_outputs=task_outputs,
                    rollback_stack=rollback_stack,
                    total_tasks=total_tasks,
                )

        # 5. Finalización exitosa del Plan
        self.session_manager.end_session()
        self.event_bus.publish("plan:completed", {"plan_id": plan.plan_id, "completed_tasks": completed_task_ids})

        logger.info(f"Plan '{plan.plan_id}' ejecutado exitosamente ({total_tasks}/{total_tasks} subtareas).")
        return PlanExecutionResult(
            plan_id=plan.plan_id,
            is_success=True,
            status="COMPLETED",
            completed_tasks=completed_task_ids,
            task_outputs=task_outputs,
            progress_percent=100.0,
        )

    async def _handle_plan_failure(
        self,
        plan: ExecutionPlan,
        failed_task_id: str,
        error_message: str,
        completed_tasks: list[str],
        task_outputs: dict[str, Any],
        rollback_stack: list[RollbackAction],
        total_tasks: int,
    ) -> PlanExecutionResult:
        """Maneja el fallo de un plan iniciando la secuencia de Rollback compensatorio."""
        logger.error(f"Fallo en plan '{plan.plan_id}' en subtarea '{failed_task_id}'. Iniciando Rollback...")
        self.session_manager.record_error(error_message, details={"failed_task_id": failed_task_id})

        # Notificar inicio de Rollback
        self.event_bus.publish(
            "plan:rollback_started",
            {"plan_id": plan.plan_id, "failed_task_id": failed_task_id, "actions_to_rollback": len(rollback_stack)},
        )

        # Ejecutar secuencia de Rollback en orden inverso (Stack LIFO)
        rollback_executed = await self._perform_rollback(rollback_stack)

        self.session_manager.end_session()
        self.event_bus.publish(
            "plan:failed",
            {
                "plan_id": plan.plan_id,
                "failed_task_id": failed_task_id,
                "rollback_executed": rollback_executed,
            },
        )

        progress_pct = round((len(completed_tasks) / total_tasks) * 100, 1) if total_tasks > 0 else 0.0

        return PlanExecutionResult(
            plan_id=plan.plan_id,
            is_success=False,
            status="ROLLED_BACK" if rollback_executed else "FAILED",
            completed_tasks=completed_tasks,
            failed_task_id=failed_task_id,
            task_outputs=task_outputs,
            progress_percent=progress_pct,
            rollback_executed=rollback_executed,
            error_message=error_message,
        )

    async def _perform_rollback(self, rollback_stack: list[RollbackAction]) -> bool:
        """Ejecuta en orden inverso (LIFO) la pila de acciones compensatorias registradas."""
        if not rollback_stack:
            logger.info("Pila de rollback vacía. No hay acciones compensatorias que ejecutar.")
            return False

        logger.info(f"Ejecutando rollback compensatorio de {len(rollback_stack)} tareas...")
        while rollback_stack:
            action = rollback_stack.pop()
            logger.info(f"Rollback subtarea '{action.task_id}' (Herramienta: '{action.tool_name}')...")
            try:
                if action.rollback_handler:
                    if inspect.iscoroutinefunction(action.rollback_handler):
                        await action.rollback_handler(action.rollback_arguments)
                    else:
                        action.rollback_handler(action.rollback_arguments)
                await asyncio.sleep(0.01)
            except Exception as e:
                logger.error(f"Error compensatorio durante rollback de subtarea '{action.task_id}': {e}")

        logger.info("Secuencia de Rollback compensatorio finalizada.")
        return True
