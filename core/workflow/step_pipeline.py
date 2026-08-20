"""Pipeline de Seguridad Atómico para cada Paso de Workflow (Etapa 18.1).

GARANTÍA CRÍTICA DE SEGURIDAD:
Cada step pasa individualmente por el pipeline formal:
  VALIDATE -> AUTHORIZE -> EXECUTE -> VERIFY -> RECORD

PROHIBICIÓN ABSOLUTA:
Ningún workflow puede ejecutar acciones en lote sin someter cada paso individual
a las 5 fases de seguridad.

Si la verificación post-ejecución falla, el step entra en FAILED y los steps dependientes
NUNCA se ejecutan automáticamente.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

from core.autonomy.autonomy_decision import AutonomyDecisionValue
from core.autonomy.autonomy_governor import AutonomyGovernor, get_autonomy_governor
from core.autonomy.autonomy_policy import AutonomyEvaluationContext
from core.exceptions import MCPError
from core.logger import get_logger
from core.observability.structured_event import (
    ActionId,
    CorrelationId,
    EventSeverity,
    get_structured_telemetry_emitter,
)
from core.recovery.recovery_coordinator import ControlledFailureRecovery, get_recovery_coordinator
from core.workflow.models import (
    StepExecutionResult,
    StepState,
    WorkflowStep,
)

logger = get_logger("jessyca.workflow.step_pipeline")


class StepSecurityError(MCPError):
    """Error emitido cuando un paso no supera las validaciones de seguridad o autorización."""

    pass


class StepVerificationFailedError(MCPError):
    """Error emitido cuando la aserción de verificación post-ejecución falla."""

    pass


def interpolate_parameters(
    parameters: dict[str, Any],
    previous_results: dict[str, StepExecutionResult],
) -> dict[str, Any]:
    """Interpola de forma segura variables de pasos previos (ej: '{{step_01.output.id}}')."""
    interpolated: dict[str, Any] = {}
    pattern = re.compile(r"\{\{([a-zA-Z0-9_\-]+)\.output(?:\.([a-zA-Z0-9_\-]+))?\}\}")

    for k, v in parameters.items():
        if isinstance(v, str):
            match = pattern.search(v)
            if match:
                src_step_id = match.group(1)
                field_name = match.group(2)

                if src_step_id in previous_results:
                    src_out = previous_results[src_step_id].output
                    if field_name and isinstance(src_out, dict):
                        resolved_val = src_out.get(field_name, "")
                    else:
                        resolved_val = src_out

                    # Reemplazar plantilla con el valor resuelto
                    interpolated[k] = pattern.sub(str(resolved_val), v)
                else:
                    interpolated[k] = v
            else:
                interpolated[k] = v
        else:
            interpolated[k] = v
    return interpolated


class StepExecutionPipeline:
    """Orquestador de las 5 fases atómicas para un paso de workflow."""

    def __init__(
        self,
        governor: AutonomyGovernor | None = None,
        recovery_coordinator: ControlledFailureRecovery | None = None,
    ) -> None:
        self.governor = governor or get_autonomy_governor()
        self.recovery = recovery_coordinator or get_recovery_coordinator()
        self.telemetry = get_structured_telemetry_emitter()

    def process_step(
        self,
        step: WorkflowStep,
        workflow_id: str,
        correlation_id: str | CorrelationId,
        previous_results: dict[str, StepExecutionResult],
        tool_invoker: Callable[[str, str, dict[str, Any]], Any] | None = None,
    ) -> StepExecutionResult:
        """Ejecuta el ciclo atómico completo de 5 fases para un paso."""
        action_id = ActionId.generate(prefix=f"act_{step.step_id}_")
        start_time = time.perf_counter()

        logger.info(f"[STEP PIPELINE] Iniciando procesamiento para step '{step.step_id}' ({step.tool_name}.{step.operation})")

        # ─── FASE 1: VALIDATE ─────────────────────────────────────────────
        # Verificar que todas las dependencias se hayan completado y verificado exitosamente
        for dep_id in step.dependencies:
            if dep_id not in previous_results:
                msg = f"Dependencia '{dep_id}' no ha sido ejecutada."
                return self._create_result(step.step_id, StepState.FAILED, False, error=msg, start_time=start_time)

            dep_res = previous_results[dep_id]
            if not dep_res.success:
                msg = f"Dependencia '{dep_id}' falló en su ejecución previa."
                return self._create_result(step.step_id, StepState.FAILED, False, error=msg, start_time=start_time)

            if not dep_res.verification_passed:
                msg = f"Dependencia '{dep_id}' no superó su verificación obligatoria. Bloqueando ejecución subsiguiente."
                return self._create_result(step.step_id, StepState.FAILED, False, error=msg, verification_passed=False, start_time=start_time)

        # Resolver parámetros interpolados
        resolved_params = interpolate_parameters(step.parameters, previous_results)

        # ─── FASE 2: AUTHORIZE ────────────────────────────────────────────
        eval_ctx = AutonomyEvaluationContext(
            task_id=f"{workflow_id}:{step.step_id}",
            tool_name=step.tool_name,
            operation=step.operation,
            parameters=resolved_params,
            task_source="workflow",
            workflow_id=workflow_id,
        )

        try:
            # Evaluar decisión de autonomía
            decision = self.governor.policy.evaluate(eval_ctx, self.governor.current_level)

            if decision.decision == AutonomyDecisionValue.DENY:
                msg = f"[STEP AUTHORIZATION DENIED] {decision.reason}"
                logger.warning(f"[STEP PIPELINE] {msg}")
                return self._create_result(step.step_id, StepState.FAILED, False, error=msg, start_time=start_time)

            if decision.requires_confirmation and not decision.allowed:
                # Si requiere confirmación y no está autorizada automáticamente
                msg = f"[STEP CONFIRMATION REQUIRED] La acción '{step.tool_name}.{step.operation}' exige confirmación humana activa."
                logger.info(f"[STEP PIPELINE] {msg}")
                return self._create_result(step.step_id, StepState.FAILED, False, error=msg, start_time=start_time)

        except Exception as exc:
            msg = f"[STEP SECURITY CHECK FAILED] Error durante evaluación de política: {exc}"
            return self._create_result(step.step_id, StepState.FAILED, False, error=msg, start_time=start_time)

        # ─── FASE 3: EXECUTE ──────────────────────────────────────────────
        def _invoke_action() -> Any:
            if tool_invoker is not None:
                return tool_invoker(step.tool_name, step.operation, resolved_params)
            # Default stub/mock si no se pasa invocador personalizado
            return {"status": "success", "tool": step.tool_name, "operation": step.operation, "params": resolved_params}

        # Ejecutar a través del subsistema de recuperación controlada (bounded retry)
        rec_res = self.recovery.execute_with_recovery(
            tool_name=step.tool_name,
            operation=step.operation,
            risk_level=step.risk_level,
            action_fn=_invoke_action,
        )

        if not rec_res.success:
            msg = f"Fallo en ejecución de herramienta: {rec_res.final_error}"
            return self._create_result(
                step.step_id,
                StepState.FAILED,
                False,
                error=msg,
                attempts=rec_res.attempts,
                start_time=start_time,
            )

        step_output = rec_res.result

        # ─── FASE 4: VERIFY ───────────────────────────────────────────────
        verification_passed = True
        verification_result = None

        # 4.1 Verificación contra ExpectedState formal (Etapa 18.3)
        if step.expected_state is not None:
            from core.workflow.verification import WorkflowStepVerifier
            v_res = WorkflowStepVerifier.verify(
                expected=step.expected_state,
                action_output=step_output,
                observer_fn=step.observer_fn,
            )
            verification_result = v_res
            if not v_res.passed:
                msg = f"Fallo en verificación post-ejecución (ExpectedState): {v_res.reason}"
                logger.error(f"[STEP PIPELINE] {msg}")
                return self._create_result(
                    step.step_id,
                    StepState.FAILED,
                    False,
                    output=step_output,
                    error=msg,
                    verification_passed=False,
                    verification_result=v_res,
                    attempts=rec_res.attempts,
                    start_time=start_time,
                )

        # 4.2 Verificación por regla funcional (compatibilidad 18.1)
        if step.requires_verification and step.verification_rule is not None:
            logger.debug(f"[STEP PIPELINE] Ejecutando regla de verificación '{step.verification_rule.rule_name}'")
            verification_passed = step.verification_rule.verify(step_output)

            if not verification_passed:
                msg = (
                    f"Fallo en verificación post-ejecución para step '{step.step_id}'. "
                    f"Regla: '{step.verification_rule.rule_name}'. "
                    f"Esperado: '{step.verification_rule.expected_description}'."
                )
                logger.error(f"[STEP PIPELINE] {msg}")
                return self._create_result(
                    step.step_id,
                    StepState.FAILED,
                    False,
                    output=step_output,
                    error=msg,
                    verification_passed=False,
                    attempts=rec_res.attempts,
                    start_time=start_time,
                )

        # ─── FASE 5: RECORD ───────────────────────────────────────────────
        result = self._create_result(
            step_id=step.step_id,
            state=StepState.COMPLETED,
            success=True,
            output=step_output,
            verification_passed=verification_passed,
            verification_result=verification_result,
            attempts=rec_res.attempts,
            start_time=start_time,
        )

        # Emitir telemetría estructurada
        try:
            self.telemetry.emit_tool(
                tool_name=step.tool_name,
                operation=step.operation,
                correlation_id=correlation_id,
                action_id=action_id,
                parameters=resolved_params,
                duration_ms=result.duration_ms,
                severity=EventSeverity.INFO,
            )
        except Exception as exc:
            logger.error(f"[STEP PIPELINE] Error emitiendo telemetría de step: {exc}")

        return result

    def _create_result(
        self,
        step_id: str,
        state: StepState,
        success: bool,
        output: Any = None,
        error: str | None = None,
        verification_passed: bool = True,
        verification_result: Any | None = None,
        attempts: int = 1,
        start_time: float = 0.0,
    ) -> StepExecutionResult:
        duration_ms = (time.perf_counter() - start_time) * 1000 if start_time > 0 else 0.0
        return StepExecutionResult(
            step_id=step_id,
            state=state,
            success=success,
            output=output,
            error=error,
            verification_passed=verification_passed,
            verification_result=verification_result,
            attempts=attempts,
            duration_ms=duration_ms,
        )
