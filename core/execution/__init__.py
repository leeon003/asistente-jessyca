"""Módulo de ejecución y verificación determinista de JESSYCA."""

from core.execution.action_pipeline import (
    ActionPipeline,
    ActionPipelineResult,
    ActionPipelineStatus,
    get_action_pipeline,
)
from core.execution.execution_dispatcher import (
    DispatchResult,
    DispatchStatus,
    ExecutionDispatcher,
)
from core.execution.execution_gate_bridge import (
    ConfirmationBridgeStatus,
    ExecutionDecision,
    ExecutionGateBridge,
    GateDecisionType,
)
from core.execution.execution_verifier import (
    ExecutionEvidence,
    ExecutionResult,
    ExecutionStatus,
    ExecutionVerifier,
    FileCopiedVerificationStrategy,
    FileDeletedVerificationStrategy,
    FileExistsVerificationStrategy,
    FileMovedVerificationStrategy,
    IVerificationStrategy,
    ProcessExistsVerificationStrategy,
    ProcessTerminatedVerificationStrategy,
    StateChangedVerificationStrategy,
    get_execution_verifier,
)
from core.execution.idempotency_guard import (
    ExecutionFingerprint,
    ExecutionIdempotencyGuard,
    ExecutionRecord,
    get_idempotency_guard,
)
from core.execution.post_execution_verifier import (
    PostExecutionVerifier,
    VerificationReport,
    VerificationReportStatus,
)
from core.execution.operation_manager import (
    ConcurrencyLimitError,
    IdempotencyConflictError,
    OperationManager,
    OperationRecord,
    OperationStatus,
    SessionIsolationError,
    get_operation_manager,
)
from core.execution.verification_event_adapter import (
    ActionVerificationAdapter,
    VerificationStatus,
)

__all__ = [
    "ActionPipeline",
    "ActionPipelineResult",
    "ActionPipelineStatus",
    "ActionVerificationAdapter",
    "ConcurrencyLimitError",
    "ConfirmationBridgeStatus",
    "DispatchResult",
    "DispatchStatus",
    "ExecutionDecision",
    "ExecutionDispatcher",
    "ExecutionEvidence",
    "ExecutionFingerprint",
    "ExecutionGateBridge",
    "ExecutionIdempotencyGuard",
    "ExecutionRecord",
    "ExecutionResult",
    "ExecutionStatus",
    "ExecutionVerifier",
    "FileCopiedVerificationStrategy",
    "FileDeletedVerificationStrategy",
    "FileExistsVerificationStrategy",
    "FileMovedVerificationStrategy",
    "GateDecisionType",
    "IVerificationStrategy",
    "IdempotencyConflictError",
    "OperationManager",
    "OperationRecord",
    "OperationStatus",
    "PostExecutionVerifier",
    "ProcessExistsVerificationStrategy",
    "ProcessTerminatedVerificationStrategy",
    "SessionIsolationError",
    "StateChangedVerificationStrategy",
    "VerificationReport",
    "VerificationReportStatus",
    "VerificationStatus",
    "get_action_pipeline",
    "get_execution_verifier",
    "get_idempotency_guard",
    "get_operation_manager",
]



