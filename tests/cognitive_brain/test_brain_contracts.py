"""Pruebas unitarias para los contratos e interfaces de JESSYCA BRAIN 1.0 (Fase 1)."""

from __future__ import annotations

import pytest

from core.cognitive_brain.contracts import (
    CanonicalPlan,
    CanonicalPlanStep,
    ContextBundle,
    ExecutionAdapter,
    GoalComprehension,
    LearnedProcedure,
    MemoryProvider,
    PlanStepExecutionState,
    PlanningProvider,
    ProcedureLifecycleState,
    ProcedureRepository,
    ReasoningProvider,
    RiskPolicy,
    TaskJournal,
    ToolRegistry,
    VerificationProvider,
)


def test_contracts_runtime_checkable():
    """Verifica que todos los protocolos principales sean runtime_checkable."""
    protocols = [
        ReasoningProvider,
        PlanningProvider,
        MemoryProvider,
        ProcedureRepository,
        ToolRegistry,
        ExecutionAdapter,
        VerificationProvider,
        RiskPolicy,
        TaskJournal,
    ]
    for proto in protocols:
        assert isinstance(proto, type)


def test_goal_comprehension_model():
    """Verifica la instanciación inmutable de GoalComprehension."""
    comp = GoalComprehension(
        raw_query="abre bloc de notas y escribe hola",
        normalized_goal="abrir bloc de notas y escribir texto",
        intent_category="application_control",
        confidence=0.95,
        entities={"app_name": "notepad", "text": "hola"},
        is_ambiguous=False,
        suggested_tools=("windows.apps",),
    )
    assert comp.intent_category == "application_control"
    assert comp.confidence == 0.95
    assert comp.entities["app_name"] == "notepad"


def test_canonical_plan_and_steps():
    """Verifica la creación y estructuración de un CanonicalPlan."""
    step1 = CanonicalPlanStep(
        step_id="step_1",
        action_name="open_app",
        tool_name="windows.apps",
        parameters={"accion": "abrir", "nombre": "notepad"},
        description="Abrir Bloc de notas",
    )
    step2 = CanonicalPlanStep(
        step_id="step_2",
        action_name="type_text",
        tool_name="windows.apps",
        parameters={"accion": "escribir", "texto": "hola"},
        description="Escribir texto en Bloc de notas",
        dependencies=["step_1"],
    )
    plan = CanonicalPlan(
        goal="abrir bloc de notas y escribir hola",
        steps=[step1, step2],
    )
    assert len(plan.steps) == 2
    assert plan.steps[1].dependencies == ["step_1"]
    assert plan.steps[0].state == PlanStepExecutionState.PENDING


def test_learned_procedure_lifecycle():
    """Verifica el ciclo de vida y transición de un LearnedProcedure."""
    proc = LearnedProcedure(
        procedure_id="proc-001",
        name="abrir_bloc_y_escribir",
        description="Abre Notepad y escribe contenido",
        associated_intent="open_application",
        steps=[{"tool": "windows.apps", "action": "open"}],
        state=ProcedureLifecycleState.CANDIDATE,
    )
    assert proc.state == ProcedureLifecycleState.CANDIDATE
    proc.state = ProcedureLifecycleState.TESTING
    assert proc.state == ProcedureLifecycleState.TESTING
    proc.state = ProcedureLifecycleState.VALIDATED
    assert proc.state == ProcedureLifecycleState.VALIDATED
