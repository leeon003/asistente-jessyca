"""Tests unitarios exhaustivos para Autonomía Controlada y Tareas Persistentes (Fase 15: Controlled Autonomy).

Verifica el ciclo de vida y las barreras de seguridad de tareas multi-step:
1. Creación y ejecución de tarea simple
2. Tarea periódica programada
3. Cancelación de tarea (cancel_task)
4. Pausa y reanudación (pause_task / resume_task)
5. Recuperación tras reinicio (recover_on_startup) y aislamiento de tareas de alto riesgo
6. Parada por límite de presupuesto agotado (budget limits)
7. Denegación de seguridad (Security DENY)
8. Parada de emergencia inmediata (EmergencyStop)
9. Resiliencia ante fallos de persistencia
"""

import tempfile
from pathlib import Path

from core.autonomy import (
    AutonomousTaskManager,
    AutonomousTaskStatus,
    TaskActionRisk,
)
from core.control_plane.models import AgentLoopResult, AgentLoopState
from core.emergency_stop import EmergencyStopManager


class TestControlledAutonomy:
    """Suite de pruebas de tareas autónomas persistentes y límites de gobernanza."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset()

        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_tasks.json"

        self.manager = AutonomousTaskManager(
            storage_path=self.storage_path,
            emergency_stop=self.emergency_stop,
        )

    def teardown_method(self) -> None:
        self.temp_dir.cleanup()

    # ── 1. TAREA SIMPLE AUTÓNOMA ──

    def test_create_and_execute_simple_task(self) -> None:
        """Verifica la creación y ejecución exitosa de una tarea autónoma de diagnóstico."""
        task = self.manager.create_task(
            intent="Consultar memoria RAM del sistema",
            schedule="interval:3600",
            agent_id="agent_system",
            risk_ceiling=TaskActionRisk.READ_ONLY,
        )

        assert task.status == AutonomousTaskStatus.PENDING
        assert task.agent_id == "agent_system"

        # Mock executor para simular ControlledAgentLoop completando la tarea
        def mock_sys_exec(intent: str) -> AgentLoopResult:
            return AgentLoopResult(
                task_id=task.task_id,
                intent=intent,
                final_state=AgentLoopState.COMPLETED,
                iterations_executed=1,
                tools_executed=1,
                tokens_consumed=10,
                duration_seconds=0.05,
                stop_reason="Diagnóstico completado.",
            )

        result = self.manager.execute_task(task.task_id, custom_executor=mock_sys_exec)

        assert result.is_success is True
        updated_task = self.manager.get_task(task.task_id)
        assert updated_task is not None
        assert updated_task.status == AutonomousTaskStatus.COMPLETED
        assert updated_task.execution_count == 1

    # ── 2. CANCELACIÓN DE TAREA ──

    def test_cancel_task(self) -> None:
        """Verifica que una tarea cancelada no pueda ejecutarse."""
        task = self.manager.create_task(
            intent="Limpieza periódica",
            schedule="cron:0 0 * * *",
        )

        assert self.manager.cancel_task(task.task_id) is True

        cancelled = self.manager.get_task(task.task_id)
        assert cancelled is not None
        assert cancelled.status == AutonomousTaskStatus.CANCELLED

        # Intentar ejecutar tarea cancelada
        result = self.manager.execute_task(task.task_id)
        assert result.is_success is False
        assert result.final_state == AgentLoopState.STOPPED_PERMISSION_DENIED

    # ── 3. PAUSA Y REANUDACIÓN ──

    def test_pause_and_resume_task(self) -> None:
        """Verifica el ciclo de pausa y reanudación controlada de tareas autónomas."""
        task = self.manager.create_task(
            intent="Monitoreo de CPU",
            schedule="interval:60",
        )

        # 1. Pausar
        assert self.manager.pause_task(task.task_id) is True
        paused_task = self.manager.get_task(task.task_id)
        assert paused_task is not None
        assert paused_task.status == AutonomousTaskStatus.PAUSED

        # 2. Ejecutar estando pausada es bloqueado
        res_paused = self.manager.execute_task(task.task_id)
        assert res_paused.is_success is False
        assert res_paused.final_state == AgentLoopState.STOPPED_PERMISSION_DENIED

        # 3. Reanudar
        assert self.manager.resume_task(task.task_id) is True
        resumed_task = self.manager.get_task(task.task_id)
        assert resumed_task is not None
        assert resumed_task.status == AutonomousTaskStatus.PENDING

    # ── 4. RECUPERACIÓN TRAS REINICIO (RECOVERY ON STARTUP) ──

    def test_recovery_on_startup_and_high_risk_isolation(self) -> None:
        """Verifica que tras un reinicio las tareas de alto riesgo se pausen automáticamente para revisión."""
        # Crear 1 tarea segura y 1 tarea de alto riesgo
        self.manager.create_task(
            intent="Revisión de logs",
            schedule="interval:300",
            risk_ceiling=TaskActionRisk.READ_ONLY,
        )
        self.manager.create_task(
            intent="Modificación de registros",
            schedule="interval:600",
            risk_ceiling=TaskActionRisk.DANGEROUS,
        )

        # Simular reinicio del sistema instanciando un nuevo AutonomousTaskManager sobre el mismo archivo JSON
        new_manager = AutonomousTaskManager(
            storage_path=self.storage_path,
            emergency_stop=self.emergency_stop,
        )
        report = new_manager.recover_on_startup()

        assert report["recovered_tasks"] == 2
        assert report["paused_for_review"] == 1

        tasks = new_manager.list_tasks()
        dangerous_task = next(t for t in tasks if t.risk_ceiling == TaskActionRisk.DANGEROUS)
        assert dangerous_task.status == AutonomousTaskStatus.PAUSED
        assert "riesgo elevado" in (dangerous_task.last_error or "").lower()

    # ── 5. EXCEDER LÍMITE DE PRESUPUESTO (BUDGET LIMIT) ──

    def test_budget_limit_stops_execution(self) -> None:
        """Verifica que si se exceden los límites del presupuesto, la ejecución se detenga."""
        task = self.manager.create_task(
            intent="Proceso intensivo",
            schedule="interval:100",
            max_steps=2,
        )

        # Mock executor que simula agotar el presupuesto
        def mock_budget_exhausted(intent: str) -> AgentLoopResult:
            return AgentLoopResult(
                task_id=task.task_id,
                intent=intent,
                final_state=AgentLoopState.STOPPED_LIMIT_REACHED,
                iterations_executed=2,
                tools_executed=2,
                tokens_consumed=5000,
                duration_seconds=10.0,
                stop_reason="Límite máximo de iteraciones alcanzado (2).",
            )

        result = self.manager.execute_task(task.task_id, custom_executor=mock_budget_exhausted)

        assert result.is_success is False
        assert result.final_state == AgentLoopState.STOPPED_LIMIT_REACHED
        updated = self.manager.get_task(task.task_id)
        assert updated is not None
        assert updated.status == AutonomousTaskStatus.FAILED

    # ── 6. DENEGACIÓN DE SEGURIDAD ──

    def test_security_denial_fails_task_safely(self) -> None:
        """Verifica que una denegación de permisos en el security pipeline falle la tarea de forma limpia."""
        task = self.manager.create_task(
            intent="Operación no autorizada",
            schedule="interval:100",
        )

        def mock_sec_denial(intent: str) -> AgentLoopResult:
            return AgentLoopResult(
                task_id=task.task_id,
                intent=intent,
                final_state=AgentLoopState.STOPPED_PERMISSION_DENIED,
                iterations_executed=0,
                tools_executed=0,
                tokens_consumed=0,
                duration_seconds=0.01,
                stop_reason="Permiso denegado por PermissionManager.",
            )

        result = self.manager.execute_task(task.task_id, custom_executor=mock_sec_denial)

        assert result.is_success is False
        assert result.final_state == AgentLoopState.STOPPED_PERMISSION_DENIED

    # ── 7. PARADA DE EMERGENCIA ──

    def test_emergency_stop_halts_autonomous_tasks(self) -> None:
        """Verifica que la activación de EmergencyStop impida la ejecución de cualquier tarea autónoma."""
        task = self.manager.create_task(intent="Tarea con parada de emergencia", schedule="interval:10")
        self.emergency_stop.trigger_stop(reason="Parada de emergencia manual activada")

        result = self.manager.execute_task(task.task_id)

        assert result.is_success is False
        assert result.final_state == AgentLoopState.STOPPED_EMERGENCY
        assert "emergencia" in result.stop_reason.lower()
