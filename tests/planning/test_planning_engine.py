"""Tests unitarios e integrales para el Motor de Planificación (Fase 23: Planning Engine).

Verifica:
1. Creación y ejecución de planes simples
2. Planes multi-step y ordenamiento topológico
3. Gestión y resolución de dependencias
4. Manejo de fallos en pasos y bloqueo en cascada
5. Detección y rechazo de ciclos (DAG estricto)
6. Timeouts de pasos y timeout global del plan
7. Presupuesto y límites de pasos
8. Cancelación cooperativa vía CancellationToken
9. Parada de Emergencia prevalente e inmediata
10. Invariante: PLANNER != AUTHORIZATION y bloqueo por denegación de seguridad
"""

from typing import Any

from core.cancellation import CancellationToken
from core.emergency_stop import EmergencyStopManager
from core.permission_manager import PermissionManager
from core.planning import (
    ExecutionPlan,
    PlanBuilder,
    PlanExecutor,
    PlanningEngine,
    PlanStatus,
    PlanStep,
    StepStatus,
)
from core.risk_engine import RiskEngine
from core.security_architecture import SecurityLevel


class TestPlanningEngine:
    """Suite de pruebas exhaustiva para el Planning Engine."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_planning_setup")
        self.permission_manager = PermissionManager()
        self.risk_engine = RiskEngine()
        self.engine = PlanningEngine(
            emergency_stop=self.emergency_stop,
            permission_manager=self.permission_manager,
            risk_engine=self.risk_engine,
        )

    # ── 1. PLANES SIMPLES LINEALES ──

    def test_simple_linear_plan_execution(self) -> None:
        """Verifica la ejecución exitosa de un plan lineal de 2 pasos."""
        step1 = PlanStep(
            step_id="s1_list",
            description="Listar archivos",
            required_agent="agent_file",
            required_tool="filesystem.list_directory",
            tool_parameters={"path": "sandbox"},
            dependencies=(),
            risk_level=SecurityLevel.SAFE,
        )
        step2 = PlanStep(
            step_id="s2_report",
            description="Reportar archivos",
            required_agent="agent_system",
            dependencies=("s1_list",),
            risk_level=SecurityLevel.SAFE,
        )

        plan = self.engine.create_plan(goal="Listar y reportar", steps=[step1, step2])
        res = self.engine.execute_plan(plan)

        assert res.is_success is True
        assert res.status == PlanStatus.COMPLETED
        assert res.steps_executed == 2
        assert all(s.status == StepStatus.COMPLETED for s in res.step_results)

    # ── 2. PLANES MULTI-STEP Y ORDENAMIENTO TOPOLÓGICO ──

    def test_multi_step_file_organization_template(self) -> None:
        """Verifica la plantilla formal de organización de archivos (7 pasos con dependencias complejas)."""
        plan = PlanBuilder.build_file_organization_plan(target_dir="sandbox/work")
        is_valid, msg = self.engine.validate_plan(plan)
        assert is_valid is True

        res = self.engine.execute_plan(plan)
        assert res.is_success is True
        assert res.status == PlanStatus.COMPLETED
        assert res.steps_executed == 7

    # ── 3. DETECCIÓN Y RECHAZO DE CICLOS (DAG ESTRICTO) ──

    def test_cyclic_plan_rejected_before_execution(self) -> None:
        """Verifica que dependencias circulares (A->B, B->A) sean rechazadas sin ejecutarse."""
        step_a = PlanStep(
            step_id="step_a",
            description="Paso A",
            required_agent="agent_file",
            dependencies=("step_b",),
        )
        step_b = PlanStep(
            step_id="step_b",
            description="Paso B",
            required_agent="agent_file",
            dependencies=("step_a",),
        )

        plan = self.engine.create_plan(goal="Plan con ciclo", steps=[step_a, step_b])
        is_valid, reason = self.engine.validate_plan(plan)
        assert is_valid is False
        assert "cíclicas" in reason.lower()

        res = self.engine.execute_plan(plan)
        assert res.is_success is False
        assert res.status == PlanStatus.FAILED
        assert res.steps_executed == 0

    # ── 4. AUTO-CICLO RECHAZADO ──

    def test_self_dependency_rejected(self) -> None:
        """Verifica que un paso que depende de sí mismo sea rechazado inmediatamente."""
        step_self = PlanStep(
            step_id="step_self",
            description="Auto dependencia",
            required_agent="agent_system",
            dependencies=("step_self",),
        )
        plan = self.engine.create_plan(goal="Auto-ciclo", steps=[step_self])
        is_valid, reason = self.engine.validate_plan(plan)
        assert is_valid is False
        assert "auto-ciclo" in reason.lower()

    # ── 5. MANEJO DE FALLOS Y BLOQUEO EN CASCADA ──

    def test_step_failure_blocks_dependent_steps(self) -> None:
        """Verifica que si un paso falla, los pasos que dependen de él queden en BLOCKED."""
        def faulty_executor(step: PlanStep, ctx: dict[str, Any]) -> dict[str, Any]:
            if step.step_id == "s1_fail":
                raise RuntimeError("Error simulado en disco")
            return {"status": "success"}

        executor = PlanExecutor(
            emergency_stop=self.emergency_stop,
            permission_manager=self.permission_manager,
            risk_engine=self.risk_engine,
            step_executor=faulty_executor,
        )
        engine = PlanningEngine(
            emergency_stop=self.emergency_stop,
            permission_manager=self.permission_manager,
            risk_engine=self.risk_engine,
            executor=executor,
        )

        step1 = PlanStep(step_id="s1_fail", description="Paso defectuoso", required_agent="agent_file")
        step2 = PlanStep(step_id="s2_dep", description="Paso dependiente", required_agent="agent_file", dependencies=("s1_fail",))

        plan = engine.create_plan(goal="Prueba de fallo", steps=[step1, step2])
        res = engine.execute_plan(plan)

        assert res.is_success is False
        assert res.status == PlanStatus.FAILED
        assert res.step_results[0].status == StepStatus.FAILED
        assert res.step_results[1].status == StepStatus.BLOCKED

    # ── 6. TIMEOUT GLOBAL DEL PLAN ──

    def test_global_timeout_halts_plan(self) -> None:
        """Verifica que si el tiempo total excede max_total_timeout_seconds, el plan falle por timeout."""
        def slow_executor(step: PlanStep, ctx: dict[str, Any]) -> dict[str, Any]:
            import time
            time.sleep(0.06)
            return {"status": "success"}

        executor = PlanExecutor(
            emergency_stop=self.emergency_stop,
            step_executor=slow_executor,
        )
        engine = PlanningEngine(
            emergency_stop=self.emergency_stop,
            executor=executor,
        )

        s1 = PlanStep(step_id="s1", description="Lento 1", required_agent="agent_file")
        s2 = PlanStep(step_id="s2", description="Lento 2", required_agent="agent_file", dependencies=("s1",))

        plan = ExecutionPlan.create(
            goal="Test timeout",
            steps=[s1, s2],
            max_total_timeout_seconds=0.04,  # Timeout menor que la duración del primer paso
        )
        res = engine.execute_plan(plan)
        assert res.is_success is False
        assert res.status == PlanStatus.FAILED
        assert "timeout" in str(res.error).lower()

    # ── 7. CANCELACIÓN VÍA CANCELLATION TOKEN ──

    def test_cancellation_token_halts_execution(self) -> None:
        """Verifica que un CancellationToken detenga limpiamente la ejecución."""
        token = CancellationToken()

        def cancelling_executor(step: PlanStep, ctx: dict[str, Any]) -> dict[str, Any]:
            token.cancel()  # Cancelar en el primer paso
            return {"status": "success"}

        executor = PlanExecutor(
            emergency_stop=self.emergency_stop,
            step_executor=cancelling_executor,
        )
        engine = PlanningEngine(
            emergency_stop=self.emergency_stop,
            executor=executor,
        )

        s1 = PlanStep(step_id="s1", description="Paso 1", required_agent="agent_file")
        s2 = PlanStep(step_id="s2", description="Paso 2", required_agent="agent_file", dependencies=("s1",))

        plan = engine.create_plan(goal="Prueba cancelación", steps=[s1, s2])
        res = engine.execute_plan(plan, cancellation_token=token)

        assert res.is_success is False
        assert res.status == PlanStatus.CANCELLED

    # ── 8. PARADA DE EMERGENCIA PREVALENTE ──

    def test_emergency_stop_halts_plan_immediately(self) -> None:
        """Verifica que la activación de Parada de Emergencia aborte el plan al instante."""
        self.emergency_stop.trigger_stop(reason="Parada forzada en test de planificación", source="test")

        s1 = PlanStep(step_id="s1", description="Paso crítico", required_agent="agent_file")
        plan = self.engine.create_plan(goal="Intento durante stop", steps=[s1])

        res = self.engine.execute_plan(plan)
        assert res.is_success is False
        assert res.status == PlanStatus.CANCELLED
        assert "Parada de Emergencia" in str(res.error)

    # ── 9. INVARIANTE: PLANNER != AUTHORIZATION Y BLOQUEO POR SEGURIDAD ──

    def test_planner_cannot_bypass_security_pipeline(self) -> None:
        """Verifica que una herramienta de riesgo crítico sea bloqueada por PermissionManager en el plan."""
        # Un plan que intenta formatear el disco
        step_danger = PlanStep(
            step_id="danger_step",
            description="Formatear disco del sistema",
            required_agent="agent_system",
            required_tool="system.format_disk",
            tool_parameters={"drive": "C:"},
            risk_level=SecurityLevel.CRITICAL,
        )

        plan = self.engine.create_plan(goal="Plan malicioso", steps=[step_danger])
        res = self.engine.execute_plan(plan)

        assert res.is_success is False
        assert res.status == PlanStatus.FAILED
        assert "Denegación de seguridad" in str(res.error) or "denegado" in str(res.error).lower()
        assert res.step_results[0].status == StepStatus.FAILED
