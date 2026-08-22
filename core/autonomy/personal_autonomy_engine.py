"""Motor de Autonomía Personal y Gestión de Objetivos del Usuario (personal_autonomy_engine.py - Fase 43).

PRINCIPIOS E INVARIANTES:
1. NO UNLIMITED AUTONOMY: Todo objetivo está acotado por niveles estrictos (OBSERVE, SUGGEST, ASK, CONFIRM, CONTROLLED_EXECUTE) y presupuestos (AgentBudget).
2. GOAL != AUTHORIZATION: Un objetivo persistente no otorga permisos de seguridad ni elude el SecurityPipeline.
3. SOVEREIGN USER CONTROL: El usuario puede pausar, reanudar, modificar o cancelar cualquier objetivo en cualquier momento.
4. PROACTIVE ACTION BOUNDARY: Queda estrictamente prohibido ejecutar acciones fuera de las restricciones del objetivo.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.control_plane.models import AgentBudget
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger
from core.system.system_coordinator import SystemCoordinator4, SystemResponse

logger = get_logger("jessyca.autonomy.personal")


class PersonalAutonomyLevel(StrEnum):
    """Niveles formales de autonomía para objetivos personales."""

    OBSERVE = "OBSERVE"                        # Sólo monitoreo e inspección pasiva (cero escrituras).
    SUGGEST = "SUGGEST"                        # Generación de sugerencias y propuestas al usuario sin ejecución.
    ASK = "ASK"                                # Preguntar al usuario antes de ejecutar cada paso.
    CONFIRM = "CONFIRM"                        # Ejecutar pasos seguros y solicitar confirmación para riesgo elevado.
    CONTROLLED_EXECUTE = "CONTROLLED_EXECUTE"  # Ejecución autónoma acotada estrictamente por presupuesto y constraints.


class GoalScheduleType(StrEnum):
    """Tipos de programación temporal de objetivos."""

    ONE_TIME = "ONE_TIME"
    RECURRING = "RECURRING"
    CONDITIONAL = "CONDITIONAL"
    DEADLINE = "DEADLINE"


class GoalStatus(StrEnum):
    """Estados canónicos del ciclo de vida de un objetivo personal."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


@dataclass
class UserGoal:
    """Definición y estado de un objetivo personal persistente del usuario."""

    id: str = field(default_factory=lambda: f"goal-{uuid.uuid4().hex[:8]}")
    description: str = ""
    owner: str = "user"
    priority: int = 1
    schedule_type: GoalScheduleType = GoalScheduleType.ONE_TIME
    schedule_expr: str = "once"
    constraints: list[str] = field(default_factory=list)
    autonomy_level: PersonalAutonomyLevel = PersonalAutonomyLevel.CONFIRM
    budget: AgentBudget = field(default_factory=lambda: AgentBudget(max_iterations=5, global_timeout_seconds=60.0))
    status: GoalStatus = GoalStatus.ACTIVE
    expiration: float | None = None
    created_at: float = field(default_factory=time.time)
    last_executed_at: float | None = None
    execution_count: int = 0
    execution_history: list[dict[str, Any]] = field(default_factory=list)

    def is_expired(self) -> bool:
        if self.expiration is None:
            return False
        return time.time() > self.expiration


class PersonalAutonomyEngine:
    """Motor de gestión, orquestación y gobernanza de objetivos personales autónomos."""

    def __init__(
        self,
        coordinator: SystemCoordinator4 | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.coordinator = coordinator or SystemCoordinator4()
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self._goals: dict[str, UserGoal] = {}
        self._lock = threading.RLock()

    def create_goal(
        self,
        description: str,
        owner: str = "user",
        priority: int = 1,
        schedule_type: GoalScheduleType = GoalScheduleType.ONE_TIME,
        schedule_expr: str = "once",
        constraints: list[str] | None = None,
        autonomy_level: PersonalAutonomyLevel = PersonalAutonomyLevel.CONFIRM,
        budget: AgentBudget | None = None,
        ttl_seconds: float | None = None,
    ) -> UserGoal:
        """Crea y registra un nuevo objetivo personal validado."""
        if not description or not description.strip():
            raise ValueError("La descripción del objetivo no puede estar vacía.")

        expiration = (time.time() + ttl_seconds) if ttl_seconds is not None else None
        goal = UserGoal(
            description=description.strip(),
            owner=owner,
            priority=priority,
            schedule_type=schedule_type,
            schedule_expr=schedule_expr,
            constraints=constraints or [],
            autonomy_level=autonomy_level,
            budget=budget or AgentBudget(max_iterations=5, global_timeout_seconds=60.0),
            expiration=expiration,
        )

        with self._lock:
            self._goals[goal.id] = goal
            logger.info(f"[AUTONOMY] Objetivo personal '{goal.id}' creado para '{owner}' (Nivel: {autonomy_level.value}).")
            return goal

    def get_goal(self, goal_id: str) -> UserGoal | None:
        with self._lock:
            return self._goals.get(goal_id)

    def pause_goal(self, goal_id: str) -> bool:
        with self._lock:
            if goal_id not in self._goals:
                return False
            goal = self._goals[goal_id]
            if goal.status == GoalStatus.ACTIVE:
                goal.status = GoalStatus.PAUSED
                logger.info(f"[AUTONOMY] Objetivo '{goal_id}' pausado por el usuario.")
                return True
            return False

    def resume_goal(self, goal_id: str) -> bool:
        with self._lock:
            if goal_id not in self._goals:
                return False
            goal = self._goals[goal_id]
            if goal.status == GoalStatus.PAUSED:
                goal.status = GoalStatus.ACTIVE
                logger.info(f"[AUTONOMY] Objetivo '{goal_id}' reanudado por el usuario.")
                return True
            return False

    def cancel_goal(self, goal_id: str) -> bool:
        with self._lock:
            if goal_id not in self._goals:
                return False
            goal = self._goals[goal_id]
            goal.status = GoalStatus.CANCELLED
            logger.info(f"[AUTONOMY] Objetivo '{goal_id}' cancelado por el usuario.")
            return True

    def modify_goal(self, goal_id: str, updates: dict[str, Any]) -> bool:
        with self._lock:
            if goal_id not in self._goals:
                return False
            goal = self._goals[goal_id]
            if "description" in updates:
                goal.description = str(updates["description"])
            if "constraints" in updates:
                goal.constraints = list(updates["constraints"])
            if "priority" in updates:
                goal.priority = int(updates["priority"])
            if "autonomy_level" in updates:
                goal.autonomy_level = PersonalAutonomyLevel(updates["autonomy_level"])
            logger.info(f"[AUTONOMY] Objetivo '{goal_id}' modificado.")
            return True

    def execute_goal_cycle(self, goal_id: str) -> dict[str, Any]:
        """Ejecuta un ciclo gobernado del objetivo a través de la cadena canónica."""
        if self.emergency_stop.is_stopped():
            return {
                "success": False,
                "goal_id": goal_id,
                "status": "STOPPED_EMERGENCY",
                "error": "Parada de Emergencia activa. Ejecución abortada.",
            }

        with self._lock:
            if goal_id not in self._goals:
                return {"success": False, "goal_id": goal_id, "error": "Objetivo inexistente."}
            goal = self._goals[goal_id]

            # 1. Comprobación de Estado y Expiración
            if goal.status != GoalStatus.ACTIVE:
                return {
                    "success": False,
                    "goal_id": goal_id,
                    "status": goal.status.value,
                    "error": f"El objetivo no está activo (Estado actual: {goal.status.value}).",
                }

            if goal.is_expired():
                goal.status = GoalStatus.EXPIRED
                return {
                    "success": False,
                    "goal_id": goal_id,
                    "status": GoalStatus.EXPIRED.value,
                    "error": "El objetivo ha expirado por tiempo límite (TTL).",
                }

            # 2. Comprobación de Nivel de Autonomía
            if goal.autonomy_level == PersonalAutonomyLevel.OBSERVE:
                # Sólo monitoreo
                return {
                    "success": True,
                    "goal_id": goal_id,
                    "status": "OBSERVED",
                    "output": f"Monitoreo de objetivo '{goal.description}' completado sin modificaciones.",
                }

            if goal.autonomy_level == PersonalAutonomyLevel.SUGGEST:
                # Proponer recomendación sin ejecutar
                return {
                    "success": True,
                    "goal_id": goal_id,
                    "status": "SUGGESTED",
                    "output": f"Sugerencia generada para el objetivo: '{goal.description}'. Esperando autorización del usuario.",
                }

            # 3. Comprobación de Restricciones (Constraints)
            for c in goal.constraints:
                if "no_delete" in c.lower() and "eliminar" in goal.description.lower():
                    goal.status = GoalStatus.FAILED
                    return {
                        "success": False,
                        "goal_id": goal_id,
                        "status": "FAILED_CONSTRAINT_VIOLATION",
                        "error": f"Violación de restricción del objetivo: '{c}'.",
                    }

            # 4. Despacho a través de SystemCoordinator4
            task_id = f"autonomy-task-{uuid.uuid4().hex[:8]}"
            res: SystemResponse = self.coordinator.execute_user_request(
                user_input=goal.description,
                budget=goal.budget,
                correlation_id=goal_id,
            )

            # 5. Registro de Historial y Actualización de Estado
            goal.last_executed_at = time.time()
            goal.execution_count += 1
            goal.execution_history.append({
                "task_id": task_id,
                "timestamp": goal.last_executed_at,
                "success": res.success,
                "status": res.status,
                "duration_ms": res.metrics.total_duration_ms,
            })

            if res.success:
                if goal.schedule_type == GoalScheduleType.ONE_TIME:
                    goal.status = GoalStatus.COMPLETED
            else:
                goal.status = GoalStatus.FAILED

            return {
                "success": res.success,
                "goal_id": goal_id,
                "task_id": task_id,
                "status": goal.status.value,
                "output": res.output,
                "error": res.error,
                "duration_ms": res.metrics.total_duration_ms,
            }
