"""Pruebas unitarias completas del Task Executor y Motor de Rollback."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from core.capability import CapabilityManager, ToolCapabilitySpec
from core.event_bus import EventBus
from core.exceptions import ValidationError
from core.executor import PlanExecutionResult, TaskExecutor
from core.planner import AIPlanner, ExecutionPlan, SubTask
from core.security import SecurityManager
from core.types import JSONDict
from tools.base_tool import BaseMCPTool


class DummySuccessTool(BaseMCPTool):
    def __init__(self, name: str = "dummy_success", capability: str = "System", action: str = "health") -> None:
        super().__init__(name=name, description="Herramienta exitosa", capability=capability, action=action)

    def _get_input_schema(self) -> JSONDict:
        return {"type": "object", "properties": {}}

    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        return {"status": "ok", "executed": self.name}


class DummyFailingTool(BaseMCPTool):
    def __init__(self, name: str = "dummy_failing", capability: str = "Filesystem", action: str = "delete") -> None:
        super().__init__(name=name, description="Herramienta defectuosa", capability=capability, action=action)

    def _get_input_schema(self) -> JSONDict:
        return {"type": "object", "properties": {}}

    async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
        raise RuntimeError("Fallo intencional durante la ejecución de la herramienta")


def test_executor_rejects_non_plan_input() -> None:
    executor = TaskExecutor()

    # Debe lanzar ValidationError si recibe un string o un objeto diferente a ExecutionPlan
    with pytest.raises(ValidationError):
        asyncio.run(executor.execute_plan("Copiar archivo"))  # type: ignore[arg-type]


def test_executor_executes_valid_plan_successfully() -> None:
    async def _run() -> None:
        cap_mgr = CapabilityManager()
        tool = DummySuccessTool()
        cap_mgr.register_tool_capability(tool, ToolCapabilitySpec("System", "health"))

        planner = AIPlanner()
        plan = planner.create_plan("Obtener salud del sistema")

        executor = TaskExecutor(capability_manager=cap_mgr)
        res = await executor.execute_plan(plan)

        assert isinstance(res, PlanExecutionResult)
        assert res.is_success is True
        assert res.status == "COMPLETED"
        assert res.progress_percent == 100.0
        assert len(res.completed_tasks) >= 1

    asyncio.run(_run())


def test_executor_event_bus_progress_notifications() -> None:
    async def _run() -> None:
        bus = EventBus()
        events_received = []

        def listener(evt: Any) -> None:
            events_received.append(evt.name)

        bus.subscribe("*", listener)

        cap_mgr = CapabilityManager()
        tool = DummySuccessTool()
        cap_mgr.register_tool_capability(tool, ToolCapabilitySpec("System", "health"))

        planner = AIPlanner()
        plan = planner.create_plan("Obtener salud del sistema")

        executor = TaskExecutor(capability_manager=cap_mgr, event_bus=bus)
        await executor.execute_plan(plan)

        assert "plan:started" in events_received
        assert "task:progress" in events_received
        assert "task:completed" in events_received
        assert "plan:completed" in events_received

    asyncio.run(_run())


def test_executor_rollback_on_task_failure() -> None:
    async def _run() -> None:
        cap_mgr = CapabilityManager()
        t1 = DummySuccessTool("step1_tool", capability="Filesystem", action="read")
        t2 = DummyFailingTool("step2_tool", capability="Filesystem", action="delete")

        cap_mgr.register_tool_capability(t1, ToolCapabilitySpec("Filesystem", "read"))
        cap_mgr.register_tool_capability(t2, ToolCapabilitySpec("Filesystem", "delete"))

        # Crear plan manual con 2 subtareas: t1 exitosa, t2 falla
        sub1 = SubTask(task_id="t1", description="Leer origen", capability_required="Filesystem", action_required="read", execution_order=1)
        sub2 = SubTask(task_id="t2", description="Eliminar elemento", capability_required="Filesystem", action_required="delete", dependencies=["t1"], execution_order=2)

        plan = ExecutionPlan(goal="Prueba Rollback", tasks=[sub1, sub2])

        executor = TaskExecutor(capability_manager=cap_mgr)
        res = await executor.execute_plan(plan)

        assert res.is_success is False
        assert res.status == "ROLLED_BACK"
        assert res.failed_task_id == "t2"
        assert res.rollback_executed is True

    asyncio.run(_run())


def test_executor_security_blocking() -> None:
    async def _run() -> None:
        cap_mgr = CapabilityManager()
        tool = DummySuccessTool("sec_tool", capability="System", action="health")
        cap_mgr.register_tool_capability(tool, ToolCapabilitySpec("System", "health"))

        sec_mgr = SecurityManager()
        # Bloquear la herramienta en la Lista Negra
        sec_mgr.add_to_blacklist("sec_tool")

        planner = AIPlanner()
        plan = planner.create_plan("Obtener salud del sistema")

        executor = TaskExecutor(capability_manager=cap_mgr, security_manager=sec_mgr)
        res = await executor.execute_plan(plan)

        assert res.is_success is False
        assert "bloqueada por seguridad" in res.error_message.lower()

    asyncio.run(_run())
