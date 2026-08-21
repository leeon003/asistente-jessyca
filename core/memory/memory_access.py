"""Control de acceso y solicitudes estructuradas de memoria (memory_access.py - Fase 12).

Implementa las estructuras de datos y mediación para compartir memoria entre agentes de forma segura
y solicitar la promoción formal de afirmaciones a hechos verificados.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.memory.memory_entry import MemoryEntry
from core.memory.memory_exceptions import (
    MemoryAccessDeniedError,
    MemoryIsolationViolationError,
    MemoryPromotionError,
)
from core.memory.memory_policy import MemoryPolicy
from core.memory.memory_provenance import (
    MemoryConfidence,
    ProvenanceSource,
)
from core.memory.memory_scope import MemoryScope


@dataclass(frozen=True)
class MemoryShareRequest:
    """Solicitud formal de compartición de una entrada de memoria entre dos agentes."""

    request_id: str
    sender_agent_id: str
    recipient_agent_id: str
    entry_id: str
    reason: str
    target_scope: MemoryScope = MemoryScope.TASK
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        sender_agent_id: str,
        recipient_agent_id: str,
        entry_id: str,
        reason: str,
        target_scope: MemoryScope = MemoryScope.TASK,
    ) -> MemoryShareRequest:
        return cls(
            request_id=f"mshare_{uuid.uuid4().hex[:8]}",
            sender_agent_id=str(sender_agent_id).strip(),
            recipient_agent_id=str(recipient_agent_id).strip(),
            entry_id=str(entry_id).strip(),
            reason=str(reason).strip(),
            target_scope=target_scope,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "sender_agent_id": self.sender_agent_id,
            "recipient_agent_id": self.recipient_agent_id,
            "entry_id": self.entry_id,
            "reason": self.reason,
            "target_scope": str(self.target_scope),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class MemoryPromotionRequest:
    """Solicitud estructurada para elevar la confianza de una memoria con evidencia."""

    request_id: str
    entry_id: str
    requested_by: str
    verifier_id: str
    verifier_source: ProvenanceSource
    target_confidence: MemoryConfidence
    evidence: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        entry_id: str,
        requested_by: str,
        verifier_id: str,
        verifier_source: ProvenanceSource,
        target_confidence: MemoryConfidence = MemoryConfidence.VERIFIED,
        evidence: str = "Verification evidence",
    ) -> MemoryPromotionRequest:
        return cls(
            request_id=f"mprom_{uuid.uuid4().hex[:8]}",
            entry_id=str(entry_id).strip(),
            requested_by=str(requested_by).strip(),
            verifier_id=str(verifier_id).strip(),
            verifier_source=verifier_source,
            target_confidence=target_confidence,
            evidence=str(evidence).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "entry_id": self.entry_id,
            "requested_by": self.requested_by,
            "verifier_id": self.verifier_id,
            "verifier_source": str(self.verifier_source),
            "target_confidence": str(self.target_confidence),
            "evidence": self.evidence,
            "timestamp": self.timestamp.isoformat(),
        }


class MemoryAccessControl:
    """Validador y mediador de transacciones de acceso a memoria."""

    def __init__(self, policy: MemoryPolicy | None = None) -> None:
        self.policy = policy or MemoryPolicy()

    def enforce_read(self, agent_id: str, entry: MemoryEntry) -> None:
        """Verifica permiso de lectura. Lanza MemoryIsolationViolationError o MemoryAccessDeniedError si es rechazado."""
        if not self.policy.can_read(agent_id=agent_id, entry=entry):
            if entry.scope == MemoryScope.AGENT and entry.owner != agent_id:
                raise MemoryIsolationViolationError(
                    f"[ISOLATION VIOLATION] El agente '{agent_id}' no tiene permiso para leer la memoria privada de '{entry.owner}' (entry_id: '{entry.entry_id}')."
                )
            raise MemoryAccessDeniedError(
                f"[ACCESS DENIED] El agente '{agent_id}' no tiene autorización de lectura para la memoria '{entry.entry_id}' (scope: '{entry.scope}')."
            )

    def enforce_write(self, agent_id: str, scope: MemoryScope, target_owner: str) -> None:
        """Verifica permiso de escritura. Lanza excepción si es rechazado."""
        if not self.policy.can_write(agent_id=agent_id, scope=scope, target_owner=target_owner):
            if scope == MemoryScope.AGENT and target_owner != agent_id:
                raise MemoryIsolationViolationError(
                    f"[ISOLATION VIOLATION] El agente '{agent_id}' no puede escribir en la memoria privada de '{target_owner}'."
                )
            raise MemoryAccessDeniedError(
                f"[ACCESS DENIED] El agente '{agent_id}' no puede escribir en el scope '{scope}' con propietario '{target_owner}'."
            )

    def enforce_update(self, agent_id: str, entry: MemoryEntry) -> None:
        """Verifica permiso de actualización."""
        if not self.policy.can_update(agent_id=agent_id, entry=entry):
            raise MemoryAccessDeniedError(
                f"[ACCESS DENIED] El agente '{agent_id}' no puede modificar la memoria '{entry.entry_id}' perteneciente a '{entry.owner}'."
            )

    def enforce_delete(self, agent_id: str, entry: MemoryEntry) -> None:
        """Verifica permiso de eliminación."""
        if not self.policy.can_delete(agent_id=agent_id, entry=entry):
            raise MemoryAccessDeniedError(
                f"[ACCESS DENIED] El agente '{agent_id}' no puede eliminar la memoria '{entry.entry_id}' perteneciente a '{entry.owner}'."
            )

    def enforce_promotion(self, request: MemoryPromotionRequest, entry: MemoryEntry) -> None:
        """Verifica si la promoción de confianza cumple las políticas autoritativas."""
        if not self.policy.can_promote(
            agent_id=request.requested_by,
            entry=entry,
            new_confidence=request.target_confidence,
            verifier_source=request.verifier_source,
        ):
            raise MemoryPromotionError(
                f"[PROMOTION DENIED] No se puede promover la memoria '{entry.entry_id}' a '{request.target_confidence}' "
                f"con fuente no autoritativa '{request.verifier_source}'."
            )

    def enforce_share(self, request: MemoryShareRequest, entry: MemoryEntry) -> None:
        """Verifica si la solicitud de compartir memoria es válida."""
        if not self.policy.can_share(
            sender_agent_id=request.sender_agent_id,
            recipient_agent_id=request.recipient_agent_id,
            entry=entry,
        ):
            raise MemoryAccessDeniedError(
                f"[SHARE DENIED] El agente '{request.sender_agent_id}' no puede compartir la memoria '{entry.entry_id}' "
                f"perteneciente a '{entry.owner}' con '{request.recipient_agent_id}'."
            )
