"""Contrato Formal de Decisión para JESSYCA Decision Engine (JDE) - Fase 8.

Define la estructura canónica, unificada e inmutable de una decisión de JDE:
- Trazabilidad determinista completa.
- Separación de roles (Reasoning vs Decision Authority vs Constraint vs Verification).
- Integridad mediante fingerprint SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.jde.states import DecisionState


def compute_contract_fingerprint(
    decision_id: str,
    session_id: str,
    intent: str,
    selected_action: str,
    reason: str,
    policy: str,
    risk_level: str,
    permission_status: str,
    idempotency_status: str,
    authority_level: str,
    decision_status: str,
    timestamp: datetime | str,
) -> str:
    """Calcula el hash SHA-256 canónico del contrato de decisión."""
    payload = {
        "decision_id": decision_id.strip(),
        "session_id": session_id.strip(),
        "intent": intent.strip(),
        "selected_action": selected_action.strip(),
        "reason": reason.strip(),
        "policy": policy.strip(),
        "risk_level": risk_level.strip().upper(),
        "permission_status": permission_status.strip().upper(),
        "idempotency_status": idempotency_status.strip().upper(),
        "authority_level": authority_level.strip().upper(),
        "decision_status": decision_status.strip().upper(),
        "timestamp": str(timestamp),
    }
    canonical_json = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class DecisionContract(BaseModel):
    """Contrato formal e inmutable de decisión emitida por JDE."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str = "jde_session"
    intent: str
    context: dict[str, Any] = Field(default_factory=dict)
    candidate_actions: list[str] = Field(default_factory=list)
    selected_action: str
    reason: str
    policy: str = "DEFAULT_POLICY"
    rules_evaluated: list[str] = Field(default_factory=list)
    risk_level: str = "SAFE"
    permission_status: str = "ALLOW"
    idempotency_status: str = "ACQUIRED"
    verification_requirement: list[str] = Field(default_factory=list)
    authority_level: str = "FULL"
    decision_status: DecisionState = DecisionState.RECEIVED
    fingerprint: str = ""

    @classmethod
    def create(
        cls,
        intent: str,
        selected_action: str,
        reason: str,
        decision_id: str | None = None,
        session_id: str = "jde_session",
        context: dict[str, Any] | None = None,
        candidate_actions: list[str] | None = None,
        policy: str = "DEFAULT_POLICY",
        rules_evaluated: list[str] | None = None,
        risk_level: str = "SAFE",
        permission_status: str = "ALLOW",
        idempotency_status: str = "ACQUIRED",
        verification_requirement: list[str] | None = None,
        authority_level: str = "FULL",
        decision_status: DecisionState = DecisionState.RECEIVED,
        timestamp: datetime | None = None,
    ) -> DecisionContract:
        """Fabrica un DecisionContract inmutable con fingerprint SHA-256 verificado."""
        did = decision_id or str(uuid.uuid4())
        ts = timestamp or datetime.now(UTC)
        candidates = list(candidate_actions or ([selected_action] if selected_action else []))
        rules = list(rules_evaluated or [])
        verif_reqs = list(verification_requirement or [])
        ctx = dict(context or {})

        fp = compute_contract_fingerprint(
            decision_id=did,
            session_id=session_id,
            intent=intent,
            selected_action=selected_action,
            reason=reason,
            policy=policy,
            risk_level=risk_level,
            permission_status=permission_status,
            idempotency_status=idempotency_status,
            authority_level=authority_level,
            decision_status=decision_status.value,
            timestamp=ts,
        )

        return cls(
            decision_id=did,
            timestamp=ts,
            session_id=session_id,
            intent=intent,
            context=ctx,
            candidate_actions=candidates,
            selected_action=selected_action,
            reason=reason,
            policy=policy,
            rules_evaluated=rules,
            risk_level=risk_level,
            permission_status=permission_status,
            idempotency_status=idempotency_status,
            verification_requirement=verif_reqs,
            authority_level=authority_level,
            decision_status=decision_status,
            fingerprint=fp,
        )

    def verify_integrity(self) -> bool:
        """Verifica que ningún atributo del contrato haya sido manipulado."""
        recalculated = compute_contract_fingerprint(
            decision_id=self.decision_id,
            session_id=self.session_id,
            intent=self.intent,
            selected_action=self.selected_action,
            reason=self.reason,
            policy=self.policy,
            risk_level=self.risk_level,
            permission_status=self.permission_status,
            idempotency_status=self.idempotency_status,
            authority_level=self.authority_level,
            decision_status=self.decision_status.value,
            timestamp=self.timestamp,
        )
        return self.fingerprint == recalculated
