"""Motor de Workflows Multi-Step para JESSYCA 3.0 (Etapas 18.0, 18.1, 18.2 y 18.3).

Proporciona:
  - WorkflowDefinition & WorkflowStep: Modelos declarativos inmutables.
  - WorkflowState & StepState: Estados canónicos del ciclo de vida.
  - ExpectedState, ObservedState, VerificationStatus, VerificationFailurePolicy: Verificación entre pasos (Etapa 18.3).
  - WorkflowStepVerifier: Verificador Action -> Observe -> Compare -> VerificationResult.
  - StepExecutionPipeline: Pipeline atómico de 5 fases (validate -> authorize -> execute -> verify -> record).
  - WorkflowExecutor: Motor de ejecución con soporte de DAG, Timeout, Pause/Resume, Cancel y Rollback.
  - WorkflowStateSnapshot, IWorkflowStore, InMemoryWorkflowStore, SQLiteWorkflowStore: Persistencia segura.
  - WorkflowRecoveryManager: Recuperación tras reinicio con bloqueo de workflows DANGEROUS/CRITICAL.
"""

from core.workflow.executor import WorkflowExecutor
from core.workflow.models import (
    StepExecutionResult,
    StepState,
    StepVerificationRule,
    WorkflowDefinition,
    WorkflowExecutionResult,
    WorkflowSource,
    WorkflowState,
    WorkflowStateSnapshot,
    WorkflowStep,
)
from core.workflow.step_pipeline import (
    StepExecutionPipeline,
    StepSecurityError,
    StepVerificationFailedError,
    interpolate_parameters,
)
from core.workflow.verification import (
    ExpectedState,
    ObservedState,
    VerificationFailurePolicy,
    VerificationStatus,
    WorkflowStepVerifier,
    WorkflowVerificationResult,
)
from core.workflow.workflow_store import (
    InMemoryWorkflowStore,
    IWorkflowStore,
    SQLiteWorkflowStore,
    WorkflowPersistenceError,
    WorkflowRecoveryManager,
    WorkflowResumptionBlockedError,
)

__all__ = [
    # Models
    "WorkflowState",
    "StepState",
    "WorkflowSource",
    "StepVerificationRule",
    "WorkflowStep",
    "StepExecutionResult",
    "WorkflowDefinition",
    "WorkflowExecutionResult",
    "WorkflowStateSnapshot",
    # Verification (Etapa 18.3)
    "ExpectedState",
    "ObservedState",
    "VerificationStatus",
    "VerificationFailurePolicy",
    "WorkflowVerificationResult",
    "WorkflowStepVerifier",
    # Step Pipeline
    "StepExecutionPipeline",
    "StepSecurityError",
    "StepVerificationFailedError",
    "interpolate_parameters",
    # Executor
    "WorkflowExecutor",
    # Persistence & Recovery
    "IWorkflowStore",
    "InMemoryWorkflowStore",
    "SQLiteWorkflowStore",
    "WorkflowRecoveryManager",
    "WorkflowPersistenceError",
    "WorkflowResumptionBlockedError",
]
