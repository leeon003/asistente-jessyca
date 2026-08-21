"""Tests exhaustivos para ControlledAgentLoop (Etapa 20.1 & Fase 6: Activación Controlada).

Verifica:
1. Ciclo normal: Ciclo completo exitoso en pocas iteraciones.
2. Timeout: Detención segura por expiración de timeout global (max_time).
3. Step limit: Prevención de bucles infinitos por límite acotado de pasos (max_steps).
4. Risk limit: Bloqueo seguro ante superación del techo de riesgo (max_risk).
5. Tool failure / Retry exhaustion: Detención segura ante fallos repetidos consecutivos (max_retries).
6. Security denial: Parada inmediata (STOP INMEDIATO) cuando Security Pipeline deniega la acción.
7. Emergency stop: Interrupción inmediata ante activación de EmergencyStop.
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
        budget = AgentBudget.create(max_steps=5, max_time=10.0)

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

    def test_infinite_loop_step_limit_prevention(self) -> None:
        """Verifica que si la meta nunca se satisface, el bucle se detenga estrictamente en max_steps."""
        budget = AgentBudget.create(max_steps=4, max_time=10.0)

        # La condición de meta nunca devuelve True
        result = self.loop.run(
            intent="Consultar información del sistema",
            budget=budget,
            is_goal_satisfied=lambda ctx: False,
        )

        assert result.final_state == AgentLoopState.STOPPED_LIMIT_REACHED
        assert result.iterations_executed == 4
        assert "límite" in result.stop_reason.lower()

    def test_repeated_failure_and_retry_exhaustion(self) -> None:
        """Verifica que agotar los reintentos (max_retries) detenga de forma segura el loop."""
        budget = AgentBudget.create(max_steps=10, max_retries=3)

        # El verificador siempre falla simulando tool failures consecutivos
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
        assert "reintentos" in result.stop_reason.lower() or "fallos" in result.stop_reason.lower()

    def test_global_timeout(self) -> None:
        """Verifica que el loop se detenga inmediatamente si se excede el timeout global (max_time)."""
        budget = AgentBudget.create(max_steps=10, max_time=0.1)

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
        budget = AgentBudget.create(max_steps=10)

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

    def test_budget_exceeded_for_tools_and_actions(self) -> None:
        """Verifica que exceder el límite de herramientas (max_actions) detenga el bucle."""
        budget = AgentBudget.create(max_steps=10, max_actions=2)

        result = self.loop.run(
            intent="Consultar información del sistema",
            budget=budget,
            is_goal_satisfied=lambda ctx: False,  # nunca termina por meta
        )

        assert result.final_state == AgentLoopState.STOPPED_LIMIT_REACHED
        assert result.tools_executed == 2
        assert "herramientas ejecutadas" in result.stop_reason.lower()

    def test_risk_ceiling_permission_denied(self) -> None:
        """Verifica que si una acción supera el Risk Ceiling (max_risk), el loop la bloquea."""
        # Techo de riesgo: LOW_RISK.
        budget = AgentBudget.create(
            max_steps=5,
            max_risk=TaskActionRisk.LOW_RISK,
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

    def test_security_pipeline_denial_immediate_stop(self) -> None:
        """Invariante Crítica: Si SecurityPipeline dice DENY, el loop se detiene inmediatamente (STOP INMEDIATO)."""
        def security_checker_deny(tool: str, op: str, params: dict[str, Any]) -> tuple[bool, str]:
            return False, "Operación bloqueada por SecurityPolicy: recurso protegido."

        executed_tools: list[str] = []

        def tracking_executor(tool: str, op: str, params: dict[str, Any]) -> dict[str, Any]:
            executed_tools.append(f"{tool}.{op}")
            return {"status": "ok"}

        loop = ControlledAgentLoop(
            emergency_stop=self.emergency_stop,
            action_executor=tracking_executor,
            security_checker=security_checker_deny,
        )

        budget = AgentBudget.create(max_steps=5)
        result = loop.run(
            intent="Consultar información del sistema",
            budget=budget,
            is_goal_satisfied=lambda ctx: False,
        )

        # 1. Estado terminal STOPPED_PERMISSION_DENIED
        assert result.final_state == AgentLoopState.STOPPED_PERMISSION_DENIED
        assert "Security Pipeline DENY" in result.stop_reason

        # 2. Cero herramientas ejecutadas
        assert len(executed_tools) == 0
        assert result.tools_executed == 0
