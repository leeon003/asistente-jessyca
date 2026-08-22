"""Ejecutor orquestado y motor de ejecución seguro para Skill Composition Engine (Fase 35).

Ejecuta composiciones de Skills respetando los tres modos de ejecución:
- SEQUENTIAL
- PARALLEL (concurrencia segura mediante ThreadPoolExecutor)
- CONDITIONAL (evaluación segura de predicados)

INVARIANTES DE SEGURIDAD CRÍTICOS:
1. Una Skill compuesta NO obtiene privilegios superiores a las Skills que contiene.
2. Cada acción y paso individual pasa obligatoriamente por SecurityPipeline, RiskEngine y PermissionManager.
3. Prevalencia de Parada de Emergencia: EmergencyStopManager detiene inmediatamente la ejecución en cualquier punto.
4. Las confirmaciones de pasos previos NO se heredan ni transfieren a pasos posteriores.
5. Se respetan los límites de presupuesto (AgentBudget), timeout y recursión.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, AuditLogger, get_audit_logger
from core.emergency_stop import EmergencyStopManager
from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.skill_composition_dataflow import (
    DataFlowResolutionError,
    SkillConditionEvaluator,
    SkillDataFlowResolver,
)
from skills.skill_composition_models import (
    CompositionErrorPolicy,
    CompositionExecutionMode,
    CompositionStatus,
    SkillComposition,
    SkillCompositionContext,
    SkillCompositionResult,
    SkillCompositionStep,
    SkillCompositionStepResult,
)
from skills.skill_composition_validator import (
    SkillCompositionValidator,
)
from skills.skill_manager import SkillManager, get_skill_manager
from skills.skill_models import (
    SkillResult,
    SkillStatus,
)
from skills.skill_registry import SkillRegistry, get_skill_registry
from skills.skill_runtime import SkillRuntime

logger = get_logger("jessyca.skills.composition.executor")


class SkillCompositionExecutionError(Exception):
    """Excepción durante la ejecución de una composición de Skills."""
    pass


class SkillCompositionExecutor:
    """Motor de orquestación y ejecución de composiciones de Skills."""

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        skill_manager: SkillManager | None = None,
        skill_runtime: SkillRuntime | None = None,
        validator: SkillCompositionValidator | None = None,
        emergency_stop: EmergencyStopManager | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.registry = registry or get_skill_registry()
        self.skill_manager = skill_manager or get_skill_manager()
        self.skill_runtime = skill_runtime or SkillRuntime()
        self.validator = validator or SkillCompositionValidator(registry=self.registry)
        self.emergency_stop = emergency_stop or EmergencyStopManager.get_instance()
        self.audit_logger = audit_logger or get_audit_logger()
        self._lock = threading.Lock()

    def execute_composition(
        self,
        composition: SkillComposition,
        context: SkillCompositionContext,
    ) -> SkillCompositionResult:
        """Ejecuta la composición de acuerdo a su modo de ejecución y políticas de seguridad."""
        start_time = time.perf_counter()
        warnings: list[str] = []

        # 1. Comprobación inmediata de Parada de Emergencia
        if self.emergency_stop.is_stopped():
            err_msg = "Parada de Emergencia activa en el sistema. Composición abortada."
            logger.critical(f"[COMPOSITION HALTED] {err_msg}")
            self._log_audit(
                event_type=AuditEventType.EXECUTION_DENIED,
                operation="COMPOSITION_HALTED_BY_EMERGENCY_STOP",
                success=False,
                tool_name=f"composition.{composition.id}",
                reason=err_msg,
            )
            return SkillCompositionResult(
                composition_id=composition.id,
                execution_id=context.execution_id,
                success=False,
                status=CompositionStatus.CANCELLED,
                error=err_msg,
            )

        # 2. Comprobación de Cancelación previa
        if context.cancellation_token and context.cancellation_token.is_cancelled:
            err_msg = "Composición cancelada antes de iniciar por CancellationToken."
            logger.info(f"[COMPOSITION CANCELLED] {err_msg}")
            return SkillCompositionResult(
                composition_id=composition.id,
                execution_id=context.execution_id,
                success=False,
                status=CompositionStatus.CANCELLED,
                error=err_msg,
            )

        # 3. Validación estructural y estática de la composición
        is_valid, validation_errors, aggregated_risk = self.validator.validate_composition(
            composition=composition,
            current_nesting_level=context.nesting_level,
            max_nesting_level=context.max_nesting_level,
        )
        if not is_valid:
            err_msg = f"Validación de composición fallida: {'; '.join(validation_errors)}"
            logger.error(f"[COMPOSITION REJECTED] {err_msg}")
            self._log_audit(
                event_type=AuditEventType.SECURITY_ALERT,
                operation="COMPOSITION_VALIDATION_FAILED",
                success=False,
                tool_name=f"composition.{composition.id}",
                reason=err_msg,
                metadata={"validation_errors": validation_errors},
            )
            return SkillCompositionResult(
                composition_id=composition.id,
                execution_id=context.execution_id,
                success=False,
                status=CompositionStatus.FAILED,
                error=err_msg,
                aggregated_risk=aggregated_risk,
                warnings=tuple(validation_errors),
            )

        self._log_audit(
            event_type=AuditEventType.EXECUTION_STARTED,
            operation="COMPOSITION_STARTED",
            success=True,
            tool_name=f"composition.{composition.id}",
            reason=f"Iniciando ejecución de composición '{composition.id}' (Modo: {composition.execution_mode})",
            metadata={
                "composition_id": composition.id,
                "execution_mode": str(composition.execution_mode),
                "steps_count": len(composition.steps),
                "aggregated_risk": str(aggregated_risk),
            },
        )

        # 4. Despacho según el modo de ejecución
        step_results: dict[str, SkillCompositionStepResult] = {}
        comp_status = CompositionStatus.COMPLETED
        comp_error: str | None = None

        try:
            if composition.execution_mode == CompositionExecutionMode.SEQUENTIAL:
                step_results, comp_status, comp_error = self._execute_sequential(
                    composition, context, warnings
                )
            elif composition.execution_mode == CompositionExecutionMode.PARALLEL:
                step_results, comp_status, comp_error = self._execute_parallel(
                    composition, context, warnings
                )
            elif composition.execution_mode == CompositionExecutionMode.CONDITIONAL:
                step_results, comp_status, comp_error = self._execute_conditional(
                    composition, context, warnings
                )
            else:
                raise SkillCompositionExecutionError(
                    f"Modo de ejecución no soportado: '{composition.execution_mode}'"
                )

        except Exception as exc:
            comp_status = CompositionStatus.FAILED
            comp_error = f"Excepción crítica durante la orquestación: {exc}"
            logger.error(f"[COMPOSITION EXECUTION ERROR] {comp_error}")

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        # 5. Generar output agregado a partir de output_mapping
        final_output: dict[str, Any] = {}
        if comp_status == CompositionStatus.COMPLETED:
            try:
                if composition.output_mapping:
                    final_output = SkillDataFlowResolver.resolve_mapping(
                        composition.output_mapping, context.inputs, step_results
                    )
                else:
                    # Por defecto, agregar los outputs de todos los pasos ejecutados con éxito
                    final_output = {
                        s_id: s_res.output
                        for s_id, s_res in step_results.items()
                        if s_res.success and not s_res.skipped
                    }
            except Exception as e:
                warnings.append(f"Error generando output_mapping: {e}")
                final_output = {
                    s_id: s_res.output
                    for s_id, s_res in step_results.items()
                    if s_res.success and not s_res.skipped
                }

        steps_executed = sum(1 for r in step_results.values() if not r.skipped)
        steps_skipped = sum(1 for r in step_results.values() if r.skipped)
        success = comp_status == CompositionStatus.COMPLETED

        self._log_audit(
            event_type=AuditEventType.EXECUTION_SUCCEEDED if success else AuditEventType.EXECUTION_FAILED,
            operation="COMPOSITION_COMPLETED" if success else "COMPOSITION_FAILED",
            success=success,
            tool_name=f"composition.{composition.id}",
            reason=f"Composición finalizada con estado '{comp_status}'. {comp_error or ''}".strip(),
            metadata={
                "composition_id": composition.id,
                "status": str(comp_status),
                "duration_ms": elapsed_ms,
                "steps_executed": steps_executed,
                "steps_skipped": steps_skipped,
            },
        )

        return SkillCompositionResult(
            composition_id=composition.id,
            execution_id=context.execution_id,
            success=success,
            status=comp_status,
            output=final_output,
            step_results=step_results,
            aggregated_risk=aggregated_risk,
            error=comp_error,
            duration_ms=elapsed_ms,
            warnings=tuple(warnings),
            steps_executed=steps_executed,
            steps_skipped=steps_skipped,
        )

    # ── MODOS DE EJECUCIÓN ──

    def _execute_sequential(
        self,
        composition: SkillComposition,
        context: SkillCompositionContext,
        warnings: list[str],
    ) -> tuple[dict[str, SkillCompositionStepResult], CompositionStatus, str | None]:
        """Ejecuta los pasos de forma secuencial en orden estricto."""
        step_results: dict[str, SkillCompositionStepResult] = {}

        for step in composition.steps:
            # 1. Comprobación Parada de Emergencia
            if self.emergency_stop.is_stopped():
                return step_results, CompositionStatus.CANCELLED, "Parada de Emergencia activada durante la ejecución."

            # 2. Comprobación Cancelación
            if context.cancellation_token and context.cancellation_token.is_cancelled:
                return step_results, CompositionStatus.CANCELLED, "Ejecución cancelada por CancellationToken."

            # 3. Comprobación de Presupuesto
            if context.budget is not None:
                if (
                    getattr(context.budget, "is_exhausted", lambda: False)()
                    or getattr(context.budget, "max_tool_executions", 1) <= 0
                    or getattr(context.budget, "max_iterations", 1) <= 0
                    or getattr(context.budget, "max_actions", 1) <= 0
                ):
                    return step_results, CompositionStatus.FAILED, "Presupuesto de ejecución (AgentBudget) agotado."

            # 4. Evaluación de condición previa si existe
            if step.condition is not None:
                should_run = SkillConditionEvaluator.evaluate(
                    step.condition, context.inputs, step_results
                )
                if not should_run:
                    logger.info(f"[STEP SKIPPED] Paso '{step.step_id}' omitido por condición falsa.")
                    step_results[step.step_id] = SkillCompositionStepResult(
                        step_id=step.step_id,
                        skill_id=step.skill_id,
                        success=True,
                        status=SkillStatus.COMPLETED,
                        output=None,
                        skipped=True,
                        skip_reason="Condición de ejecución no cumplida",
                    )
                    continue

            # 5. Ejecutar paso individual
            res = self._execute_single_step(step, context, step_results)
            step_results[step.step_id] = res

            if res.status == SkillStatus.WAITING_CONFIRMATION:
                return step_results, CompositionStatus.WAITING_CONFIRMATION, f"Paso '{step.step_id}' requiere confirmación explícita."

            if not res.success:
                if step.error_policy == CompositionErrorPolicy.FAIL_FAST or composition.error_policy == CompositionErrorPolicy.FAIL_FAST:
                    return step_results, CompositionStatus.FAILED, f"Fallo en paso '{step.step_id}' ({res.error})."
                elif step.error_policy == CompositionErrorPolicy.CONTINUE_WHERE_SAFE:
                    warnings.append(f"Paso '{step.step_id}' falló pero se continuó por política CONTINUE_WHERE_SAFE.")
                elif step.error_policy == CompositionErrorPolicy.ROLLBACK_WHERE_SUPPORTED:
                    warnings.append(f"Paso '{step.step_id}' falló. Rollback de compensación solicitado.")
                    return step_results, CompositionStatus.FAILED, f"Fallo con rollback en paso '{step.step_id}'."

        return step_results, CompositionStatus.COMPLETED, None

    def _execute_parallel(
        self,
        composition: SkillComposition,
        context: SkillCompositionContext,
        warnings: list[str],
    ) -> tuple[dict[str, SkillCompositionStepResult], CompositionStatus, str | None]:
        """Ejecuta los pasos independientes de forma concurrente con límite de hilos."""
        step_results: dict[str, SkillCompositionStepResult] = {}
        max_workers = min(max(len(composition.steps), 1), 8)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_step = {
                executor.submit(self._execute_single_step, step, context, {}): step
                for step in composition.steps
            }

            for future in concurrent.futures.as_completed(future_to_step):
                step = future_to_step[future]
                try:
                    res = future.result()
                    step_results[step.step_id] = res
                except Exception as exc:
                    err_res = SkillCompositionStepResult(
                        step_id=step.step_id,
                        skill_id=step.skill_id,
                        success=False,
                        status=SkillStatus.FAILED,
                        error=f"Excepción en hilo paralelo: {exc}",
                    )
                    step_results[step.step_id] = err_res

        # Evaluar resultado global
        failed_steps = [s_id for s_id, r in step_results.items() if not r.success]
        if failed_steps:
            if composition.error_policy == CompositionErrorPolicy.FAIL_FAST:
                return step_results, CompositionStatus.FAILED, f"Fallos en pasos paralelos: {', '.join(failed_steps)}"
            else:
                warnings.append(f"Fallaron pasos en paralelo: {', '.join(failed_steps)}")

        return step_results, CompositionStatus.COMPLETED, None

    def _execute_conditional(
        self,
        composition: SkillComposition,
        context: SkillCompositionContext,
        warnings: list[str],
    ) -> tuple[dict[str, SkillCompositionStepResult], CompositionStatus, str | None]:
        """Ejecuta los pasos evaluando condiciones dinámicas en cada bifurcación."""
        return self._execute_sequential(composition, context, warnings)

    # ── EJECUCIÓN DE PASO INDIVIDUAL BAJO GOBIERNO ──

    def _execute_single_step(
        self,
        step: SkillCompositionStep,
        context: SkillCompositionContext,
        accumulated_results: dict[str, SkillCompositionStepResult],
    ) -> SkillCompositionStepResult:
        """Ejecuta un paso individual garantizando que pase por toda la arquitectura de seguridad."""
        start_time = time.perf_counter()

        # 1. Comprobar Parada de Emergencia previa al paso
        if self.emergency_stop.is_stopped():
            return SkillCompositionStepResult(
                step_id=step.step_id,
                skill_id=step.skill_id,
                success=False,
                status=SkillStatus.CANCELLED,
                error="Parada de Emergencia activa.",
                security_decision="EMERGENCY_STOP",
            )

        # 2. Resolver parámetros de entrada desde el flujo de datos
        try:
            resolved_params = SkillDataFlowResolver.resolve_mapping(
                mapping=step.input_mapping,
                composition_inputs=context.inputs,
                step_results=accumulated_results,
            )
        except DataFlowResolutionError as exc:
            return SkillCompositionStepResult(
                step_id=step.step_id,
                skill_id=step.skill_id,
                success=False,
                status=SkillStatus.FAILED,
                error=f"Error en resolución de parámetros: {exc}",
                security_decision="DATAFLOW_ERROR",
            )

        # 3. Comprobar confirmación requerida a nivel de paso
        if step.requires_confirmation:
            logger.warning(
                f"[STEP CONFIRMATION REQUIRED] El paso '{step.step_id}' ({step.skill_id}) exige confirmación explícita."
            )
            return SkillCompositionStepResult(
                step_id=step.step_id,
                skill_id=step.skill_id,
                success=False,
                status=SkillStatus.WAITING_CONFIRMATION,
                input_parameters=resolved_params,
                error="Confirmación explícita del usuario requerida para este paso.",
                security_decision="WAITING_CONFIRMATION",
            )

        # 4. Delegar ejecución al SkillManager (que aplica SecurityPipeline, Sandbox y Runtime)
        exec_res: SkillResult = self.skill_manager.execute_skill(
            skill_id=step.skill_id,
            parameters=resolved_params,
            session_id=context.session_id,
            user=context.user,
            cancellation_token=context.cancellation_token,
            timeout_seconds=step.timeout_seconds,
            budget=context.budget,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        return SkillCompositionStepResult(
            step_id=step.step_id,
            skill_id=step.skill_id,
            success=exec_res.success,
            status=exec_res.status,
            input_parameters=resolved_params,
            output=exec_res.output,
            error=exec_res.error,
            duration_ms=elapsed_ms,
            security_decision=exec_res.security_decision,
        )

    def _log_audit(
        self,
        event_type: AuditEventType,
        operation: str,
        success: bool,
        tool_name: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            ev = AuditEvent(
                event_type=event_type,
                user="system",
                tool_name=tool_name,
                operation=operation,
                security_level=SecurityLevel.SAFE if success else SecurityLevel.HIGH,
                success=success,
                reason=reason,
                metadata=metadata or {},
            )
            self.audit_logger.log_audit_event(ev)
        except Exception as e:
            logger.error(f"[AUDIT LOG ERROR] No se pudo emitir evento de auditoría en composición: {e}")
