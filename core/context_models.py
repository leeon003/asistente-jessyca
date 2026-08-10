"""Modelos inmutables para la construcción de contexto y recuperación de memoria (Subetapa 10.2).

GARANTÍA ABSOLUTA DE SEGURIDAD Y PRIVACIDAD:
Modelos congelados e inmutables (`@dataclass(frozen=True)`). Representan consultas, elementos, secciones
y snapshots de contexto inmutables. CERO capacidad de ejecución autónoma de herramientas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class ContextSource(StrEnum):
    """Orígenes estructurados de información para los elementos de contexto."""

    SESSION_STATE = "SESSION_STATE"
    RECENT_MESSAGES = "RECENT_MESSAGES"
    PREFERENCES = "PREFERENCES"
    FACTS = "FACTS"
    HISTORICAL_CONTEXT = "HISTORICAL_CONTEXT"
    METADATA = "METADATA"
    SEMANTIC_MEMORY = "SEMANTIC_MEMORY"


@dataclass(frozen=True)
class ContextQuery:
    """Consulta parametrizada e inmutable para la recuperación de memoria de sesión y semántica."""

    session_id: str
    max_messages: int = 50
    max_facts: int = 50
    max_preferences: int = 50
    max_semantic_items: int = 10
    max_total_size: int = 524288
    include_facts: bool = True
    include_preferences: bool = True
    include_messages: bool = True
    include_semantic_memory: bool = True
    query_filter: str | None = None
    semantic_query: str | None = None

    def __post_init__(self) -> None:
        if not self.session_id or not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("El session_id de la consulta debe ser una cadena no vacía.")




    def to_dict(self) -> dict[str, Any]:
        """Convierte la consulta a diccionario estructurado."""
        return {
            "session_id": self.session_id,
            "max_messages": self.max_messages,
            "max_facts": self.max_facts,
            "max_preferences": self.max_preferences,
            "max_total_size": self.max_total_size,
            "include_facts": self.include_facts,
            "include_preferences": self.include_preferences,
            "include_messages": self.include_messages,
            "query_filter": self.query_filter,
        }


@dataclass(frozen=True)
class ContextItem:
    """Elemento individual de datos inmutable incorporado al contexto."""

    item_id: str
    source: ContextSource
    key: str
    content: str
    priority: int
    timestamp: datetime
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convierte el elemento de contexto a diccionario estructurado."""
        return {
            "item_id": self.item_id,
            "source": str(self.source),
            "key": self.key,
            "content": self.content,
            "priority": self.priority,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ContextSection:
    """Sección agrupadora e inmutable de elementos de contexto por origen/prioridad."""

    section_id: str
    title: str
    source: ContextSource
    items: tuple[ContextItem, ...]
    priority: int

    def to_dict(self) -> dict[str, Any]:
        """Convierte la sección a diccionario estructurado."""
        return {
            "section_id": self.section_id,
            "title": self.title,
            "source": str(self.source),
            "items": [item.to_dict() for item in self.items],
            "priority": self.priority,
        }


@dataclass(frozen=True)
class ContextMetadata:
    """Metadatos inmutables del snapshot de contexto generado."""

    query_id: str
    session_id_hash: str
    created_at: datetime
    total_items: int
    total_size_bytes: int
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        """Convierte los metadatos de contexto a diccionario seguro."""
        return {
            "query_id": self.query_id,
            "session_id_hash": self.session_id_hash,
            "created_at": self.created_at.isoformat(),
            "total_items": self.total_items,
            "total_size_bytes": self.total_size_bytes,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class ContextSnapshot:
    """Snapshot puntual, inmutable y aislado del contexto de sesión generado para el agente."""

    snapshot_id: str
    query: ContextQuery
    sections: tuple[ContextSection, ...]
    metadata: ContextMetadata

    def to_dict(self) -> dict[str, Any]:
        """Convierte el snapshot completo a diccionario estructurado."""
        return {
            "snapshot_id": self.snapshot_id,
            "query": self.query.to_dict(),
            "sections": [sec.to_dict() for sec in self.sections],
            "metadata": self.metadata.to_dict(),
        }
