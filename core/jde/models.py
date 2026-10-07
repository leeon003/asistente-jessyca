"""Modelos inmutables de petición y resultado para JESSYCA Decision Engine (JDE).

Aplica la regla Anti-False Success:
claims_success solo puede ser True si state == DecisionState.SUCCESS y existe evidencia comprobada.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType


class FallbackSpec(BaseModel):
    """Especificación declarativa de acción fallback si la primaria falla o no se verifica."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = 10.0
    expected_outcome: dict[str, Any] = Field(default_factory=dict)


class VerificationRequirement(BaseModel):
    """Requisitos de comprobación que el Verifier debe verificar determinísticamente."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: str = "default"  # e.g., "process_running", "window_visible", "browser_tab", "file_exists", "mcp_state"
    target: str = ""
    expected_properties: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = 3.0
    poll_interval_seconds: float = 0.1
    mandatory: bool = True  # Si es True y la verificación no puede comprobarse -> UNKNOWN


class PolicyRequirement(BaseModel):
    """Requisitos de política y autorización previa."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_allowed_risk: str = "MEDIUM"
    requires_human_confirmation: bool = False
    allow_scheduled: bool = False
    security_context: dict[str, Any] = Field(default_factory=dict)


class DecisionRequest(BaseModel):
    """Solicitud unificada e inmutable de decisión para JDE."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str | None = None
    user_request: str = "JDE internal request"
    intent: str = "execute_action"
    proposed_action: str
    tool: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "SAFE"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    policy_requirements: PolicyRequirement = Field(default_factory=PolicyRequirement)
    verification_requirements: list[VerificationRequirement] = Field(default_factory=list)
    fallback: FallbackSpec | None = None
    timeout: float = 30.0
    session_id: str = "default_session"
    user_id: str = "default_user"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("request_id")
    @classmethod
    def _validate_request_id(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("request_id no puede ser vacío.")
        return clean

    @field_validator("intent")
    @classmethod
    def _validate_intent(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("intent no puede ser vacío.")
        return clean


class DecisionResult(BaseModel):
    """Resultado formal emitido por el Decision Engine con trazabilidad completa."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    state: DecisionState
    success: bool
    claims_success: bool
    message: str
    executed_action: str
    tool_used: str
    executor_status: ExecutionStatusType
    verification_status: VerificationStatusType
    used_fallback: bool = False
    retry_count: int = 0
    receipt_id: str | None = None
    receipt_data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    duration_ms: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _validate_anti_false_success(self) -> DecisionResult:
        """Invariante absoluta: claims_success NUNCA puede ser True a menos que state == SUCCESS."""
        if self.claims_success and self.state != DecisionState.SUCCESS:
            raise ValueError(
                f"Invariante violada (Anti-False Success): claims_success es True pero el estado es '{self.state}'."
            )
        if self.state == DecisionState.SUCCESS and not self.claims_success:
            raise ValueError(
                "Invariante violada: estado SUCCESS exige claims_success=True."
            )
        return self
