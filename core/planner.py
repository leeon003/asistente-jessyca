"""AI Planner para Jessyca Windows MCP.

Recibe intenciones u objetivos en lenguaje natural y genera un Plan de Ejecución Estructurado
(ExecutionPlan) 100% independiente del LLM.

REGLA FUNDAMENTAL: El AI Planner NO ejecuta herramientas; únicamente descompone,
estructura, evalúa riesgos, valida dependencias y secuencia las subtareas.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.logger import get_logger
from core.security import RiskLevel

logger = get_logger("jessyca.planner")


@dataclass
class SubTask:
    """Subtarea individual dentro de un Plan de Ejecución."""

    task_id: str
    description: str
    capability_required: str | None = None
    action_required: str | None = None
    dependencies: list[str] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.SAFE
    required_context_keys: list[str] = field(default_factory=list)
    execution_order: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "capability_required": self.capability_required,
            "action_required": self.action_required,
            "dependencies": self.dependencies,
            "risk_level": self.risk_level.value,
            "required_context_keys": self.required_context_keys,
            "execution_order": self.execution_order,
        }


@dataclass
class ExecutionPlan:
    """Plan de ejecución completo, estructurado e independiente del modelo LLM."""

    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    goal: str = ""
    tasks: list[SubTask] = field(default_factory=list)
    total_risk: RiskLevel = RiskLevel.READ_ONLY
    required_context: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.consolidate_risk_and_context()

    def consolidate_risk_and_context(self) -> None:
        """Consolida el nivel de riesgo global del plan y la lista de claves de contexto requeridas."""
        risk_hierarchy = {
            RiskLevel.READ_ONLY: 1,
            RiskLevel.SAFE: 2,
            RiskLevel.WARNING: 3,
            RiskLevel.DANGEROUS: 4,
            RiskLevel.CRITICAL: 5,
        }

        max_risk_score = 1
        max_risk_level = RiskLevel.READ_ONLY
        context_keys: set[str] = set()

        for t in self.tasks:
            score = risk_hierarchy.get(t.risk_level, 1)
            if score > max_risk_score:
                max_risk_score = score
                max_risk_level = t.risk_level

            context_keys.update(t.required_context_keys)

        self.total_risk = max_risk_level
        self.required_context = sorted(context_keys)

    def validate_dependencies(self) -> bool:
        """Verifica que todas las dependencias entre subtareas existan y no contengan ciclos.

        Returns:
            bool: True si el grafo de dependencias es válido y acíclico, False si es inválido.
        """
        task_ids = {t.task_id for t in self.tasks}

        # 1. Comprobar que todas las dependencias referenciadas existan
        for t in self.tasks:
            for dep in t.dependencies:
                if dep not in task_ids:
                    logger.error(
                        f"Plan '{self.plan_id}' inválido: Subtarea '{t.task_id}' depende de '{dep}' no existente."
                    )
                    return False

        # 2. Detección de ciclos en el grafo (Algoritmo de Kahn / DFS)
        visited: set[str] = set()
        rec_stack: set[str] = set()

        adj: dict[str, list[str]] = {t.task_id: t.dependencies for t in self.tasks}

        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)

            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for t_id in task_ids:
            if t_id not in visited:
                if has_cycle(t_id):
                    logger.error(f"Plan '{self.plan_id}' inválido: Se detectó un ciclo de dependencia circular.")
                    return False

        return True

    def get_ordered_tasks(self) -> list[SubTask]:
        """Obtiene la lista de subtareas ordenada estrictamente según el orden de ejecución y dependencias."""
        return sorted(self.tasks, key=lambda t: (t.execution_order, t.task_id))

    def to_dict(self) -> dict[str, Any]:
        """Convierte el plan en un diccionario serializable."""
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "total_risk": self.total_risk.value,
            "required_context": self.required_context,
            "created_at": self.created_at.isoformat(),
            "tasks_count": len(self.tasks),
            "tasks": [t.to_dict() for t in self.get_ordered_tasks()],
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Serializa el plan completo a un string JSON formateado."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


class AIPlanner:
    """Planificador inteligente que analiza la meta en lenguaje natural y construye el ExecutionPlan.

    No ejecuta herramientas reales. Funciona de manera agnóstica al modelo de lenguaje.
    """

    def __init__(self, capability_manager: Any | None = None) -> None:
        self.capability_manager = capability_manager

    def create_plan(
        self,
        natural_language_goal: str,
        context_snapshot: dict[str, Any] | None = None,
    ) -> ExecutionPlan:
        """Analiza la meta en lenguaje natural y genera un ExecutionPlan estructurado.

        Args:
            natural_language_goal: Objetivo expresado por el usuario en texto libre.
            context_snapshot: Instantánea opcional del ContextManager.

        Returns:
            Instancia de ExecutionPlan validada y ordenada.
        """
        logger.info(f"Generando plan para la meta: '{natural_language_goal}'")
        goal_text = natural_language_goal.strip()
        context = context_snapshot or {}

        # Generar subtareas descompuestas mediante motor de reglas heurísticas
        tasks = self._decompose_goal_to_tasks(goal_text, context)

        plan = ExecutionPlan(
            goal=goal_text,
            tasks=tasks,
            metadata={"context_snapshot_keys": list(context.keys())},
        )

        plan.consolidate_risk_and_context()

        if not plan.validate_dependencies():
            logger.warning(f"Se generó un plan con dependencias no válidas para '{goal_text}'")

        logger.info(
            f"Plan generado ID: '{plan.plan_id}' [{len(plan.tasks)} subtareas, Riesgo Global: {plan.total_risk.value}]"
        )
        return plan

    def _decompose_goal_to_tasks(
        self, goal: str, context: dict[str, Any]
    ) -> list[SubTask]:
        """Descompone la meta en lenguaje natural en subtareas secuenciales estructuradas."""
        g_lower = goal.lower()
        subtasks: list[SubTask] = []

        # Heurística 1: Tareas de Copia / Archivos
        if "copiar" in g_lower or "copy" in g_lower or "mover" in g_lower:
            t1 = SubTask(
                task_id="task_01",
                description="Validar existencia del archivo o carpeta origen",
                capability_required="Filesystem",
                action_required="read",
                dependencies=[],
                risk_level=RiskLevel.READ_ONLY,
                required_context_keys=["current_file", "last_directory"],
                execution_order=1,
            )
            t2 = SubTask(
                task_id="task_02",
                description="Ejecutar la operación de copia o traslado en el sistema de archivos",
                capability_required="Filesystem",
                action_required="copy" if "copiar" in g_lower or "copy" in g_lower else "move",
                dependencies=["task_01"],
                risk_level=RiskLevel.SAFE,
                required_context_keys=[],
                execution_order=2,
            )
            subtasks.extend([t1, t2])

        # Heurística 2: Diagnóstico o Salud del Sistema
        elif "salud" in g_lower or "diagnostico" in g_lower or "system_health" in g_lower or "ping" in g_lower:
            t1 = SubTask(
                task_id="task_01",
                description="Obtener métricas y diagnósticos de plataforma del sistema Windows",
                capability_required="System",
                action_required="health",
                dependencies=[],
                risk_level=RiskLevel.READ_ONLY,
                required_context_keys=["active_window"],
                execution_order=1,
            )
            subtasks.append(t1)

        # Heurística 3: Operaciones de Limpieza / Eliminación (High Risk)
        elif "eliminar" in g_lower or "borrar" in g_lower or "delete" in g_lower:
            t1 = SubTask(
                task_id="task_01",
                description="Inspeccionar archivo o directorio a eliminar",
                capability_required="Filesystem",
                action_required="read",
                dependencies=[],
                risk_level=RiskLevel.READ_ONLY,
                execution_order=1,
            )
            t2 = SubTask(
                task_id="task_02",
                description="Eliminar elemento del disco de manera irreversible",
                capability_required="Filesystem",
                action_required="delete",
                dependencies=["task_01"],
                risk_level=RiskLevel.DANGEROUS,
                required_context_keys=["current_file"],
                execution_order=2,
            )
            subtasks.extend([t1, t2])

        # Heurística Genérica / Fallback para cualquier otro lenguaje natural
        else:
            t1 = SubTask(
                task_id="task_01",
                description=f"Analizar requisitos para el objetivo: '{goal}'",
                capability_required="General",
                action_required="inspect",
                dependencies=[],
                risk_level=RiskLevel.READ_ONLY,
                execution_order=1,
            )
            t2 = SubTask(
                task_id="task_02",
                description=f"Procesar acción solicitada: '{goal}'",
                capability_required="General",
                action_required="execute",
                dependencies=["task_01"],
                risk_level=RiskLevel.SAFE,
                execution_order=2,
            )
            subtasks.extend([t1, t2])

        return subtasks
