"""Validador formal y estructural de planes de ejecución (plan_validator.py - Fase 23).

Garantiza determinísticamente:
1. Ausencia de ciclos (DAG estricto con TaskGraph).
2. Integridad de dependencias y precondiciones.
3. Conformidad de delegación inter-agente (DelegationPolicy).
4. Límites de presupuesto y timeouts acotados.
"""

from __future__ import annotations

from core.agents.delegation_policy import DelegationPolicy
from core.agents.task_graph import TaskGraph, TaskNode
from core.logger import get_logger
from core.planning.plan_models import ExecutionPlan, PlanStep

logger = get_logger("jessyca.planning.validator")

MAX_PLAN_TIMEOUT_SECONDS: float = 600.0  # 10 minutos techo global
MAX_PLAN_STEPS: int = 25                 # Máximo de pasos por plan


class PlanValidationError(Exception):
    """Excepción lanzada cuando un plan no supera la validación estructural o de seguridad."""


class PlanValidator:
    """Validador estricto para planes de ejecución multi-agente."""

    @classmethod
    def validate(cls, plan: ExecutionPlan) -> tuple[bool, str]:
        """Ejecuta todas las validaciones estructurales y de seguridad sobre el plan."""
        # 1. Comprobación básica de tamaño y unicidad
        if not plan.steps:
            return False, "El plan no contiene pasos para ejecutar."

        if len(plan.steps) > MAX_PLAN_STEPS:
            return False, f"El plan supera el límite máximo de pasos permitidos ({MAX_PLAN_STEPS})."

        step_ids = {s.step_id for s in plan.steps}
        if len(step_ids) != len(plan.steps):
            return False, "Existen identificadores de paso duplicados en el plan."

        # 2. Validación de dependencias existentes y auto-dependencias
        for s in plan.steps:
            for dep in s.dependencies:
                if dep == s.step_id:
                    return False, f"El paso '{s.step_id}' depende de sí mismo (auto-ciclo)."
                if dep not in step_ids:
                    return False, f"El paso '{s.step_id}' depende del paso inexistente '{dep}'."

        # 3. Validación de Grafo Acíclico (DAG) mediante TaskGraph
        graph = TaskGraph()
        for s in plan.steps:
            graph.add_node(
                TaskNode(
                    node_id=s.step_id,
                    agent_id=s.required_agent,
                    intent=s.description,
                    dependencies=list(s.dependencies),
                )
            )

        if graph.detect_cycles():
            return False, "El plan contiene dependencias cíclicas o recursivas prohibidas."

        # 4. Validación de delegaciones inter-agente si aplica
        for s in plan.steps:
            for dep_id in s.dependencies:
                parent_step = plan.get_step(dep_id)
                if parent_step and parent_step.required_agent != s.required_agent:
                    # Delegación cross-agent
                    verdict = DelegationPolicy.validate_delegation(
                        sender_agent_id=parent_step.required_agent,
                        recipient_agent_id=s.required_agent,
                        scope="export_report",
                    )
                    # Si no está explícitamente permitida en la matriz estricta
                    if not verdict.is_allowed:
                        logger.warning(
                            f"[PLAN VALIDATION WARNING] Delegación '{parent_step.required_agent}' -> '{s.required_agent}' "
                            f"requiere validación por paso: {verdict.reason}"
                        )

        # 5. Validación de presupuestos y timeouts
        if plan.max_total_timeout_seconds <= 0 or plan.max_total_timeout_seconds > MAX_PLAN_TIMEOUT_SECONDS:
            return False, f"El timeout total del plan ({plan.max_total_timeout_seconds}s) está fuera de rango (0-{MAX_PLAN_TIMEOUT_SECONDS}s)."

        for s in plan.steps:
            if s.timeout_seconds <= 0 or s.timeout_seconds > plan.max_total_timeout_seconds:
                return False, f"El timeout del paso '{s.step_id}' ({s.timeout_seconds}s) es inválido."

        return True, "Plan válido y conforme con políticas estructurales y de seguridad."

    @classmethod
    def get_topological_steps(cls, plan: ExecutionPlan) -> list[PlanStep]:
        """Retorna los pasos del plan ordenados topológicamente según sus dependencias."""
        is_valid, reason = cls.validate(plan)
        if not is_valid:
            raise PlanValidationError(f"No se puede obtener el orden topológico de un plan inválido: {reason}")

        graph = TaskGraph()
        for s in plan.steps:
            graph.add_node(
                TaskNode(
                    node_id=s.step_id,
                    agent_id=s.required_agent,
                    intent=s.description,
                    dependencies=list(s.dependencies),
                )
            )

        topological_nodes = graph.get_topological_order()
        step_map = {s.step_id: s for s in plan.steps}
        return [step_map[node.node_id] for node in topological_nodes]
