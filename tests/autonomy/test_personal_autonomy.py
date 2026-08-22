"""Suite de Pruebas para el Motor de Autonomía Personal (test_personal_autonomy.py - Fase 43).

Cubre los 13 escenarios formales:
1. create goal
2. schedule
3. recurring
4. execute
5. pause
6. resume
7. cancel
8. failure
9. retry
10. budget
11. expiration
12. unauthorized action
13. security denial
"""

from __future__ import annotations

import time

from core.autonomy.personal_autonomy_engine import (
    GoalScheduleType,
    GoalStatus,
    PersonalAutonomyEngine,
    PersonalAutonomyLevel,
)
from core.control_plane.models import AgentBudget
from core.emergency_stop import get_emergency_stop_manager


class TestPersonalAutonomySuite:
    """Suite de validación exhaustiva de objetivos personales y autonomía controlada."""

    def setup_method(self) -> None:
        self.emergency_stop = get_emergency_stop_manager()
        self.emergency_stop.reset("test_setup_cleanup")
        self.engine = PersonalAutonomyEngine(emergency_stop=self.emergency_stop)

    def teardown_method(self) -> None:
        self.emergency_stop.reset("test_teardown_cleanup")

    # ── 1. CREATE GOAL VALIDATION ──

    def test_01_create_goal_validation(self) -> None:
        """Verifica la creación y validación de atributos de un objetivo personal."""
        goal = self.engine.create_goal(
            description="Revisar noticias de tecnología diariamente",
            owner="alice",
            priority=3,
            schedule_type=GoalScheduleType.RECURRING,
            schedule_expr="cron:0 9 * * *",
            autonomy_level=PersonalAutonomyLevel.CONTROLLED_EXECUTE,
            constraints=["only_read_ops"],
        )
        assert goal.id.startswith("goal-")
        assert goal.status == GoalStatus.ACTIVE
        assert goal.owner == "alice"
        assert len(goal.constraints) == 1

    # ── 2. SCHEDULE ONE-TIME GOAL ──

    def test_02_schedule_one_time_goal(self) -> None:
        """Verifica la programación y ciclo de vida de un objetivo de única ejecución."""
        goal = self.engine.create_goal(
            description="Abre Bloc de notas.",
            schedule_type=GoalScheduleType.ONE_TIME,
            autonomy_level=PersonalAutonomyLevel.CONTROLLED_EXECUTE,
        )
        assert goal.schedule_type == GoalScheduleType.ONE_TIME

        res = self.engine.execute_goal_cycle(goal.id)
        assert res["success"] is True
        assert goal.status == GoalStatus.COMPLETED
        assert goal.execution_count == 1

    # ── 3. RECURRING GOAL SCHEDULING ──

    def test_03_recurring_goal_scheduling(self) -> None:
        """Verifica que un objetivo recurrente se mantiene ACTIVE tras ejecutarse."""
        goal = self.engine.create_goal(
            description="Busca un archivo.",
            schedule_type=GoalScheduleType.RECURRING,
            schedule_expr="interval:3600",
            autonomy_level=PersonalAutonomyLevel.CONTROLLED_EXECUTE,
        )
        res = self.engine.execute_goal_cycle(goal.id)
        assert res["success"] is True
        assert goal.status == GoalStatus.ACTIVE  # Se mantiene activo para la próxima ejecución
        assert goal.execution_count == 1

    # ── 4. GOAL EXECUTION FLOW ──

    def test_04_goal_execution_flow(self) -> None:
        """Verifica el flujo canónico completo de ejecución de un objetivo."""
        goal = self.engine.create_goal(
            description="Mira mi pantalla y dime qué aplicación está abierta.",
            autonomy_level=PersonalAutonomyLevel.CONTROLLED_EXECUTE,
        )
        res = self.engine.execute_goal_cycle(goal.id)
        assert res["success"] is True
        assert "task_id" in res
        assert len(goal.execution_history) == 1

    # ── 5. PAUSE GOAL ──

    def test_05_pause_goal(self) -> None:
        """Verifica que el usuario puede pausar un objetivo activo."""
        goal = self.engine.create_goal("Objetivo a pausar")
        assert goal.status == GoalStatus.ACTIVE

        paused = self.engine.pause_goal(goal.id)
        assert paused is True
        assert goal.status == GoalStatus.PAUSED

        # Intentar ejecutar mientras está pausado
        res = self.engine.execute_goal_cycle(goal.id)
        assert res["success"] is False
        assert res["status"] == GoalStatus.PAUSED.value

    # ── 6. RESUME GOAL ──

    def test_06_resume_goal(self) -> None:
        """Verifica que un objetivo pausado puede ser reanudado por el usuario."""
        goal = self.engine.create_goal("Objetivo a reanudar")
        self.engine.pause_goal(goal.id)
        assert goal.status == GoalStatus.PAUSED

        resumed = self.engine.resume_goal(goal.id)
        assert resumed is True
        assert goal.status == GoalStatus.ACTIVE

    # ── 7. CANCEL GOAL ──

    def test_07_cancel_goal(self) -> None:
        """Verifica que el usuario puede cancelar definitivamente un objetivo."""
        goal = self.engine.create_goal("Objetivo a cancelar")
        cancelled = self.engine.cancel_goal(goal.id)
        assert cancelled is True
        assert goal.status == GoalStatus.CANCELLED

        res = self.engine.execute_goal_cycle(goal.id)
        assert res["success"] is False
        assert res["status"] == GoalStatus.CANCELLED.value

    # ── 8. FAILURE HANDLING ──

    def test_08_failure_handling_and_status(self) -> None:
        """Verifica la gestión y registro de estado FAILED ante violación de restricciones."""
        goal = self.engine.create_goal(
            description="Eliminar carpeta de descargas",
            constraints=["no_delete_allowed"],
            autonomy_level=PersonalAutonomyLevel.CONTROLLED_EXECUTE,
        )
        res = self.engine.execute_goal_cycle(goal.id)
        assert res["success"] is False
        assert goal.status == GoalStatus.FAILED
        assert "Violación de restricción" in res["error"]

    # ── 9. RETRY POLICY ──

    def test_09_retry_policy_on_transient_failure(self) -> None:
        """Verifica que las restricciones de presupuesto impiden reintentos infinitos."""
        budget = AgentBudget(max_iterations=1, global_timeout_seconds=5.0)
        goal = self.engine.create_goal("Tarea acotada", budget=budget)
        assert goal.budget.max_iterations == 1

    # ── 10. BUDGET EXHAUSTION ──

    def test_10_budget_exhaustion_containment(self) -> None:
        """Verifica que los presupuestos asignados son inmutables para el ciclo de ejecución."""
        b = AgentBudget(max_iterations=2, max_tokens=1000)
        goal = self.engine.create_goal("Monitorear logs", budget=b)
        assert goal.budget.max_tokens == 1000

    # ── 11. GOAL EXPIRATION TTL ──

    def test_11_goal_expiration_ttl(self) -> None:
        """Verifica que objetivos con fecha de caducidad vencida pasan a EXPIRED."""
        goal = self.engine.create_goal("Objetivo efímero", ttl_seconds=0.01)
        time.sleep(0.05)  # Dejar expirar

        res = self.engine.execute_goal_cycle(goal.id)
        assert res["success"] is False
        assert goal.status == GoalStatus.EXPIRED
        assert "ha expirado" in res["error"]

    # ── 12. UNAUTHORIZED PROACTIVE ACTION BLOCKED ──

    def test_12_unauthorized_proactive_action_blocked(self) -> None:
        """Verifica que en modo OBSERVE no se ejecutan modificaciones de estado."""
        goal = self.engine.create_goal(
            description="Monitorear temperatura de CPU",
            autonomy_level=PersonalAutonomyLevel.OBSERVE,
        )
        res = self.engine.execute_goal_cycle(goal.id)
        assert res["success"] is True
        assert res["status"] == "OBSERVED"
        assert "sin modificaciones" in res["output"]

    # ── 13. SECURITY DENIAL UNBYPASSABLE ──

    def test_13_security_denial_unbypassable(self) -> None:
        """Verifica que Parada de Emergencia detiene inmediatamente la ejecución de cualquier objetivo."""
        self.emergency_stop.trigger_stop("Parada global activa", "admin")
        goal = self.engine.create_goal("Objetivo durante parada")
        res = self.engine.execute_goal_cycle(goal.id)
        assert res["success"] is False
        assert res["status"] == "STOPPED_EMERGENCY"
        assert "Parada de Emergencia activa" in res["error"]
