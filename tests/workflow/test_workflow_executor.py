"""Tests completos para el Motor de Workflows Multi-Step y WorkflowExecutor (Etapa 18.1).

Verifica:
1. Cada step pasa individualmente por SecureExecutionPipeline (validate -> authorize -> execute -> verify -> record).
2. Resolución topológica de dependencias por DAG e interpolación de variables.
3. Control de Timeout global y por paso.
4. Cancelación determinista (cancel) y marcado de pasos pendientes.
5. Pausa y Reanudación (pause -> resume).
6. Regla Inmutable de Verificación: NO ejecutar el siguiente step si la verificación del anterior falló.
7. Manejo de fallos (stop_on_failure) e interrupción limpia.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from core.autonomy.autonomy_governor import get_autonomy_governor
from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk
from core.workflow import (
    StepExecutionPipeline,
    StepExecutionResult,
    StepState,
    StepVerificationRule,
    WorkflowDefinition,
    WorkflowExecutor,
    WorkflowState,
    WorkflowStep,
)


class TestWorkflowStepPipeline:
    """Pruebas del pipeline de 5 fases para pasos individuales."""

    def setup_method(self) -> None:
        self.governor = get_autonomy_governor()
        self.governor.reset_to_default()
        self.pipeline = StepExecutionPipeline(governor=self.governor)

    def test_single_step_full_pipeline_success(self) -> None:
        step = WorkflowStep(
            step_id="step_read",
            name="Leer archivo",
            tool_name="filesystem",
            operation="read",
            parameters={"path": "C:\\data.txt"},
            risk_level=TaskActionRisk.READ_ONLY,
            requires_verification=True,
            verification_rule=StepVerificationRule(
                rule_name="output_not_empty",
                validator_fn=lambda out: bool(out and out.get("content")),
                expected_description="El contenido debe estar presente",
            ),
        )

        def mock_tool(tool: str, op: str, params: dict[str, Any]) -> Any:
            return {"status": "ok", "content": "hello world"}

        result = self.pipeline.process_step(
            step=step,
            workflow_id="wf_test_01",
            correlation_id="corr_test_01",
            previous_results={},
            tool_invoker=mock_tool,
        )

        assert result.success is True
        assert result.state == StepState.COMPLETED
        assert result.verification_passed is True
        assert result.output == {"status": "ok", "content": "hello world"}

    def test_step_verification_failure_halts_step(self) -> None:
        """Si la regla de verificación falla, el step entra en FAILED y verification_passed=False."""
        step = WorkflowStep(
            step_id="step_calc",
            name="Cálculo matemático",
            tool_name="filesystem",
            operation="read",
            parameters={"path": "C:\\data.txt"},
            requires_verification=True,
            verification_rule=StepVerificationRule(
                rule_name="must_equal_5",
                validator_fn=lambda out: out.get("value") == 5,  # Espera 5 pero devolverá 4
                expected_description="Resultado debe ser 5",
            ),
        )

        def mock_tool(tool: str, op: str, params: dict[str, Any]) -> Any:
            return {"value": 4}

        result = self.pipeline.process_step(
            step=step,
            workflow_id="wf_test_02",
            correlation_id="corr_test_02",
            previous_results={},
            tool_invoker=mock_tool,
        )

        assert result.success is False
        assert result.state == StepState.FAILED
        assert result.verification_passed is False
        assert "Fallo en verificación post-ejecución" in str(result.error)


class TestWorkflowExecutorE2E:
    """Pruebas de integración para WorkflowExecutor."""

    def setup_method(self) -> None:
        self.governor = get_autonomy_governor()
        self.governor.reset_to_default()
        self.executor = WorkflowExecutor()

    def test_sequential_workflow_execution_with_interpolation(self) -> None:
        """Ejecuta workflow de 2 pasos dependientes con interpolación de variables."""
        step1 = WorkflowStep(
            step_id="step_create",
            name="Crear documento",
            tool_name="document",
            operation="create",
            parameters={"title": "Reporte"},
            risk_level=TaskActionRisk.LOW_RISK,
        )
        step2 = WorkflowStep(
            step_id="step_notify",
            name="Notificar creación",
            tool_name="notification",
            operation="send",
            parameters={"msg": "Documento creado con ID {{step_create.output.doc_id}}"},
            dependencies=("step_create",),
            risk_level=TaskActionRisk.LOW_RISK,
        )

        workflow = WorkflowDefinition.create(
            name="Create and Notify",
            steps=[step1, step2],
        )

        def mock_invoker(tool: str, op: str, params: dict[str, Any]) -> Any:
            if tool == "document":
                return {"doc_id": "DOC-9941"}
            elif tool == "notification":
                return {"sent": True, "delivered_msg": params.get("msg")}
            return {}

        result = self.executor.execute(workflow, tool_invoker=mock_invoker)

        assert result.success is True
        assert result.state == WorkflowState.COMPLETED
        assert result.completed_steps == ("step_create", "step_notify")
        assert result.step_results["step_notify"].output["delivered_msg"] == "Documento creado con ID DOC-9941"

    def test_verification_failure_prevents_subsequent_step_execution(self) -> None:
        """REQUISITO CRÍTICO: NO ejecutar automáticamente el siguiente step si el anterior requería verification y falló."""
        step1 = WorkflowStep(
            step_id="step_export",
            name="Exportar datos",
            tool_name="document",
            operation="export",
            requires_verification=True,
            verification_rule=StepVerificationRule(
                rule_name="file_size_check",
                validator_fn=lambda out: out.get("row_count", 0) > 0,  # Espera > 0 filas
                expected_description="Debe haber al menos 1 fila",
            ),
        )
        step2_invoked = False
        step2 = WorkflowStep(
            step_id="step_notify_email",
            name="Enviar notificación con archivo",
            tool_name="notification",
            operation="send",
            dependencies=("step_export",),
            risk_level=TaskActionRisk.LOW_RISK,
        )

        workflow = WorkflowDefinition.create(
            name="Export and Notify",
            steps=[step1, step2],
        )

        def mock_invoker(tool: str, op: str, params: dict[str, Any]) -> Any:
            nonlocal step2_invoked
            if tool == "document":
                return {"row_count": 0}  # CERO FILAS -> FALLARÁ VERIFICACIÓN
            if tool == "notification":
                step2_invoked = True
                return {"sent": True}
            return {}

        result = self.executor.execute(workflow, tool_invoker=mock_invoker)

        # El workflow debe fallar
        assert result.success is False
        assert result.state == WorkflowState.FAILED
        assert result.failed_step_id == "step_export"
        assert result.step_results["step_export"].verification_passed is False

        # El step 2 NUNCA debió haberse ejecutado
        assert step2_invoked is False
        assert result.step_results["step_notify_email"].state == StepState.SKIPPED

    def test_cancellation_aborts_workflow_cleanly(self) -> None:
        """Verifica que cancel() aborte el workflow deterministamente."""
        step1 = WorkflowStep(step_id="s1", name="Paso 1", tool_name="filesystem", operation="read")
        step2 = WorkflowStep(step_id="s2", name="Paso 2", tool_name="filesystem", operation="read", dependencies=("s1",))

        workflow = WorkflowDefinition.create(name="Cancellable Flow", steps=[step1, step2])

        def slow_invoker(tool: str, op: str, params: dict[str, Any]) -> Any:
            self.executor.cancel(reason="Prueba de cancelación de usuario")
            return {"ok": True}

        result = self.executor.execute(workflow, tool_invoker=slow_invoker)

        assert result.state == WorkflowState.CANCELLED
        assert result.success is False
        assert "Prueba de cancelación" in str(result.error)

    def test_pause_and_resume_execution(self) -> None:
        """Verifica que pause() detenga y resume() continúe la ejecución de pasos."""
        step1 = WorkflowStep(step_id="s1", name="Paso 1", tool_name="filesystem", operation="read")
        step2 = WorkflowStep(step_id="s2", name="Paso 2", tool_name="filesystem", operation="read", dependencies=("s1",))

        workflow = WorkflowDefinition.create(name="Pausable Flow", steps=[step1, step2])

        import threading

        def pause_invoker(tool: str, op: str, params: dict[str, Any]) -> Any:
            if tool == "filesystem" and op == "read" and params == {}:
                # Pausar antes del paso 2
                self.executor.pause()
                # Reanudar en hilo separado tras breve espera
                threading.Thread(target=lambda: (time.sleep(0.05), self.executor.resume())).start()
            return {"status": "ok"}

        result = self.executor.execute(workflow, tool_invoker=pause_invoker)

        assert result.success is True
        assert result.state == WorkflowState.COMPLETED
        assert len(result.completed_steps) == 2

    def test_global_workflow_timeout(self) -> None:
        """Verifica que el workflow respete el límite de timeout global."""
        step1 = WorkflowStep(step_id="s1", name="Paso lento", tool_name="filesystem", operation="read")
        workflow = WorkflowDefinition.create(name="Timeout Flow", steps=[step1], timeout_sec=0.05)

        def slow_call(tool: str, op: str, params: dict[str, Any]) -> Any:
            time.sleep(0.08)
            return {}

        result = self.executor.execute(workflow, tool_invoker=slow_call)

        assert result.success is False
        assert result.state == WorkflowState.FAILED
        assert "timeout" in str(result.error).lower()
