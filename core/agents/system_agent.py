"""Agente especializado en diagnóstico del sistema (system_agent.py - Fase 7: Specialized Agents).

Restringido estrictamente a herramientas de diagnóstico y telemetría del sistema operativo.
INVARIANTE CRÍTICA:
Es estrictamente READ ONLY. No puede escribir, terminar procesos ni alterar la configuración del sistema.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.agents.agent_budget import create_system_agent_budget
from core.agents.base_agent import AgentIdentity, BaseSpecializedAgent
from core.autonomy.autonomy_level import TaskActionRisk
from core.control_plane.models import AgentBudget
from core.emergency_stop import EmergencyStopManager
from core.tool_planner import ControlledToolPlanner

SYSTEM_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "system.info",
    "system_info",
    "system.diagnostics",
    "diagnostics",
    "system.process_list",
    "process_list",
    "system.metrics",
    "metrics",
    "system.status",
    "system_status",
    "system.read",
    "system.read_only",
    "system.get_info",
    "system.check",
})

FORBIDDEN_WRITE_OPERATIONS: frozenset[str] = frozenset({
    "kill",
    "terminate",
    "write",
    "delete",
    "modify",
    "set",
    "reboot",
    "shutdown",
    "execute",
    "run_command",
})


class SystemAgent(BaseSpecializedAgent):
    """Agente de diagnóstico del sistema acotado estrictamente a operaciones de solo lectura."""

    def __init__(
        self,
        budget: AgentBudget | None = None,
        planner: ControlledToolPlanner | None = None,
        emergency_stop: EmergencyStopManager | None = None,
        action_executor: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
        action_verifier: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> None:
        identity = AgentIdentity(
            agent_id="agent_system",
            name="SystemAgent",
            description="Agente especializado en diagnóstico y métricas del sistema operativo (READ ONLY).",
            role="system_diagnostics",
        )
        capabilities = (
            "diagnostics",
            "system_info",
            "metrics",
            "read_only",
        )
        effective_budget = budget or create_system_agent_budget()

        super().__init__(
            identity=identity,
            capabilities=capabilities,
            allowed_tools=SYSTEM_ALLOWED_TOOLS,
            risk_ceiling=TaskActionRisk.READ_ONLY,
            budget=effective_budget,
            planner=planner,
            emergency_stop=emergency_stop,
            action_executor=action_executor,
            action_verifier=action_verifier,
        )

    def _additional_tool_validation(
        self,
        tool_name: str,
        operation: str,
        params: dict[str, Any],
    ) -> tuple[bool, str]:
        """Garantiza la invariante estricta READ ONLY del SystemAgent."""
        op_lower = operation.lower()
        tool_lower = tool_name.lower()

        for forbidden in FORBIDDEN_WRITE_OPERATIONS:
            if forbidden in op_lower or forbidden in tool_lower:
                return (
                    False,
                    f"Violación de Modo Lectura: El agente 'SystemAgent' es estrictamente READ ONLY "
                    f"y no puede ejecutar la operación de modificación '{tool_name}.{operation}'.",
                )

        return True, "SystemAgent read-only check OK"
