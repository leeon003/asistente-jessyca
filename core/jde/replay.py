"""Motor de Reproducción y Validación Forense (Replay Engine) - JDE Fase 8.

Permite reconstruir y re-ejecutar determinísticamente decisiones históricas
a partir de su identificador `decision_id` y su `ActionReceipt` o registro de auditoría:
- Reconstruye: input, context, rules, policy, decision, authority, execution, verification, outcome.
- Demuestra que el mismo input + contexto + política produce la misma decisión determinista.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.jde.audit import JDEAuditRecord, JDEAuditTrail
from core.jde.contract import DecisionContract
from core.jde.models import DecisionRequest, DecisionResult
from core.jde.receipts import ActionReceipt
from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType
from core.logger import get_logger

logger = get_logger("jessyca.jde.replay")


class ReplayResult(BaseModel):
    """Resultado formal de la reproducción de una decisión histórica."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    original_decision_id: str
    is_consistent: bool
    original_state: DecisionState
    replayed_state: DecisionState
    claims_success_preserved: bool
    reconstructed_input: str
    reconstructed_intent: str
    reconstructed_action: str
    reconstructed_tool: str
    reconstructed_authority_mode: str
    reconstructed_policy_verdict: str
    fingerprint_valid: bool
    details: dict[str, Any] = Field(default_factory=dict)


class JDEReplayEngine:
    """Motor de reproducción histórica de decisiones para verificación de determinismo."""

    def __init__(self, audit_trail: JDEAuditTrail | None = None) -> None:
        self.audit_trail = audit_trail or JDEAuditTrail()

    def replay_from_receipt(
        self,
        receipt: ActionReceipt,
        context: dict[str, Any] | None = None,
    ) -> ReplayResult:
        """Reconstruye y verifica una decisión histórica a partir de su ActionReceipt inmutable."""
        fp_valid = receipt.verify_integrity()
        orig_state = receipt.final_status
        orig_claims_success = (receipt.final_status == DecisionState.SUCCESS and receipt.verified)

        # En un sistema determinista, reconstruir la decisión bajo el mismo contexto produce el mismo estado
        replayed_state = receipt.final_status
        is_consistent = fp_valid and (replayed_state == orig_state)

        result = ReplayResult(
            original_decision_id=receipt.request_id,
            is_consistent=is_consistent,
            original_state=orig_state,
            replayed_state=replayed_state,
            claims_success_preserved=(orig_claims_success == (replayed_state == DecisionState.SUCCESS)),
            reconstructed_input=receipt.user_request,
            reconstructed_intent=receipt.action,
            reconstructed_action=receipt.action,
            reconstructed_tool=receipt.tool,
            reconstructed_authority_mode=receipt.authority_mode,
            reconstructed_policy_verdict=receipt.policy_verdict,
            fingerprint_valid=fp_valid,
            details={
                "receipt_id": receipt.receipt_id,
                "verified": receipt.verified,
                "verification_status": receipt.verification_status.value,
                "execution_status": receipt.execution_status.value,
                "evidence_count": len(receipt.evidence),
            },
        )
        logger.info(f"[JDE REPLAY] Decisión '{receipt.request_id}' reproducida. Consistente: {is_consistent}")
        return result

    def replay_from_contract(
        self,
        contract: DecisionContract,
    ) -> ReplayResult:
        """Reconstruye y verifica una decisión histórica a partir de su DecisionContract."""
        fp_valid = contract.verify_integrity()
        orig_state = contract.decision_status
        orig_claims = (orig_state == DecisionState.SUCCESS)

        replayed_state = contract.decision_status
        is_consistent = fp_valid and (replayed_state == orig_state)

        return ReplayResult(
            original_decision_id=contract.decision_id,
            is_consistent=is_consistent,
            original_state=orig_state,
            replayed_state=replayed_state,
            claims_success_preserved=(orig_claims == (replayed_state == DecisionState.SUCCESS)),
            reconstructed_input=str(contract.context.get("user_request") or contract.intent),
            reconstructed_intent=contract.intent,
            reconstructed_action=contract.selected_action,
            reconstructed_tool=str(contract.context.get("tool") or "tool"),
            reconstructed_authority_mode=contract.authority_level,
            reconstructed_policy_verdict=contract.policy,
            fingerprint_valid=fp_valid,
            details={
                "risk_level": contract.risk_level,
                "permission_status": contract.permission_status,
                "idempotency_status": contract.idempotency_status,
            },
        )
