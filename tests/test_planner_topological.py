"""Suite de pruebas para el Ordenamiento Topológico y Resolución de Dependencias en el AI Planner (Prompt 05).

Valida:
1. Reproducción: Tarea dependiente con execution_order=1 y prerrequisito con execution_order=2
   (el prerrequisito se ejecuta primero).
2. Cadena lineal de dependencias (t1 -> t2 -> t3 -> t4).
3. Grafo en diamante (A -> B, A -> C, (B, C) -> D con desempate por execution_order).
4. Tareas independientes (desempate determinista por execution_order y task_id).
5. Plan vacío (DAG trivial válido que retorna lista vacía).
6. Referencias desconocidas o inexistentes (rechazadas con MissingDependencyError).
7. Detección estricta de ciclos circulares (rechazados con CircularDependencyError).
8. Autodependencias (rechazadas con SelfDependencyError).
9. Identificadores de subtarea duplicados (rechazados con DuplicateNodeError).
10. Estabilidad y determinismo garantizado ante llamadas repetidas.
11. Serialización del plan (to_dict, to_json) preservando el orden topológico.
12. Consumidor real TaskExecutor ejecutando en el orden topológico resuelto.
13. AIPlanner.create_plan rechaza planes defectuosos con InvalidPlanError sin entregarlos como ejecutables.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from core.capability import CapabilityManager, ToolCapabilitySpec
from core.dag import (
    CircularDependencyError,
    DAGError,
    DuplicateNodeError,
    InvalidPlanError,
    MissingDependencyError,
    SelfDependencyError,
    topological_sort,
)
from core.executor import TaskExecutor
from core.planner import AIPlanner, ExecutionPlan, SubTask
from core.security import RiskLevel
from core.types import JSONDict
from tools.base_tool import BaseMCPTool


# ── TEST 1: REPRODUCCIÓN DEL HALLAZGO ──
def test_01_reproduction_dependent_order1_prerequisite_order2() -> None:
    """Una tarea dependent (order=1) depende de prerequisite (order=2).

    El orden topológico DEBE anteponer prerequisite a dependent.
    """
    prereq = SubTask(
        task_id="prerequisite",
        description="Paso previo obligatorio",
        execution_order=2,
        dependencies=[],
    )
    dep = SubTask(
        task_id="dependent",
        description="Paso dependiente",
        execution_order=1,
        dependencies=["prerequisite"],
    )

    plan = ExecutionPlan(goal="Reproducción", tasks=[dep, prereq])

    # validate_dependencies() debe ser True porque el grafo es válido
    assert plan.validate_dependencies() is True

    # get_ordered_tasks() debe retornar prerequisite ANTES que dependent
    ordered = plan.get_ordered_tasks()
    ordered_ids = [t.task_id for t in ordered]
    assert ordered_ids == ["prerequisite", "dependent"], (
        f"Se esperaba ['prerequisite', 'dependent'] pero se obtuvo {ordered_ids}"
    )


# ── TEST 2: CADENA LINEAL ──
def test_02_linear_chain_dependencies() -> None:
    """Cadena simple t1 -> t2 -> t3 -> t4 entregada en desorden."""
    t1 = SubTask(task_id="t1", description="1", dependencies=[])
    t2 = SubTask(task_id="t2", description="2", dependencies=["t1"])
    t3 = SubTask(task_id="t3", description="3", dependencies=["t2"])
    t4 = SubTask(task_id="t4", description="4", dependencies=["t3"])

    # Entregamos en orden arbitrario inverso
    plan = ExecutionPlan(goal="Cadena", tasks=[t4, t2, t1, t3])
    assert plan.validate_dependencies() is True

    ordered = [t.task_id for t in plan.get_ordered_tasks()]
    assert ordered == ["t1", "t2", "t3", "t4"]


# ── TEST 3: GRAFO EN DIAMANTE ──
def test_03_diamond_graph_with_tie_breaker() -> None:
    """Grafo en diamante:
         A (order 1)
        / \
    B(2)   C(1)
        \ /
         D (order 1)
    Orden esperado: A -> C (order 1 < 2) -> B -> D.
    """
    a = SubTask(task_id="A", description="Inicio", execution_order=1, dependencies=[])
    b = SubTask(task_id="B", description="Rama B", execution_order=2, dependencies=["A"])
    c = SubTask(task_id="C", description="Rama C", execution_order=1, dependencies=["A"])
    d = SubTask(task_id="D", description="Confluencia", execution_order=1, dependencies=["B", "C"])

    plan = ExecutionPlan(goal="Diamante", tasks=[d, b, c, a])
    assert plan.validate_dependencies() is True

    ordered = [t.task_id for t in plan.get_ordered_tasks()]
    assert ordered == ["A", "C", "B", "D"]


# ── TEST 4: TAREAS INDEPENDIENTES Y DESEMPATE DETERMINISTA ──
def test_04_independent_tasks_tie_breaking() -> None:
    """Tareas independientes sin dependencias se ordenan por execution_order y luego por task_id."""
    t_mid = SubTask(task_id="t_mid", description="M", execution_order=2)
    t_low = SubTask(task_id="t_low", description="L", execution_order=1)
    t_high = SubTask(task_id="t_high", description="H", execution_order=3)

    plan = ExecutionPlan(goal="Independientes", tasks=[t_high, t_mid, t_low])
    ordered = [t.task_id for t in plan.get_ordered_tasks()]
    assert ordered == ["t_low", "t_mid", "t_high"]

    # Mismo execution_order desempatado alfabéticamente por task_id
    t_b = SubTask(task_id="task_b", description="B", execution_order=1)
    t_a = SubTask(task_id="task_a", description="A", execution_order=1)
    plan2 = ExecutionPlan(goal="Empate ID", tasks=[t_b, t_a])
    assert [t.task_id for t in plan2.get_ordered_tasks()] == ["task_a", "task_b"]


# ── TEST 5: PLAN VACÍO ──
def test_05_empty_plan_handling() -> None:
    """Un plan sin tareas es un DAG trivial válido."""
    plan = ExecutionPlan(goal="Vacío", tasks=[])
    assert plan.validate_dependencies() is True
    assert plan.get_ordered_tasks() == []
    assert plan.to_dict()["tasks"] == []


# ── TEST 6: REFERENCIAS DESCONOCIDAS O INEXISTENTES ──
def test_06_unknown_dependency_rejected() -> None:
    """Una tarea que depende de un ID inexistente debe ser rechazada."""
    t1 = SubTask(task_id="t1", description="1", dependencies=["inexistente_999"])
    plan = ExecutionPlan(goal="Inexistente", tasks=[t1])

    assert plan.validate_dependencies() is False

    with pytest.raises(MissingDependencyError) as exc_info:
        plan.get_ordered_tasks()
    assert "inexistente_999" in str(exc_info.value)

    with pytest.raises(MissingDependencyError):
        plan.validate_dependencies(raise_on_error=True)


# ── TEST 7: DETECCIÓN DE CICLOS CIRCULARES ──
def test_07_cycle_detection_rejected() -> None:
    """Un ciclo circular A -> B -> C -> A debe ser rechazado."""
    a = SubTask(task_id="A", description="A", dependencies=["C"])
    b = SubTask(task_id="B", description="B", dependencies=["A"])
    c = SubTask(task_id="C", description="C", dependencies=["B"])

    plan = ExecutionPlan(goal="Ciclo", tasks=[a, b, c])
    assert plan.validate_dependencies() is False

    with pytest.raises(CircularDependencyError) as exc_info:
        plan.get_ordered_tasks()
    assert "ciclo detectado" in str(exc_info.value)

    with pytest.raises(CircularDependencyError):
        plan.validate_dependencies(raise_on_error=True)


# ── TEST 8: AUTODEPENDENCIAS ──
def test_08_self_dependency_rejected() -> None:
    """Una tarea que depende de sí misma debe ser rechazada de inmediato."""
    self_loop = SubTask(task_id="loop", description="Autodependiente", dependencies=["loop"])
    plan = ExecutionPlan(goal="Autodependencia", tasks=[self_loop])

    assert plan.validate_dependencies() is False

    with pytest.raises(SelfDependencyError) as exc_info:
        plan.get_ordered_tasks()
    assert "depende de sí mismo" in str(exc_info.value)

    with pytest.raises(SelfDependencyError):
        plan.validate_dependencies(raise_on_error=True)


# ── TEST 9: IDENTIFICADORES REPETIDOS ──
def test_09_duplicate_task_ids_rejected() -> None:
    """Dos subtareas con el mismo task_id deben ser rechazadas."""
    t1a = SubTask(task_id="dup_id", description="Primera instancia")
    t1b = SubTask(task_id="dup_id", description="Segunda instancia duplicada")

    plan = ExecutionPlan(goal="Duplicado", tasks=[t1a, t1b])
    assert plan.validate_dependencies() is False

    with pytest.raises(DuplicateNodeError) as exc_info:
        plan.get_ordered_tasks()
    assert "duplicado" in str(exc_info.value)

    with pytest.raises(DuplicateNodeError):
        plan.validate_dependencies(raise_on_error=True)


# ── TEST 10: ORDEN ESTABLE ANTE LLAMADAS REPETIDAS ──
def test_10_deterministic_and_stable_order_repeated_calls() -> None:
    """100 llamadas consecutivas a get_ordered_tasks() deben arrojar exactamente la misma secuencia."""
    tasks = [
        SubTask(task_id="leaf_3", description="L3", execution_order=3, dependencies=["mid_1"]),
        SubTask(task_id="root", description="R", execution_order=5, dependencies=[]),
        SubTask(task_id="mid_1", description="M1", execution_order=2, dependencies=["root"]),
        SubTask(task_id="leaf_1", description="L1", execution_order=1, dependencies=["mid_1"]),
        SubTask(task_id="mid_2", description="M2", execution_order=1, dependencies=["root"]),
        SubTask(task_id="leaf_2", description="L2", execution_order=2, dependencies=["mid_2"]),
    ]
    plan = ExecutionPlan(goal="Estabilidad", tasks=tasks)

    baseline_order = [t.task_id for t in plan.get_ordered_tasks()]
    assert baseline_order[0] == "root"  # Root no tiene dependencias

    for _ in range(100):
        current_order = [t.task_id for t in plan.get_ordered_tasks()]
        assert current_order == baseline_order


# ── TEST 11: SERIALIZACIÓN PRESERVA ORDEN TOPOLÓGICO ──
def test_11_plan_serialization_preserves_topological_order() -> None:
    """to_dict() y to_json() serializan las subtareas en orden topológico estricto."""
    prereq = SubTask(task_id="prereq", description="Prereq", execution_order=2, dependencies=[])
    dep = SubTask(task_id="dep", description="Dep", execution_order=1, dependencies=["prereq"])

    plan = ExecutionPlan(goal="Serialización", tasks=[dep, prereq])

    # Serializar a dict
    plan_dict = plan.to_dict()
    assert plan_dict["tasks"][0]["task_id"] == "prereq"
    assert plan_dict["tasks"][1]["task_id"] == "dep"

    # Serializar a json
    plan_json = plan.to_json()
    parsed = json.loads(plan_json)
    assert parsed["tasks"][0]["task_id"] == "prereq"
    assert parsed["tasks"][1]["task_id"] == "dep"


# ── TEST 12: CONSUMIDOR REAL TASKEXECUTOR RESPETA DEPENDENCIAS ──
def test_12_consumer_task_executor_respects_dependencies() -> None:
    """Verifica que TaskExecutor ejecute las tareas en el orden devuelto por get_ordered_tasks."""
    execution_trail: list[str] = []

    class MockTrailTool(BaseMCPTool):
        def __init__(self, name: str, capability: str, action: str) -> None:
            super().__init__(name=name, description="Tool de rastro", capability=capability, action=action)

        def _get_input_schema(self) -> JSONDict:
            return {"type": "object", "properties": {}}

        async def _execute_internal(self, arguments: JSONDict) -> JSONDict:
            execution_trail.append(self.name)
            return {"status": "ok", "tool": self.name}

    async def _run() -> None:
        cap_mgr = CapabilityManager()
        tool1 = MockTrailTool(name="tool_prereq", capability="System", action="health")
        tool2 = MockTrailTool(name="tool_dep", capability="Filesystem", action="read")
        cap_mgr.register_tool_capability(tool1, ToolCapabilitySpec("System", "health"))
        cap_mgr.register_tool_capability(tool2, ToolCapabilitySpec("Filesystem", "read"))

        prereq = SubTask(
            task_id="t_prereq",
            description="Paso inicial",
            capability_required="System",
            action_required="health",
            execution_order=2,
            dependencies=[],
        )
        dep = SubTask(
            task_id="t_dep",
            description="Paso dependiente",
            capability_required="Filesystem",
            action_required="read",
            execution_order=1,
            dependencies=["t_prereq"],
        )

        plan = ExecutionPlan(goal="Test Ejecución", tasks=[dep, prereq])
        executor = TaskExecutor(capability_manager=cap_mgr)
        res = await executor.execute_plan(plan)

        assert res.is_success is True
        assert res.status == "COMPLETED"
        # La herramienta prerequisito DEBE haberse ejecutado antes que la dependiente
        assert execution_trail == ["tool_prereq", "tool_dep"]

    asyncio.run(_run())


# ── TEST 13: AIPLANNER NO ENTREGA PLAN INVÁLIDO ──
def test_13_ai_planner_create_plan_rejects_invalid_plan() -> None:
    """AIPlanner.create_plan lanza InvalidPlanError si las subtareas tienen dependencias defectuosas."""
    planner = AIPlanner()

    # Sobrescribimos el descompone interno para simular heurística con ciclo
    def broken_decompose(goal: str, context: dict) -> list[SubTask]:
        t1 = SubTask(task_id="step1", description="1", dependencies=["step2"])
        t2 = SubTask(task_id="step2", description="2", dependencies=["step1"])
        return [t1, t2]

    planner._decompose_goal_to_tasks = broken_decompose  # type: ignore[method-assign]

    with pytest.raises(InvalidPlanError) as exc_info:
        planner.create_plan("Cualquier meta")

    assert "plan inválido o no ejecutable" in str(exc_info.value)
