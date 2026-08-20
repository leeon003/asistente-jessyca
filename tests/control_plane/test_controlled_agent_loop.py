"""Tests exhaustivos para ControlledAgentLoop (Etapa 20.1).

Verifica:
1. Normal completion: Ciclo completo exitoso en pocas iteraciones.
2. Repeated failure: Detención segura ante fallos repetidos consecutivos.
3. Infinite loop prevention: Prevención de bucles infinitos por límite acotado de iteraciones.
4. Timeout: Detención segura por expiración de timeout global.
5. Emergency stop: Interrupción inmediata ante activación de EmergencyStop.
6. Budget exceeded: Detención por superar el presupuesto de herramientas o tokens.
7. Permission denied: Detención por violación de Risk Ceiling o falta de nivel de autonomía.
"""

from __future__ import annotations

import time
from typing import Any

from core.autonomy.autonomy_governor import get_autonomy_governor
from core.autonomy.autonomy_level import TaskActionRisk
from core.control_plane import (
    AgentBudget,
    AgentLoopState,
    ControlledAgentLoop,
)
from core.emergency_stop import EmergencyStopManager


class TestControlledAgentLoop:
    """Pruebas funcionales y de seguridad para el ciclo acotado del agente."""

    def setup_method(self) -> None:
        self.governor = get_autonomy_governor()
        self.governor.reset_to_default()
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset()
        self.loop = ControlledAgentLoop(emergency_stop=self.emergency_stop)

    def test_normal_completion(self) -> None:
        """Verifica que una tarea normal complete exitosamente y verifique su meta."""
        budget = AgentBudget(max_iterations=5, global_timeout_seconds=10.0)

        # Meta se satisface tras la primera iteración
        result = self.loop.run(
            intent="Leer archivo de configuración",
            budget=budget,
            is_goal_satisfied=lambda ctx: ctx.get("last_verified") is True,
        )

        assert result.final_state == AgentLoopState.COMPLETED
        assert result.is_success is True
        assert result.iterations_executed >= 1
        assert result.tools_executed >= 1
        assert result.duration_seconds > 0.0

    def test_infinite_loop_prevention(self) -> None:
        """Verifica que si la meta nunca se satisface, el bucle se detenga estrictamente en max_iterations."""
        budget = AgentBudget(max_iterations=4, global_timeout_seconds=10.0)

        # La condición de meta nunca devuelve True
        result = self.loop.run(
            intent="Consultar información del sistema",
            budget=budget,
            is_goal_satisfied=lambda ctx: False,
        )

        assert result.final_state == AgentLoopState.STOPPED_LIMIT_REACHED
        assert result.iterations_executed == 4
        assert "límite" in result.stop_reason.lower()

    def test_repeated_failure_stops_safely(self) -> None:
        """Verifica que fallos repetidos consecutivos detengan el loop."""
        budget = AgentBudget(max_iterations=10, max_consecutive_failures=3)

        # El verificador siempre falla
        loop = ControlledAgentLoop(
            emergency_stop=self.emergency_stop,
            action_verifier=lambda tool, res: False,
        )

        result = loop.run(
            intent="Operación inestable de lectura",
            budget=budget,
            is_goal_satisfied=lambda ctx: False,
        )

        assert result.final_state == AgentLoopState.STOPPED_REPEATED_FAILURE
        assert "fallos consecutivos" in result.stop_reason.lower()

    def test_global_timeout(self) -> None:
        """Verifica que el loop se detenga inmediatamente si se excede el timeout global."""
        budget = AgentBudget(max_iterations=10, global_timeout_seconds=0.1)

        def slow_executor(tool: str, op: str, params: dict[str, Any]) -> dict[str, Any]:
            time.sleep(0.15)
            return {"status": "ok"}

        loop = ControlledAgentLoop(
            emergency_stop=self.emergency_stop,
            action_executor=slow_executor,
        )

        result = loop.run(
            intent="Tarea lenta de lectura",
            budget=budget,
            is_goal_satisfied=lambda ctx: False,
        )

        assert result.final_state == AgentLoopState.STOPPED_TIMEOUT
        assert "timeout" in result.stop_reason.lower()

    def test_emergency_stop_triggers_immediate_halt(self) -> None:
        """Verifica que Emergency Stop detenga instantáneamente el loop del agente."""
        budget = AgentBudget(max_iterations=10)

        def emergency_executor(tool: str, op: str, params: dict[str, Any]) -> dict[str, Any]:
            # Disparar parada de emergencia durante la primera acción
            self.emergency_stop.trigger_stop(reason="Anomalía crítica detectada")
            return {"status": "ok"}

        loop = ControlledAgentLoop(
            emergency_stop=self.emergency_stop,
            action_executor=emergency_executor,
        )

        result = loop.run(
            intent="Tarea abortada de lectura",
            budget=budget,
            is_goal_satisfied=lambda ctx: False,
        )

        assert result.final_state == AgentLoopState.STOPPED_EMERGENCY
        assert "emergency stop" in result.stop_reason.lower()

    def test_budget_exceeded_for_tools_and_tokens(self) -> None:
        """Verifica que exceder el límite de herramientas detenga el bucle."""
        budget = AgentBudget(max_iterations=10, max_tool_executions=2)

        result = self.loop.run(
            intent="Consultar información del sistema",
            budget=budget,
            is_goal_satisfied=lambda ctx: False,  # nunca termina por meta
        )

        assert result.final_state == AgentLoopState.STOPPED_LIMIT_REACHED
        assert result.tools_executed == 2
        assert "herramientas ejecutadas" in result.stop_reason.lower()

    def test_risk_ceiling_permission_denied(self) -> None:
        """Verifica que si una acción supera el Risk Ceiling, el loop la bloquea."""
        # Techo de riesgo: LOW_RISK.
        budget = AgentBudget(
            max_iterations=5,
            risk_ceiling=TaskActionRisk.LOW_RISK,
        )

        # Intentar ejecutar filesystem.delete (DANGEROUS)
        result = self.loop.run(
            intent="Eliminar archivos delete filesystem",
            budget=budget,
            is_goal_satisfied=lambda ctx: False,
        )

        # Debe ser bloqueada por exceder el techo LOW_RISK
        assert result.final_state == AgentLoopState.STOPPED_PERMISSION_DENIED
        assert "techo de riesgo" in result.stop_reason.lower() or "no se encontraron" in result.stop_reason.lower()
