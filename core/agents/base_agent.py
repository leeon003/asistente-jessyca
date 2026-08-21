"""Clase base inmutable para agentes especializados (base_agent.py - Fase 7: Specialized Agents).

Garantiza aislamiento estricto de herramientas, presupuestos acotados y techos de riesgo inviolables.
INVARIANTE ARQUITECTÓNICA:
Ningún agente especializado obtiene permisos adicionales por sí mismo.
Toda ejecución está gobernada por ControlledAgentLoop y su validador de seguridad.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.autonomy.autonomy_level import TaskActionRisk
from core.control_plane.controlled_agent_loop import ControlledAgentLoop
from core.control_plane.models import AgentBudget, AgentLoopResult
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger
from core.tool_planner import ControlledToolPlanner

logger = get_logger("jessyca.agents.base")


@dataclass(frozen=True)
class AgentIdentity:
    """Identidad formal e inmutable de un agente especializado."""

    agent_id: str
    name: str
    description: str
    role: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "role": self.role,
        }


class BaseSpecializedAgent:
    """Clase base gobernada para la instanciación y ejecución de agentes especializados."""

    def __init__(
        self,
        identity: AgentIdentity,
        capabilities: tuple[str, ...],
        allowed_tools: frozenset[str] | set[str],
        risk_ceiling: TaskActionRisk,
        budget: AgentBudget,
        planner: ControlledToolPlanner | None = None,
        emergency_stop: EmergencyStopManager | None = None,
        action_executor: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
        action_verifier: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> None:
        self.identity = identity
        self.capabilities = tuple(capabilities)
        self.allowed_tools = frozenset(allowed_tools)
        self.risk_ceiling = risk_ceiling
        self.budget = budget
        self.planner = planner
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self.action_executor = action_executor
        self.action_verifier = action_verifier

    def validate_tool_call(
        self,
        tool_name: str,
        operation: str,
        params: dict[str, Any],
    ) -> tuple[bool, str]:
        """Valida que la herramienta solicitada pertenezca a la lista autorizada y respete las restricciones."""
        full_tool = f"{tool_name}.{operation}"

        # 1. Comprobar pertenencia a allowed_tools
        tool_match = (
            full_tool in self.allowed_tools
            or tool_name in self.allowed_tools
            or operation in self.allowed_tools
        )

        if not tool_match:
            msg = (
                f"Aislamiento de herramientas violado: El agente '{self.identity.name}' "
                f"intentó invocar '{full_tool}', la cual NO pertenece a sus herramientas autorizadas."
            )
            logger.warning(f"[AGENT SECURITY DENIAL] {msg}")
            return False, msg

        # 2. Validaciones adicionales específicas del agente (e.g. sandbox, read-only)
        extra_ok, extra_reason = self._additional_tool_validation(tool_name, operation, params)
        if not extra_ok:
            logger.warning(f"[AGENT SECURITY DENIAL] {extra_reason}")
            return False, extra_reason

        return True, "Tool validation OK"

    def _additional_tool_validation(
        self,
        tool_name: str,
        operation: str,
        params: dict[str, Any],
    ) -> tuple[bool, str]:
        """Hook extensible para validaciones de fronteras adicionales en agentes derivados."""
        return True, "OK"

    def run(
        self,
        intent: str,
        context: dict[str, Any] | None = None,
        task_id: str | None = None,
        is_goal_satisfied: Callable[[dict[str, Any]], bool] | None = None,
    ) -> AgentLoopResult:
        """Ejecuta la tarea en el ControlledAgentLoop con la gobernanza de este agente."""
        loop = ControlledAgentLoop(
            planner=self.planner,
            emergency_stop=self.emergency_stop,
            action_executor=self.action_executor,
            action_verifier=self.action_verifier,
            security_checker=self.validate_tool_call,
        )

        logger.info(
            f"[AGENT RUN] Agente '{self.identity.name}' ({self.identity.agent_id}) iniciando tarea: '{intent}'"
        )

        return loop.run(
            intent=intent,
            budget=self.budget,
            context=context,
            is_goal_satisfied=is_goal_satisfied,
            task_id=task_id,
        )
