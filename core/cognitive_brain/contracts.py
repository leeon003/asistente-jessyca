"""JESSYCA BRAIN 1.0 — Contratos Fundacionales e Interfaces Estables.

Define los 9 contratos obligatorios para el Cerebro Cognitivo Unificado:
1. ReasoningProvider
2. PlanningProvider
3. MemoryProvider
4. ProcedureRepository
5. ToolRegistry
6. ExecutionAdapter
7. VerificationProvider
8. RiskPolicy
9. TaskJournal
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


# =========================================================================
# MODELOS DE DATOS COMPARTIDOS
# =========================================================================

class ProcedureLifecycleState(StrEnum):
    """Estados del ciclo de vida de un procedimiento aprendido."""
    CANDIDATE = "CANDIDATE"       # Propuesto a partir de observaciones, no validado
    TESTING = "TESTING"           # En fase de evaluación en entorno controlado
    VALIDATED = "VALIDATED"       # Aprobado para uso recurrente autorizado
    DEPRECATED = "DEPRECATED"     # Obsoleto tras cambios en el software o fallos repetidos


class PlanStepExecutionState(StrEnum):
    """Estado de ejecución de un paso de plan."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class GoalComprehension:
    """Comprensión estructurada del objetivo del usuario generada por ReasoningEngine."""
    raw_query: str
    normalized_goal: str
    intent_category: str
    confidence: float
    entities: dict[str, Any] = field(default_factory=dict)
    is_ambiguous: bool = False
    clarification_question: str | None = None
    suggested_tools: tuple[str, ...] = field(default_factory=tuple)
    context_references: dict[str, Any] = field(default_factory=dict)
    is_conversational: bool = False
    requires_action: bool = True
    sub_goals: tuple[str, ...] = field(default_factory=tuple)
    raw_explanation: str = ""

    @property
    def extracted_parameters(self) -> dict[str, Any]:
        return dict(self.entities)

    @property
    def user_goal(self) -> str:
        return self.normalized_goal or self.raw_query

    @property
    def candidate_tools(self) -> list[str]:
        return list(self.suggested_tools)

    @property
    def anaphora_resolved(self) -> dict[str, Any]:
        return self.context_references

    @property
    def clarification_needed(self) -> bool:
        return self.is_ambiguous or bool(self.clarification_question)


@dataclass
class CanonicalPlanStep:
    """Paso unitario dentro de un plan canónico de ejecución."""
    step_id: str
    action_name: str
    tool_name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    dependencies: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    expected_outcome: str = ""
    state: PlanStepExecutionState = PlanStepExecutionState.PENDING
    timeout_seconds: float = 30.0
    retry_limit: int = 1
    requires_approval: bool = False
    evidence: dict[str, Any] | None = None
    output: Any = None
    error: str | None = None


@dataclass
class CanonicalPlan:
    """Plan formal, acíclico y supervisado generado por PlannerEngine."""
    plan_id: str = field(default_factory=lambda: f"plan-{uuid.uuid4().hex[:12]}")
    goal: str = ""
    steps: list[CanonicalPlanStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    version: int = 1
    is_recovering: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LearnedProcedure:
    """Procedimiento automatizable persistido y gestionado por ProcedureLearningEngine."""
    procedure_id: str
    name: str
    description: str = ""
    associated_intent: str = ""
    required_applications: list[str] = field(default_factory=list)
    input_parameters: dict[str, Any] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    authorized_tools: list[str] = field(default_factory=list)
    success_conditions: list[str] = field(default_factory=list)
    error_conditions: list[str] = field(default_factory=list)
    validation_evidence: list[dict[str, Any]] = field(default_factory=list)
    version: int = 1
    state: ProcedureLifecycleState = ProcedureLifecycleState.CANDIDATE
    modification_history: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_validated_at: float | None = None
    approval_status: str = "PROPOSED"
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    # Campos ergonómicos y contadores de ejecución
    intent: str = ""
    expected_outcome: str = ""
    success_count: int = 0
    failure_count: int = 0

    def __post_init__(self) -> None:
        if self.intent and not self.associated_intent:
            self.associated_intent = self.intent
        elif self.associated_intent and not self.intent:
            self.intent = self.associated_intent
        if self.expected_outcome and not self.description:
            self.description = self.expected_outcome
        if self.expected_outcome and self.expected_outcome not in self.success_conditions:
            self.success_conditions.append(self.expected_outcome)
        if self.state == ProcedureLifecycleState.VALIDATED and self.approval_status == "PROPOSED":
            self.approval_status = "APPROVED"


@dataclass
class ContextBundle:
    """Paquete de contexto unificado seleccionado y condensado para el prompt."""
    working_context: dict[str, Any] = field(default_factory=dict)
    relevant_memories: list[dict[str, Any]] = field(default_factory=list)
    procedural_candidates: list[LearnedProcedure] = field(default_factory=list)
    untrusted_documents: list[str] = field(default_factory=list)
    episodic_examples: list[dict[str, Any]] = field(default_factory=list)

    @property
    def working_memory(self) -> dict[str, Any]:
        return self.working_context

    @property
    def semantic_facts(self) -> list[dict[str, Any]]:
        return self.relevant_memories


# =========================================================================
# PROTOCOLOS E INTERFACES DE CONTRATO (SOLID / DIP)
# =========================================================================

@runtime_checkable
class ReasoningProvider(Protocol):
    """Contrato del Motor de Razonamiento y Comprensión Contextual."""

    def comprehend(
        self,
        user_input: str,
        context: ContextBundle,
        session_id: str = "default",
    ) -> GoalComprehension:
        """Analiza la solicitud, resuelve anáforas y selecciona herramientas candidatas."""
        ...

    def evaluate_ambiguity(self, query: str) -> tuple[bool, str | None]:
        """Determina si la solicitud es ambigua y propone una pregunta aclaratoria."""
        ...


@runtime_checkable
class PlanningProvider(Protocol):
    """Contrato del Motor de Planificación Jerárquica y Replanificación."""

    def create_plan(
        self,
        comprehension: GoalComprehension,
        available_tools: list[str],
        constraints: dict[str, Any] | None = None,
    ) -> CanonicalPlan:
        """Formula un plan de ejecución estructurado y acíclico."""
        ...

    def replan(
        self,
        failed_step: CanonicalPlanStep,
        current_plan: CanonicalPlan,
        error_evidence: dict[str, Any],
    ) -> CanonicalPlan:
        """Genera un plan correctivo a partir de un paso fallido sin repetir lo ya completado."""
        ...

    def validate_dag(self, plan: CanonicalPlan) -> bool:
        """Verifica que el plan no contenga dependencias circulares ni referencias inexistentes."""
        ...


@runtime_checkable
class MemoryProvider(Protocol):
    """Contrato del Orquestador de Memoria en 4 Capas Lógicas."""

    def get_working_memory(self, session_id: str) -> dict[str, Any]:
        """Obtiene el contexto efímero de la tarea activa."""
        ...

    def update_working_memory(self, session_id: str, updates: dict[str, Any]) -> None:
        """Actualiza el contexto efímero de la tarea activa."""
        ...

    def record_episode(self, episode: dict[str, Any]) -> str:
        """Registra una experiencia verificada en la memoria episódica."""
        ...

    def store_semantic_fact(self, fact: str, category: str, confidence: float = 1.0) -> str:
        """Almacena conocimiento semántico o preferencias explícitas."""
        ...

    def retrieve_context(self, query: str, active_task_id: str | None = None) -> ContextBundle:
        """Selecciona y condensa el contexto relevante sin saturar el prompt."""
        ...


@runtime_checkable
class ProcedureRepository(Protocol):
    """Contrato del Almacén y Ciclo de Vida de Procedimientos Aprendidos."""

    def save_procedure(self, procedure: LearnedProcedure) -> bool:
        """Persiste o actualiza un procedimiento aprendido."""
        ...

    def find_matching(self, intent: str, app_context: str | None = None) -> list[LearnedProcedure]:
        """Busca procedimientos validados o en prueba compatibles con la meta."""
        ...

    def promote_state(
        self,
        procedure_id: str,
        new_state: ProcedureLifecycleState,
        reason: str,
    ) -> bool:
        """Avanza o retrocede el estado en el ciclo de vida del procedimiento."""
        ...


@runtime_checkable
class ToolRegistry(Protocol):
    """Contrato del Catálogo Progresivo y Resolución de Herramientas."""

    def get_available_tools(self, filter_intent: str | None = None) -> list[dict[str, Any]]:
        """Devuelve las herramientas disponibles aplicando Progressive Tool Loading."""
        ...

    def validate_tool_call(self, tool_name: str, parameters: dict[str, Any]) -> tuple[bool, str | None]:
        """Valida los parámetros de invocación contra el esquema tipado de la herramienta."""
        ...


@runtime_checkable
class ExecutionAdapter(Protocol):
    """Contrato de Ejecución Física Supervisada sobre Windows y CUA."""

    def execute_step(
        self,
        step: CanonicalPlanStep,
        session_id: str,
    ) -> dict[str, Any]:
        """Despacha la acción de escritorio o sistema asegurando mutex y coordenadas frescas."""
        ...

    def abort_execution(self, reason: str = "Interrupción del usuario") -> None:
        """Detiene de inmediato cualquier acción en curso activando parada de emergencia."""
        ...


@runtime_checkable
class VerificationProvider(Protocol):
    """Contrato de Verificación Empírica de Resultados (Anti-False Success)."""

    def verify_action(
        self,
        action_name: str,
        target: str,
        expected_outcome: str,
        execution_output: Any,
    ) -> tuple[bool, dict[str, Any]]:
        """Verifica mediante PIDs, ventanas o I/O en disco si el efecto deseado ocurrió realmente."""
        ...


@runtime_checkable
class RiskPolicy(Protocol):
    """Contrato de Gobernanza de Seguridad y Políticas de Acceso."""

    def evaluate_step_risk(self, step: CanonicalPlanStep, user_context: dict[str, Any]) -> str:
        """Determina el nivel de riesgo y veredicto ('ALLOW', 'DENY', 'REQUIRE_REVIEW')."""
        ...

    def is_protected_resource(self, resource_path: str) -> bool:
        """Determina si una ruta o archivo corresponde a recursos críticos del sistema."""
        ...


@runtime_checkable
class TaskJournal(Protocol):
    """Contrato del Diario Persistente de Tareas y Checkpoints de Reanudación."""

    def record_checkpoint(
        self,
        task_id: str,
        step_index: int,
        step_result: dict[str, Any],
        system_state: dict[str, Any],
    ) -> None:
        """Guarda un punto de control tras verificar empíricamente un paso del plan."""
        ...

    def load_active_task(self, task_id: str) -> dict[str, Any] | None:
        """Carga el estado de una tarea interrumpida para su recuperación tras reinicio."""
        ...

    def close_task(self, task_id: str, final_status: str, summary: str) -> None:
        """Cierra la tarea en el diario tras su finalización o cancelación definitiva."""
        ...
