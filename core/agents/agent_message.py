"""Estructura formal de mensajes entre agentes (agent_message.py - Fase 9: Multi-Agent Collaboration).

Define los mensajes estructurados e inmutables intercambiados entre agentes especializados en flujos colaborativos.
GARANTÍA DE SEGURIDAD:
- Estructura inmutable (@dataclass(frozen=True)).
- Rastreo de profundidad de delegación (delegation_depth) y cadena de procedencia (audit trail).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class AgentMessageType(StrEnum):
    """Tipos de mensajes en la comunicación inter-agente."""

    TASK_DELEGATION = "TASK_DELEGATION"
    TASK_RESULT = "TASK_RESULT"
    TASK_FAILURE = "TASK_FAILURE"
    QUERY = "QUERY"
    NOTIFICATION = "NOTIFICATION"


@dataclass(frozen=True)
class AgentMessage:
    """Mensaje inmutable intercambiado entre agentes durante una colaboración o delegación."""

    sender_agent_id: str
    recipient_agent_id: str
    message_type: AgentMessageType
    payload: dict[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: f"msg-{uuid.uuid4().hex[:8]}")
    delegation_depth: int = 0
    delegation_chain: tuple[str, ...] = field(default_factory=tuple)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    audit_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializa el mensaje a un diccionario estructurado."""
        return {
            "message_id": self.message_id,
            "sender_agent_id": self.sender_agent_id,
            "recipient_agent_id": self.recipient_agent_id,
            "message_type": str(self.message_type),
            "payload": dict(self.payload),
            "delegation_depth": self.delegation_depth,
            "delegation_chain": list(self.delegation_chain),
            "timestamp": self.timestamp.isoformat(),
            "audit_id": self.audit_id,
        }
