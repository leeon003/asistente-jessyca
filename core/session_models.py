"""Modelos inmutables para la gestión de estado de sesión y memoria persistente (Subetapa 10.1).

GARANTÍA ABSOLUTA DE SEGURIDAD Y PRIVACIDAD:
Modelos congelados e inmutables (`@dataclass(frozen=True)`). Representan el estado explícito de la sesión,
mensajes, hechos y preferencias. CERO capacidad de ejecución autónoma de herramientas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class SessionStatus(StrEnum):
    """Estados explícitos y controlados de una sesión de usuario/asistente."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    WAITING_INPUT = "WAITING_INPUT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    EMERGENCY_STOPPED = "EMERGENCY_STOPPED"


class SessionRole(StrEnum):
    """Roles de origen de los mensajes intercambiados en la sesión."""

    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True)
class SessionId:
    """Identificador inmutable de sesión con validación de formato."""

    value: str

    def __post_init__(self) -> None:
        if not self.value or not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("El SessionId debe ser una cadena no vacía.")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class SessionMessage:
    """Mensaje inmutable en el historial de conversación de la sesión."""

    message_id: str
    role: SessionRole
    content: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convierte el mensaje a diccionario estructurado."""
        return {
            "message_id": self.message_id,
            "role": str(self.role),
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class SessionFact:
    """Hecho o conocimiento extraído inmutable conservado en la memoria de sesión."""

    fact_id: str
    key: str
    value: str
    confidence: float
    timestamp: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise ValueError("La confianza del fact debe ser un valor numérico.")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"La confianza debe estar en el rango [0.0, 1.0]: {self.confidence}")

    def to_dict(self) -> dict[str, Any]:
        """Convierte el fact a diccionario estructurado."""
        return {
            "fact_id": self.fact_id,
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class SessionPreference:
    """Preferencia explícita de usuario inmutable en la sesión."""

    preference_id: str
    key: str
    value: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convierte la preferencia a diccionario estructurado."""
        return {
            "preference_id": self.preference_id,
            "key": self.key,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class SessionMetadata:
    """Metadatos inmutables de entorno y cliente de la sesión."""

    user_id: str
    client_id: str
    client_version: str
    ip_address_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convierte los metadatos a diccionario seguro."""
        return {
            "user_id": self.user_id,
            "client_id": self.client_id,
            "client_version": self.client_version,
            "ip_address_hash": self.ip_address_hash,
        }


@dataclass(frozen=True)
class SessionSnapshot:
    """Captura puntual e inmutable del estado de sesión."""

    snapshot_id: str
    session_id: str
    timestamp: datetime
    status: SessionStatus
    message_count: int
    fact_count: int
    preference_count: int
    state_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convierte el snapshot a diccionario estructurado."""
        return {
            "snapshot_id": self.snapshot_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "status": str(self.status),
            "message_count": self.message_count,
            "fact_count": self.fact_count,
            "preference_count": self.preference_count,
            "state_summary": self.state_summary,
        }


@dataclass(frozen=True)
class SessionState:
    """Estado inmutable completo de una sesión de Jessyca 3.0."""

    session_id: SessionId
    status: SessionStatus
    created_at: datetime
    updated_at: datetime
    messages: tuple[SessionMessage, ...]
    facts: tuple[SessionFact, ...]
    preferences: tuple[SessionPreference, ...]
    metadata: SessionMetadata
    current_task_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convierte el estado de sesión a diccionario estructurado."""
        return {
            "session_id": str(self.session_id),
            "status": str(self.status),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "messages": [m.to_dict() for m in self.messages],
            "facts": [f.to_dict() for f in self.facts],
            "preferences": [p.to_dict() for p in self.preferences],
            "metadata": self.metadata.to_dict(),
            "current_task_id": self.current_task_id,
        }
