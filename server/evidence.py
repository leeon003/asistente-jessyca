"""Evidencia de Autorización y Contexto de Seguridad Cryptographic Binding (Subetapa 05.2).

Transporta la evidencia interna generada exclusivamente por las capas de seguridad de Jessyca.
Contiene un binding criptográfico (action_fingerprint SHA-256) vinculado estrictamente a:
tool_name + operation + parámetros canónicos + request_id.
Si cualquier parámetro o identificador es alterado post-autorización, la evidencia se invalida.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.types import JSONDict


def compute_evidence_fingerprint(
    tool_name: str,
    operation: str,
    parameters: JSONDict,
    request_id: str,
) -> str:
    """Calcula el hash canónico SHA-256 para la evidencia de autorización."""
    canonical_payload = {
        "tool_name": tool_name.strip().lower(),
        "operation": operation.strip().lower(),
        "parameters": parameters,
        "request_id": request_id.strip(),
    }
    canonical_json = json.dumps(canonical_payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthorizationEvidence:
    """Estructura inmutable de evidencia de autorización generada exclusivamente por el sistema."""

    request_id: str
    correlation_id: str
    tool_name: str
    operation: str
    risk_assessment: Any
    policy_result: Any
    permission_result: Any
    confirmation_result: Any
    action_fingerprint: str
    evidence_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def validate_integrity(
        self,
        tool_name: str,
        operation: str,
        parameters: JSONDict,
        request_id: str,
    ) -> bool:
        """Verifica la validez e integridad de la evidencia de autorización.

        Si los parámetros, la herramienta, la operación o el request_id cambian después de la autorización,
        el fingerprint recalculado no coincidirá y la validación devolverá False.
        """
        if self.request_id != request_id:
            return False
        if self.tool_name.lower() != tool_name.lower():
            return False
        if self.operation.lower() != operation.lower():
            return False

        expected_fingerprint = compute_evidence_fingerprint(
            tool_name=tool_name,
            operation=operation,
            parameters=parameters,
            request_id=request_id,
        )
        return self.action_fingerprint == expected_fingerprint

    @classmethod
    def create_valid(
        cls,
        tool_name: str,
        operation: str,
        parameters: JSONDict | None = None,
        request_id: str | None = None,
    ) -> "AuthorizationEvidence":
        """Factory de conveniencia que crea una evidencia de autorización válida.

        Útil para tests unitarios donde se necesita una evidencia válida sin pasar
        por el pipeline de autorización completo.
        """
        req_id = request_id or str(uuid.uuid4())
        params = parameters or {}
        fingerprint = compute_evidence_fingerprint(
            tool_name=tool_name,
            operation=operation,
            parameters=params,
            request_id=req_id,
        )
        return cls(
            request_id=req_id,
            correlation_id=str(uuid.uuid4()),
            tool_name=tool_name,
            operation=operation,
            risk_assessment={"level": "SAFE", "auto_approved": True},
            policy_result={"decision": "ALLOW", "is_allowed": True},
            permission_result={"granted": True},
            confirmation_result={"confirmed": True},
            action_fingerprint=fingerprint,
        )


def create_authorization_evidence(
    request_id: str,
    correlation_id: str,
    tool_name: str,
    operation: str,
    parameters: JSONDict,
    risk_assessment: Any,
    policy_result: Any,
    permission_result: Any,
    confirmation_result: Any = None,
) -> AuthorizationEvidence:
    """Crea una evidencia de autorización inmutable vinculada al fingerprint SHA-256."""
    fingerprint = compute_evidence_fingerprint(
        tool_name=tool_name,
        operation=operation,
        parameters=parameters,
        request_id=request_id,
    )
    return AuthorizationEvidence(
        request_id=request_id,
        correlation_id=correlation_id,
        tool_name=tool_name,
        operation=operation,
        risk_assessment=risk_assessment,
        policy_result=policy_result,
        permission_result=permission_result,
        confirmation_result=confirmation_result,
        action_fingerprint=fingerprint,
        evidence_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC),
    )
