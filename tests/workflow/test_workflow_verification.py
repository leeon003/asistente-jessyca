"""Tests exhaustivos para la Verificación entre pasos de Workflows (Etapa 18.3).

Verifica:
1. Success: Action -> Observe -> Compare -> VERIFIED_SUCCESS.
2. Mismatch: Discrepancia entre estado esperado y observado -> MISMATCH.
3. Timeout: Expiración del tiempo de sondeo de observación -> TIMEOUT.
4. Stale State: Detección y rechazo de estado obsoleto -> STALE_STATE.
5. Cancellation: Interrupción por cancelación durante la verificación -> CANCELLED.
6. Rollback: Ejecución de compensación tras fallo con política RECOVER -> ROLLBACK.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.autonomy.autonomy_governor import get_autonomy_governor
from core.autonomy.autonomy_level import TaskActionRisk
from core.workflow import (
    ExpectedState,
    ObservedState,
    StepState,
    VerificationFailurePolicy,
    VerificationStatus,
    WorkflowDefinition,
    WorkflowExecutor,
    WorkflowState,
    WorkflowStep,
    WorkflowStepVerifier,
)


class TestWorkflowStepVerifierUnit:
    """Pruebas unitarias de WorkflowStepVerifier."""

    def test_verification_success(self) -> None:
        """Verifica que valores coincidentes generen VERIFIED_SUCCESS."""
        expected = ExpectedState(
            expected_values={"file_size": 1024, "status": "saved"},
            description="El archivo debe tener 1024 bytes y status saved",
        )
        action_output = {"file_size": 1024, "status": "saved", "extra": "info"}

        res = WorkflowStepVerifier.verify(expected=expected, action_output=action_output)

        assert res.status == VerificationStatus.VERIFIED_SUCCESS
        assert res.passed is True
        assert len(res.mismatches) == 0

    def test_verification_mismatch(self) -> None:
        """Verifica que una discrepancia en valores genere MISMATCH."""
        expected = ExpectedState(
            expected_values={"exit_code": 0, "verified": True},
        )
        action_output = {"exit_code": 1, "verified": True}

        res = WorkflowStepVerifier.verify(expected=expected, action_output=action_output)

        assert res.status == VerificationStatus.MISMATCH
        assert res.passed is False
        assert any("exit_code" in m for m in res.mismatches)

    def test_verification_timeout_with_observer_polling(self) -> None:
        """Verifica que el sondeo continuo expire con TIMEOUT si la condición no se cumple."""
        expected = ExpectedState(
            expected_values={"ready": True},
            timeout_sec=0.08,
            poll_interval_sec=0.02,
        )

        # Observer que siempre devuelve ready=False
        def mock_observer() -> dict[str, Any]:
            return {"ready": False}

        res = WorkflowStepVerifier.verify(
            expected=expected,
            action_output={},
            observer_fn=mock_observer,
        )

        assert res.status == VerificationStatus.TIMEOUT
        assert res.passed is False
        assert "Timeout de verificación superado" in res.reason

    def test_verification_stale_state_detection(self) -> None:
        """Verifica que estados con timestamp obsoleto generen STALE_STATE."""
        expected = ExpectedState(
            expected_values={"status": "ok"},
            max_stale_seconds=5.0,
        )

        # Timestamp de hace 1 hora (obsoleto)
        stale_time = datetime.now(UTC) - timedelta(hours=1)
        stale_obs = ObservedState(data={"status": "ok"}, timestamp=stale_time)

        res = WorkflowStepVerifier.verify(
            expected=expected,
            action_output={},
            observer_fn=lambda: stale_obs,
        )

        assert res.status == VerificationStatus.STALE_STATE
        assert res.passed is False
        assert "obsoleto" in res.reason.lower()

    def test_verification_cancellation(self) -> None:
        """Verifica que una señal de cancelación aborte la verificación como CANCELLED."""
        expected = ExpectedState(
            expected_values={"status": "ok"},
            timeout_sec=1.0,
        )

        res = WorkflowStepVerifier.verify(
            expected=expected,
            action_output={"status": "ok"},
            is_cancelled_fn=lambda: True,
        )

        assert res.status == VerificationStatus.CANCELLED
        assert res.passed is False


class TestWorkflowExecutorWithVerification:
    """Pruebas de integración para WorkflowExecutor con ExpectedState y Rollback."""

    def setup_method(self) -> None:
        self.governor = get_autonomy_governor()
        self.governor.reset_to_default()
        self.executor = WorkflowExecutor()

    def test_workflow_stops_on_verification_failure(self) -> None:
        """Verifica que un fallo de verificación con policy STOP detenga el workflow."""
        step1 = WorkflowStep(
            step_id="s1_write",
            name="Escribir configuración",
            tool_name="filesystem",
            operation="read",
            expected_state=ExpectedState(
                expected_values={"valid_checksum": True},
                failure_policy=VerificationFailurePolicy.STOP,
            ),
        )
        step2_executed = False
        step2 = WorkflowStep(
            step_id="s2_notify",
            name="Notificar",
            tool_name="notification",
            operation="send",
            dependencies=("s1_write",),
        )

        workflow = WorkflowDefinition.create(
            name="Stop on Verification Mismatch",
            steps=[step1, step2],
        )

        def mock_invoker(tool: str, op: str, params: dict[str, Any]) -> Any:
            nonlocal step2_executed
            if tool == "filesystem":
                return {"valid_checksum": False}  # DISCREPANCIA
            if tool == "notification":
                step2_executed = True
                return {}
            return {}

        result = self.executor.execute(workflow, tool_invoker=mock_invoker)

        assert result.success is False
        assert result.state == WorkflowState.FAILED
        assert result.failed_step_id == "s1_write"
        assert result.step_results["s1_write"].verification_passed is False
        assert step2_executed is False
        assert result.step_results["s2_notify"].state == StepState.SKIPPED

    def test_workflow_rollback_compensation_on_verification_failure(self) -> None:
        """Verifica que un fallo de verificación con policy RECOVER ejecute acciones de rollback."""
        step1 = WorkflowStep(
            step_id="s1_create_file",
            name="Crear archivo temporal",
            tool_name="document",
            operation="create",
            parameters={"filename": "temp_report.csv"},
            compensation_tool="document",
            compensation_operation="export",  # rollback tool
            compensation_parameters={"action": "cleanup_temp_report.csv"},
            risk_level=TaskActionRisk.LOW_RISK,
        )

        step2 = WorkflowStep(
            step_id="s2_process",
            name="Procesar archivo",
            tool_name="filesystem",
            operation="read",
            dependencies=("s1_create_file",),
            expected_state=ExpectedState(
                expected_values={"rows_processed": 50},  # Espera 50 pero devolverá 0
                failure_policy=VerificationFailurePolicy.RECOVER,
            ),
            risk_level=TaskActionRisk.LOW_RISK,
        )

        workflow = WorkflowDefinition.create(
            name="Rollback Flow",
            steps=[step1, step2],
        )

        rollback_executed = False

        def mock_invoker(tool: str, op: str, params: dict[str, Any]) -> Any:
            nonlocal rollback_executed
            if tool == "document" and op == "create":
                return {"status": "created", "doc_id": "DOC-101"}
            elif tool == "filesystem" and op == "read":
                return {"rows_processed": 0}  # Falla verificación
            elif tool == "document" and op == "export" and "cleanup" in str(params.get("action")):
                rollback_executed = True
                return {"status": "cleaned"}
            return {}

        result = self.executor.execute(workflow, tool_invoker=mock_invoker)

        # El workflow debe fallar tras haber ejecutado rollback
        assert result.success is False
        assert result.state == WorkflowState.FAILED
        assert result.failed_step_id == "s2_process"
        assert rollback_executed is True
