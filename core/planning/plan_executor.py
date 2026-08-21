"""Ejecutor orquestado de planes con verificación de seguridad por paso (plan_executor.py - Fase 23).

Garantiza determinísticamente:
1. Recorrido topológico de pasos respetando dependencias.
2. Invariante: PLANNER != AUTHORIZATION (Evaluación de seguridad previa en cada paso).
3. Interrupción inmediata ante Parada de Emergencia o CancellationToken.
4. Verificación de criterios de éxito tras cada acción.
5. Detención en cascada ante fallos o denegaciones de seguridad.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from core.cancellation import CancellationToken
from core.emergency_stop import (
    EmergencyStopManager,
    EmergencyStopTriggeredError,
    get_emergency_stop_manager,
)
from core.logger import get_logger
from core.permission_manager import PermissionDecision, PermissionManager
from core.planning.plan_models import (
    ExecutionPlan,
    PlanExecutionResult,
    PlanStatus,
    PlanStep,
    PlanStepResult,
    StepStatus,
)
from core.planning.plan_validator import PlanValidator
from core.risk_engine import RiskEngine
from core.security_architecture import (
    SecurityContext,
    SecurityRequest,
    ToolSecurityMetadata,
)

logger = get_logger("jessyca.planning.executor")


class PlanExecutor:
    """Ejecutor seguro de planes multi-agente con control de seguridad y contingencias."""

    def __init__(
        self,
        emergency_stop: EmergencyStopManager | None = None,
        permission_manager: PermissionManager | None = None,
        risk_engine: RiskEngine | None = None,
        step_executor: Callable[[PlanStep, dict[str, Any]], Any] | None = None,
        step_verifier: Callable[[PlanStep, Any], bool] | None = None,
    ) -> None:
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self.permission_manager = permission_manager or PermissionManager()
        self.risk_engine = risk_engine or RiskEngine()
        self.step_executor = step_executor or self._default_step_executor
        self.step_verifier = step_verifier or self._default_step_verifier

    def execute(
        self,
        plan: ExecutionPlan,
        cancellation_token: CancellationToken | None = None,
    ) -> PlanExecutionResult:
        """Ejecuta el plan paso a paso siguiendo el orden topológico de dependencias."""
        start_time = time.monotonic()

        # 1. Validar integridad estructural y DAG del plan
        is_valid, validation_error = PlanValidator.validate(plan)
        if not is_valid:
            logger.error(f"[PLAN EXECUTION REJECTED] Plan '{plan.plan_id}' no es válido: {validation_error}")
            return PlanExecutionResult(
                plan_id=plan.plan_id,
                goal=plan.goal,
                status=PlanStatus.FAILED,
                steps_executed=0,
                step_results=(),
                duration_seconds=0.0,
                error=f"Plan inválido: {validation_error}",
                is_success=False,
            )

        topological_steps = PlanValidator.get_topological_steps(plan)
        results: list[PlanStepResult] = []
        step_outputs: dict[str, Any] = {}
        failed_step_ids: set[str] = set()

        logger.info(f"[PLAN EXECUTION STARTED] Plan '{plan.plan_id}' ({len(topological_steps)} pasos)")

        for step in topological_steps:
            step_start = time.monotonic()

            # 2. Comprobar Parada de Emergencia
            try:
                self.emergency_stop.check_cancellation(phase=f"plan_step_{step.step_id}")
            except EmergencyStopTriggeredError as e:
                logger.critical(f"[PLAN HALTED BY EMERGENCY STOP] Paso '{step.step_id}': {e}")
                results.append(
                    PlanStepResult(
                        step_id=step.step_id,
                        status=StepStatus.CANCELLED,
                        error="Interrumpido por Parada de Emergencia global.",
                        duration_seconds=time.monotonic() - step_start,
                        verified=False,
                    )
                )
                return PlanExecutionResult(
                    plan_id=plan.plan_id,
                    goal=plan.goal,
                    status=PlanStatus.CANCELLED,
                    steps_executed=len(results),
                    step_results=tuple(results),
                    duration_seconds=time.monotonic() - start_time,
                    error="Parada de Emergencia activada durante la ejecución del plan.",
                    is_success=False,
                )

            # 3. Comprobar CancellationToken
            if cancellation_token and cancellation_token.is_cancelled:
                logger.info(f"[PLAN CANCELLED] Paso '{step.step_id}' abortado por token de cancelación.")
                results.append(
                    PlanStepResult(
                        step_id=step.step_id,
                        status=StepStatus.CANCELLED,
                        error="Cancelado por usuario/sistema.",
                        duration_seconds=time.monotonic() - step_start,
                        verified=False,
                    )
                )
                return PlanExecutionResult(
                    plan_id=plan.plan_id,
                    goal=plan.goal,
                    status=PlanStatus.CANCELLED,
                    steps_executed=len(results),
                    step_results=tuple(results),
                    duration_seconds=time.monotonic() - start_time,
                    error="Ejecución cancelada por CancellationToken.",
                    is_success=False,
                )

            # 4. Comprobar Timeout Global
            elapsed_total = time.monotonic() - start_time
            if elapsed_total > plan.max_total_timeout_seconds:
                logger.error(f"[PLAN TIMEOUT] Plan '{plan.plan_id}' superó el tiempo máximo ({plan.max_total_timeout_seconds}s)")
                results.append(
                    PlanStepResult(
                        step_id=step.step_id,
                        status=StepStatus.FAILED,
                        error=f"Timeout global del plan excedido ({plan.max_total_timeout_seconds}s)",
                        duration_seconds=time.monotonic() - step_start,
                        verified=False,
                    )
                )
                return PlanExecutionResult(
                    plan_id=plan.plan_id,
                    goal=plan.goal,
                    status=PlanStatus.FAILED,
                    steps_executed=len(results),
                    step_results=tuple(results),
                    duration_seconds=elapsed_total,
                    error="Timeout global del plan excedido.",
                    is_success=False,
                )

            # 5. Comprobar si alguna dependencia falló previamente
            unmet_deps = [dep for dep in step.dependencies if dep in failed_step_ids]
            if unmet_deps:
                logger.warning(f"[STEP BLOCKED] Paso '{step.step_id}' bloqueado por fallo en dependencias: {unmet_deps}")
                failed_step_ids.add(step.step_id)
                results.append(
                    PlanStepResult(
                        step_id=step.step_id,
                        status=StepStatus.BLOCKED,
                        error=f"Dependencias fallidas: {unmet_deps}",
                        duration_seconds=0.0,
                        verified=False,
                    )
                )
                continue

            # 6. INVARIANTE: PLANNER != AUTHORIZATION (Validación de Seguridad previa a ACT)
            if step.required_tool:
                sec_req = SecurityRequest(
                    context=SecurityContext(
                        user=step.required_agent,
                        tool_name=step.required_tool,
                        parameters=step.tool_parameters,
                    ),
                    metadata=ToolSecurityMetadata(
                        tool_name=step.required_tool,
                        category="planning_step",
                        risk_level=step.risk_level,
                    ),
                )
                assessment = self.risk_engine.evaluate_risk(sec_req)
                decision = self.permission_manager.check_permission(
                    tool_name=step.required_tool,
                    risk_level=assessment.risk_level,
                )
                if decision == PermissionDecision.DENY:
                    logger.error(
                        f"[STEP SECURITY DENIED] Paso '{step.step_id}' denegado por Security Pipeline "
                        f"(Herramienta: {step.required_tool}, Riesgo: {step.risk_level})"
                    )
                    failed_step_ids.add(step.step_id)
                    results.append(
                        PlanStepResult(
                            step_id=step.step_id,
                            status=StepStatus.FAILED,
                            error=f"Denegado por política de seguridad: {step.required_tool}",
                            duration_seconds=time.monotonic() - step_start,
                            verified=False,
                        )
                    )
                    # Detener ejecución de plan ante denegación de seguridad
                    return PlanExecutionResult(
                        plan_id=plan.plan_id,
                        goal=plan.goal,
                        status=PlanStatus.FAILED,
                        steps_executed=len(results),
                        step_results=tuple(results),
                        duration_seconds=time.monotonic() - start_time,
                        error=f"Denegación de seguridad en paso '{step.step_id}': {step.required_tool}",
                        is_success=False,
                    )

            # 7. Ejecutar Paso
            try:
                output = self.step_executor(step, step_outputs)
                is_verified = self.step_verifier(step, output)

                if not is_verified:
                    logger.error(f"[STEP VERIFICATION FAILED] Paso '{step.step_id}' no cumplió el criterio de éxito.")
                    failed_step_ids.add(step.step_id)
                    results.append(
                        PlanStepResult(
                            step_id=step.step_id,
                            status=StepStatus.FAILED,
                            output=output,
                            error=f"Fallo de verificación contra criterio: '{step.success_criteria}'",
                            duration_seconds=time.monotonic() - step_start,
                            verified=False,
                        )
                    )
                else:
                    step_outputs[step.step_id] = output
                    results.append(
                        PlanStepResult(
                            step_id=step.step_id,
                            status=StepStatus.COMPLETED,
                            output=output,
                            duration_seconds=time.monotonic() - step_start,
                            verified=True,
                        )
                    )
            except Exception as e:
                logger.error(f"[STEP EXECUTION ERROR] Paso '{step.step_id}' lanzó excepción: {e}")
                failed_step_ids.add(step.step_id)
                results.append(
                    PlanStepResult(
                        step_id=step.step_id,
                        status=StepStatus.FAILED,
                        error=str(e),
                        duration_seconds=time.monotonic() - step_start,
                        verified=False,
                    )
                )

        # 8. Consolidar Resultado Final del Plan
        all_passed = len(failed_step_ids) == 0 and len(results) == len(topological_steps)
        final_status = PlanStatus.COMPLETED if all_passed else PlanStatus.FAILED
        total_duration = time.monotonic() - start_time

        logger.info(f"[PLAN EXECUTION FINISHED] Plan '{plan.plan_id}' -> Estado: {final_status} ({total_duration:.3f}s)")
        return PlanExecutionResult(
            plan_id=plan.plan_id,
            goal=plan.goal,
            status=final_status,
            steps_executed=len(results),
            step_results=tuple(results),
            duration_seconds=total_duration,
            error=None if all_passed else f"Fallaron {len(failed_step_ids)} pasos del plan.",
            is_success=all_passed,
        )

    def _default_step_executor(self, step: PlanStep, context: dict[str, Any]) -> dict[str, Any]:
        """Ejecutor mock/por defecto de pasos cuando no se suministra uno personalizado."""
        return {
            "status": "success",
            "step_id": step.step_id,
            "agent": step.required_agent,
            "tool": step.required_tool,
            "parameters": step.tool_parameters,
        }

    def _default_step_verifier(self, step: PlanStep, output: Any) -> bool:
        """Verificador por defecto que asegura que el output no sea nulo ni contenga errores explícitos."""
        if output is None:
            return False
        if isinstance(output, dict) and output.get("status") == "error":
            return False
        return True
