"""Paquete de Aprendizaje, Automejora Segura, Regresiones y Ciclo Diario (core/learning - Fases 59, 60, 61 & 63).

Exporta los modelos, validadores, simuladores, almacenes, entornos de sandbox,
evaluadores, versionamiento, despliegue, rollback, motor de regresiones y
ciclo diario de aprendizaje del JESSYCA EXPERIENCE & LEARNING ENGINE.
"""

from __future__ import annotations

from core.learning.daily import (
    DailyLearningCycle,
    DailyLearningPolicy,
    DailyLearningReport,
    DailyLearningRun,
    DailyLearningScheduler,
    DailyRunStatus,
)
from core.learning.deployment import (
    ApprovalType,
    ControlledDeployer,
    DeploymentResult,
)
from core.learning.evaluator import (
    EvaluationResult,
    ImprovementEvaluator,
)
from core.learning.improvement_engine import SafeImprovementEngine
from core.learning.proposal_engine import LearningProposalEngine
from core.learning.proposal_models import (
    LearningProposal,
    ProposalCategory,
    ProposalRiskLevel,
    ProposalStatus,
    SimulationResult,
)
from core.learning.proposal_store import (
    InMemoryProposalStore,
    IProposalStore,
    SQLiteProposalStore,
)
from core.learning.proposal_validator import (
    PROTECTED_SECURITY_COMPONENTS,
    ProposalValidator,
    is_security_component,
)
from core.learning.regression import (
    FORBIDDEN_DESTRUCTIVE_PATTERNS,
    InMemoryRegressionStore,
    IRegressionStore,
    RegressionCase,
    RegressionCategory,
    RegressionEngine,
    RegressionSeverity,
    RegressionStatus,
    RegressionSuiteStats,
    RegressionTestGenerator,
    RegressionValidator,
    SQLiteRegressionStore,
)
from core.learning.rollback import (
    RollbackManager,
    RollbackResult,
)
from core.learning.sandbox import (
    SECURITY_IMMUTABLE_ZONE,
    SandboxEnvironment,
    SandboxSecurityError,
    SandboxSecurityViolation,
    is_in_immutable_security_zone,
)
from core.learning.simulator import (
    IProposalSimulator,
    ProposalSimulator,
)
from core.learning.version_manager import (
    CandidateStatus,
    ImprovementCandidate,
    VersionManager,
    VersionSnapshot,
)

__all__ = [
    "FORBIDDEN_DESTRUCTIVE_PATTERNS",
    "ApprovalType",
    "CandidateStatus",
    "ControlledDeployer",
    "DailyLearningCycle",
    "DailyLearningPolicy",
    "DailyLearningReport",
    "DailyLearningRun",
    "DailyLearningScheduler",
    "DailyRunStatus",
    "DeploymentResult",
    "EvaluationResult",
    "IProposalSimulator",
    "IProposalStore",
    "IRegressionStore",
    "ImprovementCandidate",
    "ImprovementEvaluator",
    "InMemoryProposalStore",
    "InMemoryRegressionStore",
    "LearningProposal",
    "LearningProposalEngine",
    "PROTECTED_SECURITY_COMPONENTS",
    "ProposalCategory",
    "ProposalRiskLevel",
    "ProposalSimulator",
    "ProposalStatus",
    "ProposalValidator",
    "RegressionCase",
    "RegressionCategory",
    "RegressionEngine",
    "RegressionSeverity",
    "RegressionStatus",
    "RegressionSuiteStats",
    "RegressionTestGenerator",
    "RegressionValidator",
    "RollbackManager",
    "RollbackResult",
    "SECURITY_IMMUTABLE_ZONE",
    "SQLiteProposalStore",
    "SQLiteRegressionStore",
    "SafeImprovementEngine",
    "SandboxEnvironment",
    "SandboxSecurityError",
    "SandboxSecurityViolation",
    "SimulationResult",
    "VersionManager",
    "VersionSnapshot",
    "is_in_immutable_security_zone",
    "is_security_component",
]
