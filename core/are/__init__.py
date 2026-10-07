"""Submódulo ARE (Action Reasoning Engine) gobernado para JESSYCA PC.

Exporta los contratos, el catálogo de acciones ejecutables, el validador perimétrico de planes,
la resolución de flujo de datos tipados y el coordinador de tiempo de ejecución para la
mediación segura de descomposición de planes (DAG), evaluación estructural y recuperación.
"""

from core.are.action_catalog import (
    ActionCatalog,
    ActionVerificationStrategy,
    ExecutableAction,
    get_default_action_catalog,
)
from core.are.dataflow import DataFlowResolver
from core.are.exceptions import (
    AREPlanError,
    MissingOutputDependencyError,
    PlanBudgetExceededError,
    PlanClarificationRequired,
    PlanValidationError,
    ReplanningDenialViolationError,
    SandboxViolationError,
    UnresolvableActionError,
)
from core.are.execution_state import (
    AREPlanExecutionState,
    AREStepExecutionRecord,
)
from core.are.models import (
    AREDiagnosis,
    AREPlanProposal,
    ARERecoveryProposal,
    ARERuntimeMode,
    AREStepProposal,
)
from core.are.plan_validator import (
    LLMPlanProposal,
    LLMStepProposal,
    PlanValidator,
)
from core.are.runtime import (
    ARERuntime,
    get_are_runtime,
    reset_are_runtime,
)

__all__ = [
    "ARERuntimeMode",
    "AREStepProposal",
    "AREPlanProposal",
    "AREDiagnosis",
    "ARERecoveryProposal",
    "ARERuntime",
    "get_are_runtime",
    "reset_are_runtime",
    # Catálogo y Ejecutables
    "ActionCatalog",
    "ExecutableAction",
    "ActionVerificationStrategy",
    "get_default_action_catalog",
    # Flujo de datos
    "DataFlowResolver",
    # Validación y Contrato LLM
    "PlanValidator",
    "LLMPlanProposal",
    "LLMStepProposal",
    # Estado de ejecución
    "AREPlanExecutionState",
    "AREStepExecutionRecord",
    # Excepciones tipadas
    "AREPlanError",
    "UnresolvableActionError",
    "PlanValidationError",
    "MissingOutputDependencyError",
    "PlanBudgetExceededError",
    "ReplanningDenialViolationError",
    "SandboxViolationError",
    "PlanClarificationRequired",
]
