"""Controlled Agent Loop (Etapa 20.1 & Fase 6: Activación Controlada).

Implementa el motor de ejecución acotado, seguro y gobernado del agente:
  OBSERVE -> INTERPRET -> PLAN -> ACT -> VERIFY -> UPDATE -> STOP

GARANTÍAS INMUTABLES:
1. Bounded Loop: Iteraciones (max_steps) limitadas estrictamente por budget; PROHIBIDO 'while True' sin acotamiento.
2. Multi-Dimensional Resource Limits: Timeout global (max_time), tool budget (max_actions), reintentos (max_retries), token budget y techo de riesgo (max_risk).
3. Risk Ceiling & Security Policy: Bloqueo inmediato (STOP INMEDIATO) de cualquier acción que supere el techo de riesgo o sea denegada por SecurityPipeline / PermissionManager / RiskEngine.
4. Emergency & Cancellation: Detención inmediata ante Emergency Stop o señal de cancelación.
5. Inviolabilidad de Políticas: Toda acción pasa por Policy Check antes de ACT.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from core.autonomy.autonomy_governor import get_autonomy_governor
from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk
from core.autonomy.capability_autonomy_registry import get_capability_autonomy_registry
from core.cancellation import CancellationToken
from core.control_plane.models import (
    AgentBudget,
    AgentLoopResult,
    AgentLoopState,
    BudgetTracker,
)
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger
from core.tool_planner import (
    ControlledToolPlanner,
    MemoryEvidence,
    PlanningContext,
)

logger = get_logger("jessyca.control_plane.agent_loop")


class ControlledAgentLoop:
    """Orquestador del ciclo de vida controlado del agente con presupuesto y límites acotados."""

    def __init__(
        self,
        planner: ControlledToolPlanner | None = None,
        emergency_stop: EmergencyStopManager | None = None,
        action_executor: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
        action_verifier: Callable[[str, dict[str, Any]], bool] | None = None,
        security_checker: Callable[[str, str, dict[str, Any]], tuple[bool, str]] | None = None,
    ) -> None:
        self.planner = planner or ControlledToolPlanner()
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self.action_executor = action_executor or self._default_action_executor
        self.action_verifier = action_verifier or self._default_action_verifier
        self.security_checker = security_checker
        self.governor = get_autonomy_governor()
        self.registry = get_capability_autonomy_registry()

    def run(
        self,
        intent: str,
        budget: AgentBudget | None = None,
        context: dict[str, Any] | None = None,
        memory_evidence: list[MemoryEvidence] | None = None,
        cancellation_token: CancellationToken | None = None,
        is_goal_satisfied: Callable[[dict[str, Any]], bool] | None = None,
        task_id: str | None = None,
    ) -> AgentLoopResult:
        """Ejecuta el ciclo controlado del agente respetando presupuestos, timeouts y gobernanza."""
        effective_budget = budget or AgentBudget()
        tracker = BudgetTracker()
        task_uuid = task_id or f"task_{uuid.uuid4().hex[:10]}"
        ctx = dict(context or {})
        evidence = list(memory_evidence or [])
        history_trace: list[dict[str, Any]] = []

        logger.info(
            f"[AGENT LOOP START] Tarea '{task_uuid}': '{intent}' "
            f"(Max steps: {effective_budget.max_steps}, Timeout: {effective_budget.max_time}s, "
            f"Risk ceiling: {effective_budget.max_risk.value})"
        )

        current_state = AgentLoopState.IDLE
        stop_reason = ""

        # INVARIANTE: Bounded Loop condicionado al límite de iteraciones (NUNCA while True)
        while tracker.iterations_count < effective_budget.max_steps:
            iteration_index = tracker.iterations_count + 1

            # ── 0. BARRERA DE ENTRADA: Emergency Stop & Cancellation & Budgets ──
            if self.emergency_stop.is_stopped():
                current_state = AgentLoopState.STOPPED_EMERGENCY
                stop_reason = "Emergency Stop activado por el usuario o sistema."
                logger.warning(f"[AGENT LOOP] {stop_reason}")
                break

            if cancellation_token and cancellation_token.is_cancelled:
                current_state = AgentLoopState.STOPPED_CANCELLED
                stop_reason = "Tarea cancelada explícitamente vía CancellationToken."
                logger.info(f"[AGENT LOOP] {stop_reason}")
                break

            exceeded, budget_reason, terminal_state = tracker.check_limits(effective_budget)
            if exceeded and terminal_state:
                current_state = terminal_state
                stop_reason = budget_reason or "Límite de presupuesto excedido."
                logger.warning(f"[AGENT LOOP] {stop_reason}")
                break

            logger.debug(f"[AGENT LOOP] --- Iniciando Iteración {iteration_index}/{effective_budget.max_steps} ---")

            # ── 1. OBSERVE ──
            current_state = AgentLoopState.OBSERVING
            observed_state = self._observe(ctx)
            step_record: dict[str, Any] = {"iteration": iteration_index, "observed": observed_state}

            # ── 2. INTERPRET ──
            current_state = AgentLoopState.INTERPRETING
            subtask_hint = self._interpret(intent, observed_state, iteration_index)
            step_record["subtask"] = subtask_hint

            # ── 3. PLAN ──
            current_state = AgentLoopState.PLANNING
            retrieved_evidence = self._retrieve(intent, evidence)
            step_record["evidence_count"] = len(retrieved_evidence)

            p_ctx = PlanningContext(
                user_intent=intent,
                current_autonomy_level=self.governor.current_level,
                session_id=str(ctx.get("session_id", "")),
            )
            plan_proposal = self.planner.plan(
                intent=intent,
                context=ctx,
                memory_evidence=retrieved_evidence,
                subtasks_hints=[subtask_hint],
                planning_context=p_ctx,
            )
            step_record["proposed_steps"] = len(plan_proposal.proposed_steps)

            if not plan_proposal.proposed_steps:
                # No se pudo planificar ninguna acción ejecutable o autorizada
                current_state = AgentLoopState.STOPPED_PERMISSION_DENIED
                stop_reason = "No se encontraron herramientas autorizadas para satisfacer la tarea."
                step_record["error"] = stop_reason
                history_trace.append(step_record)
                break

            proposed_step = plan_proposal.proposed_steps[0]
            step_record["tool"] = f"{proposed_step.tool_name}.{proposed_step.operation}"

            # ── 4. POLICY CHECK / SECURITY PIPELINE (Risk Ceiling, Autonomy, SecurityPolicy) ──
            current_state = AgentLoopState.CHECKING_POLICY
            policy_ok, policy_reason = self._check_policy(proposed_step, effective_budget)
            if not policy_ok:
                current_state = AgentLoopState.STOPPED_PERMISSION_DENIED
                stop_reason = policy_reason
                step_record["policy_denial"] = policy_reason
                history_trace.append(step_record)
                logger.warning(f"[AGENT LOOP POLICY DENIED - STOP INMEDIATO] {policy_reason}")
                break

            # ── 5. ACT (Execution under Sandbox/Safe Pipeline) ──
            current_state = AgentLoopState.ACTING
            if self.emergency_stop.is_stopped():
                current_state = AgentLoopState.STOPPED_EMERGENCY
                stop_reason = "Emergency Stop activado antes de ejecutar la acción."
                break

            act_result = self._act(proposed_step.tool_name, proposed_step.operation, proposed_step.parameters)
            tracker.tools_executed_count += 1
            tracker.tokens_consumed_count += int(act_result.get("tokens_used", 50))
            step_record["act_result"] = act_result

            # ── 6. VERIFY ──
            current_state = AgentLoopState.VERIFYING
            verify_ok = self.action_verifier(f"{proposed_step.tool_name}.{proposed_step.operation}", act_result)
            step_record["verified"] = verify_ok

            if verify_ok:
                tracker.consecutive_failures_count = 0
            else:
                tracker.consecutive_failures_count += 1
                logger.warning(
                    f"[AGENT LOOP VERIFY FAIL] Fallo de verificación en acción '{proposed_step.tool_name}.{proposed_step.operation}' "
                    f"(fallos consecutivos: {tracker.consecutive_failures_count}/{effective_budget.max_retries})"
                )
                if tracker.consecutive_failures_count >= effective_budget.max_retries:
                    current_state = AgentLoopState.STOPPED_REPEATED_FAILURE
                    stop_reason = f"Límite de reintentos consecutivos alcanzado ({tracker.consecutive_failures_count} >= {effective_budget.max_retries})."
                    step_record["failure_halt"] = stop_reason
                    tracker.iterations_count += 1
                    history_trace.append(step_record)
                    break

            # ── 7. UPDATE ──
            current_state = AgentLoopState.UPDATING
            tracker.iterations_count += 1
            self._update_state(ctx, proposed_step, act_result, verify_ok)
            history_trace.append(step_record)

            # Comprobar límite de herramientas antes de la siguiente iteración
            if tracker.tools_executed_count >= effective_budget.max_actions:
                current_state = AgentLoopState.STOPPED_LIMIT_REACHED
                stop_reason = f"Límite de herramientas ejecutadas alcanzado ({tracker.tools_executed_count} >= {effective_budget.max_actions})."
                break

            # Evaluar condición de éxito o terminación del objetivo
            goal_checker = is_goal_satisfied or self._default_goal_satisfied
            if verify_ok and goal_checker(ctx):
                current_state = AgentLoopState.COMPLETED
                stop_reason = "Objetivo completado y verificado con éxito."
                logger.info(f"[AGENT LOOP COMPLETED] {stop_reason}")
                break

        # ── 8. STOP (Safe Terminal Exit) ──
        if current_state not in (
            AgentLoopState.COMPLETED,
            AgentLoopState.STOPPED_EMERGENCY,
            AgentLoopState.STOPPED_CANCELLED,
            AgentLoopState.STOPPED_TIMEOUT,
            AgentLoopState.STOPPED_PERMISSION_DENIED,
            AgentLoopState.STOPPED_REPEATED_FAILURE,
            AgentLoopState.STOPPED_LIMIT_REACHED,
        ):
            current_state = AgentLoopState.STOPPED_LIMIT_REACHED
            stop_reason = f"Límite máximo de pasos alcanzado ({effective_budget.max_steps})."

        return AgentLoopResult(
            task_id=task_uuid,
            intent=intent,
            final_state=current_state,
            iterations_executed=tracker.iterations_count,
            tools_executed=tracker.tools_executed_count,
            tokens_consumed=tracker.tokens_consumed_count,
            duration_seconds=tracker.elapsed_seconds(),
            stop_reason=stop_reason,
            output_metadata=dict(ctx),
            history_trace=tuple(history_trace),
        )

    # ─── MÉTODOS DE LAS FASES DEL LOOP ───

    def _observe(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Fase 1: OBSERVE - Recolecta el estado actual."""
        return {"session_active": True, "context_keys": list(ctx.keys())}

    def _interpret(self, intent: str, observed: dict[str, Any], iteration: int) -> dict[str, Any]:
        """Fase 2: INTERPRET - Formula la sub-meta para la iteración actual."""
        keywords = self.planner._extract_keywords(intent)
        if not keywords:
            keywords = ["system", "info", "read"]
        return {"step_id": f"step_{iteration:02d}", "description": intent, "keywords": keywords, "parameters": {}}

    def _retrieve(self, intent: str, evidence: list[MemoryEvidence]) -> list[MemoryEvidence]:
        """Recuperación de evidencias para el planificador."""
        return list(evidence)

    def _check_policy(self, step: Any, budget: AgentBudget) -> tuple[bool, str]:
        """Fase 4: POLICY CHECK - Evalúa riesgo, techo de riesgo, autonomía y SecurityPipeline."""
        risk_hierarchy = {
            TaskActionRisk.READ_ONLY: 0,
            "READ_ONLY": 0,
            "read_only": 0,
            TaskActionRisk.LOW_RISK: 1,
            "LOW_RISK": 1,
            "low_risk": 1,
            TaskActionRisk.MEDIUM_RISK: 2,
            "MEDIUM_RISK": 2,
            "medium_risk": 2,
            TaskActionRisk.DANGEROUS: 3,
            "DANGEROUS": 3,
            "dangerous": 3,
            TaskActionRisk.CRITICAL: 4,
            "CRITICAL": 4,
            "critical": 4,
        }
        step_risk = getattr(step, "declared_risk", TaskActionRisk.LOW_RISK)
        step_val = step_risk.value if hasattr(step_risk, "value") else str(step_risk)
        ceiling_val = budget.risk_ceiling.value if hasattr(budget.risk_ceiling, "value") else str(budget.risk_ceiling)

        step_score = risk_hierarchy.get(step_risk, risk_hierarchy.get(step_val, 0))
        ceiling_score = risk_hierarchy.get(budget.risk_ceiling, risk_hierarchy.get(ceiling_val, 0))

        # 1. Techo de riesgo
        if step_score > ceiling_score:
            return (
                False,
                f"Riesgo de la acción ({step_val}) supera el techo de riesgo permitido ({ceiling_val}).",
            )

        # 2. Nivel de autonomía
        min_level = getattr(step, "minimum_autonomy_level", AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION)
        if self.governor.current_level < min_level:
            return (
                False,
                f"Nivel de autonomía insuficiente ({self.governor.current_level.label} < requerido {min_level.label}).",
            )

        # 3. Security Checker / Pipeline externo
        if self.security_checker is not None:
            tool_name = getattr(step, "tool_name", "")
            operation = getattr(step, "operation", "")
            params = getattr(step, "parameters", {})
            sec_ok, sec_reason = self.security_checker(tool_name, operation, params)
            if not sec_ok:
                return False, f"Security Pipeline DENY: {sec_reason}"

        return True, "Policy check OK"

    def _act(self, tool_name: str, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        """Fase 5: ACT - Ejecuta la acción a través del executor confiable."""
        return self.action_executor(tool_name, operation, params)

    def _update_state(self, ctx: dict[str, Any], step: Any, act_result: dict[str, Any], verified: bool) -> None:
        """Fase 7: UPDATE - Actualiza el contexto y progreso de la tarea."""
        ctx["last_action"] = f"{step.tool_name}.{step.operation}"
        ctx["last_verified"] = verified
        ctx.update(act_result.get("updated_context", {}))

    def _default_action_executor(self, tool_name: str, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        """Ejecutor predeterminado (simulación segura si no se proporciona executor real)."""
        logger.debug(f"[ACTION EXECUTOR] Ejecutando {tool_name}.{operation} con params={params}")
        return {"status": "ok", "tool": tool_name, "operation": operation, "tokens_used": 100}

    def _default_action_verifier(self, tool_key: str, act_result: dict[str, Any]) -> bool:
        """Verificador predeterminado."""
        return act_result.get("status") == "ok"

    def _default_goal_satisfied(self, ctx: dict[str, Any]) -> bool:
        """Condición predeterminada de satisfacción de meta."""
        return ctx.get("last_verified") is True
