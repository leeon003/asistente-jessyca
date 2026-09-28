"""Estructuras inmutables de Recibo y Evidencia para JESSYCA Decision Engine (JDE).

Garantiza la vinculación criptográfica entre la petición, la política, la ejecución física
y la evidencia de verificación post-acción.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType

# Patrones para redacción de secretos y datos sensibles
_SENSITIVE_KEY_PATTERNS = re.compile(
    r"(pass|pwd|secret|token|api_?key|auth|bearer|credential|pin|private_?key)",
    re.IGNORECASE,
)


def redact_sensitive_data(data: Any) -> Any:
    """Elimina o anonimiza recursivamente credenciales, tokens y secretos."""
    if isinstance(data, Mapping):
        redacted_dict: dict[str, Any] = {}
        for k, v in data.items():
            k_str = str(k)
            if _SENSITIVE_KEY_PATTERNS.search(k_str):
                redacted_dict[k_str] = "***REDACTED_SECRET***"
            else:
                redacted_dict[k_str] = redact_sensitive_data(v)
        return redacted_dict
    elif isinstance(data, (list, tuple, set)):
        return [redact_sensitive_data(item) for item in data]
    elif isinstance(data, str):
        if "bearer " in data.lower():
            return re.sub(r"(bearer\s+)[a-zA-Z0-9_\-\.]{8,}", r"\1***REDACTED***", data, flags=re.IGNORECASE)
        return data
    return data


def compute_receipt_fingerprint(
    request_id: str,
    action: str,
    tool: str,
    parameters: dict[str, Any],
    execution_status: str,
    verification_status: str,
    is_verified: bool,
    final_status: str,
    correlation_id: str | None = None,
    authority_mode: str | None = None,
    risk_tier: str | None = None,
    capability: str | None = None,
) -> str:
    """Calcula el hash SHA-256 canónico e inmutable del recibo de decisión."""
    canonical_payload: dict[str, Any] = {
        "request_id": request_id.strip(),
        "action": action.strip().lower(),
        "tool": tool.strip().lower(),
        "parameters": parameters,
        "execution_status": execution_status.strip().upper(),
        "verification_status": verification_status.strip().upper(),
        "is_verified": bool(is_verified),
        "final_status": final_status.strip().upper(),
    }
    if correlation_id:
        canonical_payload["correlation_id"] = correlation_id.strip()
    if authority_mode:
        canonical_payload["authority_mode"] = authority_mode.strip().upper()
    if risk_tier:
        canonical_payload["risk_tier"] = risk_tier.strip().upper()
    if capability:
        canonical_payload["capability"] = capability.strip().lower()

    canonical_json = json.dumps(canonical_payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class JDEEvidence(BaseModel):
    """Evidencia atómica observable recolectada por un Verifier."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    verification_type: str
    target: str
    is_verified: bool
    observed_state: dict[str, Any] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ActionReceipt(BaseModel):
    """Recibo formal inmutable generado tras cada ciclo de decisión y verificación."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_request: str
    action: str
    tool: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    authority_mode: str = "SHADOW"
    risk_tier: str = "LOW"
    capability: str | None = None
    executor: str
    verifier: str
    started_at: datetime
    finished_at: datetime
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    execution_status: ExecutionStatusType
    verification_status: VerificationStatusType
    verified: bool
    evidence: list[JDEEvidence] = Field(default_factory=list)
    final_status: DecisionState
    policy_verdict: str = "ALLOW"
    fingerprint: str = ""
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        request_id: str,
        user_request: str,
        action: str,
        tool: str,
        parameters: dict[str, Any],
        executor: str,
        verifier: str,
        started_at: datetime,
        finished_at: datetime,
        execution_status: ExecutionStatusType,
        verification_status: VerificationStatusType,
        verified: bool,
        final_status: DecisionState,
        evidence: list[JDEEvidence] | None = None,
        policy_verdict: str = "ALLOW",
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        timestamp: datetime | None = None,
        authority_mode: str = "SHADOW",
        risk_tier: str = "LOW",
        capability: str | None = None,
    ) -> ActionReceipt:
        """Factory determinista que calcula el fingerprint SHA-256."""
        ev_list = evidence or []
        corr_id = (correlation_id or request_id).strip()
        safe_params = redact_sensitive_data(parameters) if parameters else {}
        ts = timestamp or finished_at or datetime.now(UTC)

        fp = compute_receipt_fingerprint(
            request_id=request_id,
            action=action,
            tool=tool,
            parameters=safe_params,
            execution_status=execution_status.value,
            verification_status=verification_status.value,
            is_verified=verified,
            final_status=final_status.value,
            correlation_id=corr_id,
            authority_mode=authority_mode,
            risk_tier=risk_tier,
            capability=capability,
        )
        return cls(
            request_id=request_id,
            correlation_id=corr_id,
            user_request=user_request,
            action=action,
            tool=tool,
            parameters=safe_params,
            authority_mode=authority_mode,
            risk_tier=risk_tier,
            capability=capability,
            executor=executor,
            verifier=verifier,
            started_at=started_at,
            finished_at=finished_at,
            timestamp=ts,
            execution_status=execution_status,
            verification_status=verification_status,
            verified=verified,
            evidence=ev_list,
            final_status=final_status,
            policy_verdict=policy_verdict,
            fingerprint=fp,
            error_message=error_message,
            metadata=metadata or {},
        )

    def verify_integrity(self) -> bool:
        """Comprueba que el contenido del recibo no haya sido alterado posteriormente."""
        recalculated = compute_receipt_fingerprint(
            request_id=self.request_id,
            action=self.action,
            tool=self.tool,
            parameters=self.parameters,
            execution_status=self.execution_status.value,
            verification_status=self.verification_status.value,
            is_verified=self.verified,
            final_status=self.final_status.value,
            correlation_id=self.correlation_id,
            authority_mode=self.authority_mode,
            risk_tier=self.risk_tier,
            capability=self.capability,
        )
        return self.fingerprint == recalculated
