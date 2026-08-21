"""Suite de pruebas unitarias e integrales para Skill Manager & Runtime (Fase 28.4).

Verifica:
1. Ejecución gobernada normal con retorno COMPLETED
2. Timeout estricto de ejecución
3. Cancelación interactiva mediante CancellationToken
4. Captura y aislamiento de fallos/excepciones internas
5. Control de presupuesto (AgentBudget) y techo de riesgo
6. Parada de Emergencia prevalente (EmergencyStopManager)
7. Ejecución concurrente thread-safe de múltiples Skills
8. Ciclo de vida completo (load, activate, deactivate, unload)
"""

import concurrent.futures
import time
from typing import Any

from core.autonomy.autonomy_level import TaskActionRisk
from core.cancellation import CancellationToken
from core.control_plane.models import AgentBudget
from core.emergency_stop import EmergencyStopManager
from core.security_architecture import SecurityLevel
from skills import (
    BaseSkill,
    SkillDefinition,
    SkillManager,
    SkillManifest,
    SkillRegistry,
    SkillResult,
    SkillRouter,
    SkillRuntime,
    SkillStatus,
)


class DummyWorkingSkill(BaseSkill):
    """Skill de prueba con comportamiento configurable (demoras, errores, etc.)."""

    def __init__(
        self,
        skill_id: str = "dummy.worker",
        delay_seconds: float = 0.0,
        should_fail: bool = False,
        risk_level: SecurityLevel = SecurityLevel.SAFE,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.should_fail = should_fail
        manifest = SkillManifest(
            id=skill_id,
            name=f"Worker {skill_id}",
            version="1.0.0",
            description="Worker skill de prueba.",
            capabilities=("system_info",),
            required_tools=(),
            risk_level=risk_level,
        )
        def_obj = SkillDefinition(
            skill_id=skill_id,
            name=f"Worker {skill_id}",
            version="1.0.0",
            description="Worker skill de prueba.",
            capabilities=("system_info",),
            required_tools=(),
            risk_level=risk_level,
            manifest=manifest,
        )
        super().__init__(nombre=skill_id, nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)
        if self.should_fail:
            raise RuntimeError("Error simulado en dummy worker")
        return {"exito": True, "resultado": f"Procesado con params: {parametros}"}


class TestSkillManagerRuntime:
    """Suite de pruebas para el ciclo de vida y runtime de Skills."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_manager_runtime_setup")
        self.registry = SkillRegistry()
        self.registry.reset()
        self.router = SkillRouter(registry=self.registry)
        self.runtime = SkillRuntime(emergency_stop=self.emergency_stop)
        self.manager = SkillManager(
            registry=self.registry,
            router=self.router,
            runtime=self.runtime,
        )

    # ── 1. EJECUCIÓN EXITOSA ──

    def test_successful_skill_execution(self) -> None:
        """Verifica la ejecución gobernada exitosa que retorna SkillStatus.COMPLETED."""
        skill = DummyWorkingSkill(skill_id="test.worker")
        self.manager.load_skill(skill)

        res: SkillResult = self.manager.execute_skill(
            skill_id="test.worker",
            parameters={"query": "hello"},
        )

        assert res.success is True
        assert res.status == SkillStatus.COMPLETED
        assert res.output == {"exito": True, "resultado": "Procesado con params: {'query': 'hello'}"}
        assert res.error is None

    # ── 2. CONTROL DE TIMEOUT ──

    def test_skill_timeout_handling(self) -> None:
        """Verifica que una skill que exceda timeout_seconds sea interrumpida con FAILED/TIMEOUT."""
        slow_skill = DummyWorkingSkill(skill_id="slow.worker", delay_seconds=1.0)
        self.manager.load_skill(slow_skill)

        res: SkillResult = self.manager.execute_skill(
            skill_id="slow.worker",
            timeout_seconds=0.1,  # Timeout menor a delay_seconds
        )

        assert res.success is False
        assert res.status == SkillStatus.FAILED
        assert "Timeout de ejecución" in str(res.error)
        assert res.security_decision == "TIMEOUT"

    # ── 3. CANCELACIÓN POR TOKEN ──

    def test_skill_cancellation(self) -> None:
        """Verifica que un token de cancelación activo retorne SkillStatus.CANCELLED."""
        skill = DummyWorkingSkill(skill_id="cancellable.worker")
        self.manager.load_skill(skill)

        token = CancellationToken()
        token.cancel()  # Token previamente cancelado

        res: SkillResult = self.manager.execute_skill(
            skill_id="cancellable.worker",
            cancellation_token=token,
        )

        assert res.success is False
        assert res.status == SkillStatus.CANCELLED
        assert "cancelada por token" in str(res.error).lower()
        assert res.security_decision == "CANCELLED"

    # ── 4. CAPTURA Y AISLAMIENTO DE FALLOS ──

    def test_skill_internal_failure_handling(self) -> None:
        """Verifica que excepciones no controladas dentro de la skill sean capturadas sin tumbar el sistema."""
        failing_skill = DummyWorkingSkill(skill_id="failing.worker", should_fail=True)
        self.manager.load_skill(failing_skill)

        res: SkillResult = self.manager.execute_skill(skill_id="failing.worker")

        assert res.success is False
        assert res.status == SkillStatus.FAILED
        assert "Error simulado" in str(res.error)

    # ── 5. CONTROL DE PRESUPUESTO (AGENT BUDGET) ──

    def test_skill_budget_risk_ceiling_exceeded(self) -> None:
        """Verifica que una Skill cuyo riesgo supera el techo de presupuesto sea rechazada."""
        dangerous_skill = DummyWorkingSkill(
            skill_id="dangerous.worker",
            risk_level=SecurityLevel.DANGEROUS,
        )
        self.manager.load_skill(dangerous_skill)

        # Presupuesto con techo LOW_RISK
        budget = AgentBudget(
            risk_ceiling=TaskActionRisk.LOW_RISK,
        )

        res: SkillResult = self.manager.execute_skill(
            skill_id="dangerous.worker",
            budget=budget,
        )

        assert res.success is False
        assert res.status == SkillStatus.FAILED
        assert "supera el techo de riesgo" in str(res.error)
        assert res.security_decision == "BUDGET_RISK_CEILING_EXCEEDED"

    # ── 6. PARADA DE EMERGENCIA PREVALENTE ──

    def test_emergency_stop_halts_skill_execution(self) -> None:
        """Verifica que la activación de Emergency Stop impida inmediatamente la ejecución."""
        skill = DummyWorkingSkill(skill_id="emergency.worker")
        self.manager.load_skill(skill)

        self.emergency_stop.trigger_stop(
            reason="Prueba de parada de emergencia en SkillRuntime",
            source="test_emergency_stop",
        )

        res: SkillResult = self.manager.execute_skill(skill_id="emergency.worker")

        assert res.success is False
        assert res.status in (SkillStatus.CANCELLED, SkillStatus.FAILED)
        assert "Parada de Emergencia activa" in str(res.error)
        assert res.security_decision == "EMERGENCY_STOP"

    # ── 7. EJECUCIÓN CONCURRENTE THREAD-SAFE ──

    def test_concurrent_skill_executions(self) -> None:
        """Verifica la ejecución en paralelo de múltiples skills de forma aislada."""
        skill1 = DummyWorkingSkill(skill_id="worker.alpha", delay_seconds=0.05)
        skill2 = DummyWorkingSkill(skill_id="worker.beta", delay_seconds=0.05)
        self.manager.load_skill(skill1)
        self.manager.load_skill(skill2)

        def run_worker(s_id: str, param: str) -> SkillResult:
            return self.manager.execute_skill(skill_id=s_id, parameters={"id": param})

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(run_worker, "worker.alpha", f"alpha_{i}")
                for i in range(5)
            ] + [
                pool.submit(run_worker, "worker.beta", f"beta_{i}")
                for i in range(5)
            ]
            results = [f.result() for f in futures]

        assert len(results) == 10
        assert all(r.success is True for r in results)
        assert all(r.status == SkillStatus.COMPLETED for r in results)

    # ── 8. CICLO DE VIDA COMPLETO (LOAD, ACTIVATE, DEACTIVATE, UNLOAD) ──

    def test_skill_lifecycle_management(self) -> None:
        """Verifica las transiciones del ciclo de vida administradas por SkillManager."""
        skill = DummyWorkingSkill(skill_id="lifecycle.worker")

        # 1. Load
        load_ok, _ = self.manager.load_skill(skill)
        assert load_ok is True
        assert self.manager.get_skill_status("lifecycle.worker") in (SkillStatus.READY, SkillStatus.ENABLED)

        # 2. Deactivate
        deact_ok = self.manager.deactivate_skill("lifecycle.worker")
        assert deact_ok is True
        assert self.manager.get_skill_status("lifecycle.worker") == SkillStatus.DISABLED

        # Intento de ejecución desactivada debe fallar
        res_dis = self.manager.execute_skill("lifecycle.worker")
        assert res_dis.success is False
        assert res_dis.security_decision == "SKILL_DISABLED"

        # 3. Activate
        act_ok = self.manager.activate_skill("lifecycle.worker")
        assert act_ok is True
        assert self.manager.get_skill_status("lifecycle.worker") == SkillStatus.ENABLED

        # Ejecución ahora debe tener éxito
        res_act = self.manager.execute_skill("lifecycle.worker")
        assert res_act.success is True

        # 4. Unload
        unload_ok = self.manager.unload_skill("lifecycle.worker")
        assert unload_ok is True
        assert self.manager.get_skill_status("lifecycle.worker") == SkillStatus.UNVALIDATED
