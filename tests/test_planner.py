"""Pruebas unitarias completas del AI Planner."""

from __future__ import annotations

import json

from core.planner import AIPlanner, ExecutionPlan, SubTask
from core.security import RiskLevel


def test_create_execution_plan_from_natural_language() -> None:
    planner = AIPlanner()
    goal = "Copiar archivo de informe a la carpeta de respaldos"
    context = {"current_file": "informe.docx"}

    plan = planner.create_plan(goal, context_snapshot=context)

    assert isinstance(plan, ExecutionPlan)
    assert plan.goal == goal
    assert len(plan.tasks) >= 2
    assert plan.plan_id is not None
    assert plan.total_risk == RiskLevel.SAFE
    assert "current_file" in plan.required_context


def test_risk_level_consolidation() -> None:
    t1 = SubTask(
        task_id="t1",
        description="Lectura preliminar",
        risk_level=RiskLevel.READ_ONLY,
    )
    t2 = SubTask(
        task_id="t2",
        description="Eliminación de archivo",
        risk_level=RiskLevel.DANGEROUS,
        dependencies=["t1"],
    )

    plan = ExecutionPlan(goal="Test riesgo", tasks=[t1, t2])
    assert plan.total_risk == RiskLevel.DANGEROUS


def test_validate_dependencies_valid_dag() -> None:
    t1 = SubTask(task_id="t1", description="Paso 1")
    t2 = SubTask(task_id="t2", description="Paso 2", dependencies=["t1"])
    t3 = SubTask(task_id="t3", description="Paso 3", dependencies=["t2"])

    plan = ExecutionPlan(goal="DAG Válido", tasks=[t1, t2, t3])
    assert plan.validate_dependencies() is True


def test_validate_dependencies_detects_cycle() -> None:
    # Dependencia circular: t1 -> t2 -> t1
    t1 = SubTask(task_id="t1", description="Paso 1", dependencies=["t2"])
    t2 = SubTask(task_id="t2", description="Paso 2", dependencies=["t1"])

    plan = ExecutionPlan(goal="Ciclo Inválido", tasks=[t1, t2])
    assert plan.validate_dependencies() is False


def test_json_serialization() -> None:
    planner = AIPlanner()
    plan = planner.create_plan("Obtener salud del sistema Windows")

    json_str = plan.to_json()
    assert isinstance(json_str, str)

    parsed = json.loads(json_str)
    assert parsed["goal"] == "Obtener salud del sistema Windows"
    assert "tasks" in parsed
    assert len(parsed["tasks"]) > 0


def test_planner_does_not_execute_tools() -> None:
    planner = AIPlanner()
    plan = planner.create_plan("Eliminar directorio temporal")

    # El plan debe contener la subtarea de riesgo DANGEROUS pero NO haber ejecutado ninguna acción
    assert plan.total_risk == RiskLevel.DANGEROUS
    # Verificar que el plan es puramente una estructura de datos inerte
    assert hasattr(plan, "tasks")
    assert not hasattr(plan, "execute")
