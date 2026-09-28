"""JESSYCA Decision Engine (JDE).

Capa central de decisión, autorización, ejecución gobernada, verificación determinista
y evidencia estructurada para JESSYCA 3.0 / 4.0.

Principios Fundamentales:
1. "Execution success" != "Real-world success".
2. No evidence = No success claim (Anti-False Success).
3. Desacoplamiento entre Executor y Verifier.
4. Fail-Safe: Ante duda o imposibilidad de verificación -> UNKNOWN.
5. Auditabilidad y Trazabilidad Criptográfica Inmutable.
"""

from __future__ import annotations

from core.jde.adapter import (
    JDEShadowAdapter,
    LocalAgentExecutionContext,
    get_jde_shadow_adapter,
)
from core.jde.authority import (
    CANARY_FORBIDDEN_ACTIONS,
    DEFAULT_CANARY_ALLOWLIST,
    ActionRiskTier,
    AuthorityDecision,
    AuthorityGateResult,
    AuthorityMode,
    JDEAuthorityGate,
    JDEAuthorityMetrics,
    classify_action_risk,
    get_authority_gate,
    is_canary_excluded_action,
    reset_authority_gate,
    validate_canary_scope,
)
from core.jde.capabilities import (
    Capability,
    CapabilityRegistry,
    get_capability_registry,
    reset_capability_registry,
)
from core.jde.engine import DecisionEngine, get_decision_engine
from core.jde.models import DecisionRequest, DecisionResult
from core.jde.policy import JDEPolicyDecision, JDEPolicyGate
from core.jde.promotion import (
    CapabilityEvaluationRecord,
    CapabilityPromotionManager,
    CapabilityPromotionPolicy,
    CapabilityPromotionReceipt,
    PromotionDecision,
    PromotionStatus,
    get_promotion_manager,
    reset_promotion_manager,
)
from core.jde.receipts import ActionReceipt, JDEEvidence
from core.jde.shadow import (
    DivergenceSeverity,
    JDEShadowMetrics,
    JDEShadowMode,
    ShadowClassification,
    ShadowEvaluation,
    get_jde_shadow_mode,
    redact_sensitive_data,
)
from core.jde.states import DecisionState
from core.jde.conflict import (
    ConflictResolutionResult,
    JDEConflictResolver,
)
from core.jde.contract import (
    DecisionContract,
    compute_contract_fingerprint,
)
from core.jde.replay import (
    JDEReplayEngine,
    ReplayResult,
)
from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeMode,
    JDERuntimeVerdict,
    JDERuntimeVerdictType,
    get_jde_runtime_binding,
    reset_jde_runtime_binding,
)
from core.jde.verification import (
    IVerifier,
    VerificationContract,
    VerificationOutcome,
    VerificationRequirement,
    VerifierRegistry,
    get_verifier_registry,
)

__all__ = [
    "ActionReceipt",
    "ActionRiskTier",
    "AuthorityDecision",
    "AuthorityGateResult",
    "AuthorityMode",
    "CANARY_FORBIDDEN_ACTIONS",
    "Capability",
    "CapabilityEvaluationRecord",
    "CapabilityPromotionManager",
    "CapabilityPromotionPolicy",
    "CapabilityPromotionReceipt",
    "CapabilityRegistry",
    "DEFAULT_CANARY_ALLOWLIST",
    "ConflictResolutionResult",
    "DecisionContract",
    "DecisionEngine",
    "DecisionRequest",
    "DecisionResult",
    "DecisionState",
    "DivergenceSeverity",
    "IVerifier",
    "JDEAuthorityGate",
    "JDEAuthorityMetrics",
    "JDEConflictResolver",
    "JDEEvidence",
    "JDEPolicyDecision",
    "JDEPolicyGate",
    "JDEReplayEngine",
    "JDERuntimeBinding",
    "JDERuntimeMode",
    "JDERuntimeVerdict",
    "JDERuntimeVerdictType",
    "JDEShadowAdapter",
    "JDEShadowMetrics",
    "JDEShadowMode",
    "LocalAgentExecutionContext",
    "PromotionDecision",
    "PromotionStatus",
    "ReplayResult",
    "ShadowClassification",
    "ShadowEvaluation",
    "VerificationContract",
    "VerificationOutcome",
    "VerificationRequirement",
    "VerifierRegistry",
    "classify_action_risk",
    "compute_contract_fingerprint",
    "get_authority_gate",
    "get_capability_registry",
    "get_decision_engine",
    "get_jde_shadow_adapter",
    "get_jde_shadow_mode",
    "get_jde_runtime_binding",
    "get_promotion_manager",
    "get_verifier_registry",
    "redact_sensitive_data",
    "reset_authority_gate",
    "reset_capability_registry",
    "reset_jde_runtime_binding",
    "reset_promotion_manager",
]

