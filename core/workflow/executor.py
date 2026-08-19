"""WorkflowExecutor — Motor de Ejecución de Workflows Multi-Step (Etapa 18.1).

Garantiza:
  - Resolución topológica de dependencias (DAG).
  - Ejecución paso a paso a través de StepExecutionPipeline (validate -> authorize -> execute -> verify -> record).
  - Control de Timeout global y por paso.
  - Soporte de Pausa (pause) y Reanudación (resume).
  - Soporte de Cancelación determinista (cancel).
  - Interrupción inmediata ante fallo o fallo de verificación (no auto-progreso si verification falló).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from core.logger import get_logger
from core.observability.structured_event import CorrelationId
from core.workflow.models import (
    StepExecutionResult,
    StepState,
    WorkflowDefinition,
    WorkflowExecutionResult,
    WorkflowState,
    WorkflowStep,
)
from core.workflow.step_pipeline import StepExecutionPipeline

logger = get_logger("jessyca.workflow.executor")


class WorkflowExecutor:
    """Ejecutor de flujos de trabajo multi-paso con control de ciclo de vida y seguridad."""

    def __init__(self, step_pipeline: StepExecutionPipeline | None = None) -> None:
        self.pipeline = step_pipeline or StepExecutionPipeline()
        self._lock = threading.RLock()

        # Flags de control de ciclo de vida
        self._is_cancelled = False
        self._cancellation_reason: str | None = None
        self._is_paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # Inicialmente no pausado (permite ejecución)

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._is_cancelled

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._is_paused

    def cancel(self, reason: str = "Cancelación solicitada por el usuario") -> None:
        """Cancela la ejecución del workflow de forma determinista."""
        with self._lock:
            self._is_cancelled = True
            self._cancellation_reason = reason
            self._pause_event.set()  # Desbloquear si estaba pausado para salir
            logger.warning(f"[WORKFLOW EXECUTOR] Workflow cancelado: {reason}")

    def pause(self) -> None:
        """Pausa la ejecución del workflow tras completar el paso activo."""
        with self._lock:
            if not self._is_paused:
                self._is_paused = True
                self._pause_event.clear()
                logger.info("[WORKFLOW EXECUTOR] Workflow pausado.")

    def resume(self) -> None:
        """Reanuda la ejecución de un workflow pausado."""
        with self._lock:
            if self._is_paused:
                self._is_paused = False
                self._pause_event.set()
                logger.info("[WORKFLOW EXECUTOR] Workflow reanudado.")

    def execute(
        self,
        workflow: WorkflowDefinition,
        tool_invoker: Callable[[str, str, dict[str, Any]], Any] | None = None,
        correlation_id: str | CorrelationId | None = None,
    ) -> WorkflowExecutionResult:
        """Ejecuta el workflow multi-paso resolviendo el DAG y ejecutando cada paso por el pipeline."""
        start_time = time.perf_counter()
        c_id = correlation_id or CorrelationId.generate(prefix="wf_corr_")
        workflow_id = workflow.workflow_id

        logger.info(f"[WORKFLOW EXECUTOR] Iniciando ejecución de workflow '{workflow_id}' ({workflow.name}) con {len(workflow.steps)} pasos.")

        # Resetear estado de control interno
        with self._lock:
            self._is_cancelled = False
            self._cancellation_reason = None
            self._is_paused = False
            self._pause_event.set()

        completed_steps: list[str] = []
        step_results: dict[str, StepExecutionResult] = {}
        pending_steps: dict[str, WorkflowStep] = {s.step_id: s for s in workflow.steps}

        state = WorkflowState.RUNNING
        failed_step_id: str | None = None
        global_error: str | None = None

        # Bucle de orquestación del DAG
        while pending_steps and not self.is_cancelled:
            # 1. Comprobar timeout global del workflow
            elapsed_total = time.perf_counter() - start_time
            if elapsed_total > workflow.timeout_sec:
                state = WorkflowState.FAILED
                global_error = f"Workflow timeout superado ({elapsed_total:.2f}s > {workflow.timeout_sec}s)."
                logger.error(f"[WORKFLOW EXECUTOR] {global_error}")
                break

            # 2. Comprobar pausa
            if self.is_paused:
                state = WorkflowState.PAUSED
                logger.debug("[WORKFLOW EXECUTOR] Esperando reanudación de pausa...")
                self._pause_event.wait()
                if self.is_cancelled:
                    break
                state = WorkflowState.RUNNING

            # 3. Encontrar pasos listos (cuyas dependencias están todas en completed_steps)
            ready_step_ids = [
                sid for sid, s in pending_steps.items()
                if all(dep in completed_steps for dep in s.dependencies)
            ]

            if not ready_step_ids:
                # Si quedan pasos pendientes pero ninguno está listo, hay un ciclo o fallo previo
                state = WorkflowState.FAILED
                global_error = "Bloqueo en el DAG: no hay pasos listos con dependencias satisfechas."
                logger.error(f"[WORKFLOW EXECUTOR] {global_error}")
                break

            # 4. Seleccionar y ejecutar el siguiente paso listo
            curr_step_id = ready_step_ids[0]
            curr_step = pending_steps.pop(curr_step_id)

            # Ejecutar a través del pipeline de seguridad de 5 fases
            step_res = self.pipeline.process_step(
                step=curr_step,
                workflow_id=workflow_id,
                correlation_id=c_id,
                previous_results=step_results,
                tool_invoker=tool_invoker,
            )
            step_results[curr_step_id] = step_res

            # 5. Evaluar resultado del paso
            if step_res.success and step_res.verification_passed:
                completed_steps.append(curr_step_id)
                logger.info(f"[WORKFLOW EXECUTOR] Step '{curr_step_id}' completado exitosamente.")
            else:
                failed_step_id = curr_step_id
                global_error = step_res.error or f"Step '{curr_step_id}' falló en la ejecución o verificación."
                logger.error(f"[WORKFLOW EXECUTOR] Step '{curr_step_id}' falló: {global_error}")

                if workflow.stop_on_failure:
                    state = WorkflowState.FAILED

                    # Comprobar si se debe disparar rollback/compensación
                    should_recover = False
                    if curr_step.expected_state is not None:
                        from core.workflow.verification import VerificationFailurePolicy
                        if getattr(curr_step.expected_state, "failure_policy", None) == VerificationFailurePolicy.RECOVER:
                            should_recover = True

                    if should_recover and completed_steps:
                        logger.warning(f"[WORKFLOW EXECUTOR] Iniciando ROLLBACK compensatorio para {len(completed_steps)} pasos completados previamente...")
                        state = WorkflowState.ROLLING_BACK
                        for prev_id in reversed(completed_steps):
                            prev_step = workflow.get_step(prev_id)
                            if prev_step and prev_step.compensation_tool and tool_invoker:
                                try:
                                    logger.info(f"[ROLLBACK] Revertiendo step '{prev_id}' mediante {prev_step.compensation_tool}.{prev_step.compensation_operation}")
                                    tool_invoker(
                                        prev_step.compensation_tool,
                                        prev_step.compensation_operation or "rollback",
                                        prev_step.compensation_parameters,
                                    )
                                except Exception as exc:
                                    logger.error(f"[ROLLBACK] Error ejecutando compensación para step '{prev_id}': {exc}")
                        state = WorkflowState.FAILED

                    # Marcar los pasos pendientes como SKIPPED
                    for s_id in pending_steps:
                        step_results[s_id] = StepExecutionResult(
                            step_id=s_id,
                            state=StepState.SKIPPED,
                            success=False,
                            error="Omitido por fallo en paso previo.",
                            verification_passed=False,
                        )
                    break

        # Determinar estado final
        total_duration_ms = (time.perf_counter() - start_time) * 1000

        if self.is_cancelled:
            state = WorkflowState.CANCELLED
            global_error = self._cancellation_reason or "Cancelado durante la ejecución."
            for s_id in pending_steps:
                if s_id not in step_results:
                    step_results[s_id] = StepExecutionResult(
                        step_id=s_id,
                        state=StepState.CANCELLED,
                        success=False,
                        error="Cancelado por usuario o Emergency Stop.",
                        verification_passed=False,
                    )
        elif total_duration_ms / 1000.0 > workflow.timeout_sec:
            state = WorkflowState.FAILED
            global_error = f"Workflow timeout superado ({total_duration_ms/1000.0:.2f}s > {workflow.timeout_sec}s)."
            logger.error(f"[WORKFLOW EXECUTOR] {global_error}")
        elif not pending_steps and state != WorkflowState.FAILED:
            state = WorkflowState.COMPLETED

        return WorkflowExecutionResult(
            workflow_id=workflow_id,
            state=state,
            success=(state == WorkflowState.COMPLETED),
            completed_steps=tuple(completed_steps),
            failed_step_id=failed_step_id,
            step_results=step_results,
            duration_ms=total_duration_ms,
            error=global_error,
        )
