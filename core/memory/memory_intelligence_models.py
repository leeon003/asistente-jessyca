"""Modelos inmutables de Inteligencia de Memoria (memory_intelligence_models.py - Fase 21).

Estructuras de datos para el pipeline inteligente:
STORE -> INDEX -> RETRIEVE -> RANK -> VALIDATE -> CONTEXT

INVARIANTE DE SEGURIDAD ABSOLUTA:
MEMORY != AUTHORIZATION
Los recuerdos clasificados y estructurados son evidencia informativa (EVIDENCE) y jamás otorgan privilegios de seguridad.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.memory.memory_entry import MemoryEntry


class ContradictionType(StrEnum):
    """Tipos formales de contradicción epistémica entre entradas de memoria."""

    DIRECT_CONTRADICTION = "direct_contradiction"  # Afirmaciones opuestas directas (ej. Sí vs No)
    VALUE_MISMATCH = "value_mismatch"              # Desacuerdo en atributos/valores específicos
    PREFERENCE_CONFLICT = "preference_conflict"    # Preferencias opuestas del usuario (ej. modo oscuro vs modo claro)
    TEMPORAL_SUPERSEDED = "temporal_superseded"    # Actualización temporal legítima


class ContradictionResolution(StrEnum):
    """Estados de resolución para contradicciones detectadas."""

    UNRESOLVED = "unresolved"                      # Contradicción no resuelta (ambigüedad)
    REQUIRES_USER_CLARIFICATION = "requires_clarification"  # Requiere preguntar al usuario
    PRESERVED_BOTH = "preserved_both"              # Ambas memorias se preservan con advertencia
    SUPERSEDED = "superseded"                      # Memoria previa reemplazada por mayor jerarquía/recencia
    REJECTED_UNVERIFIED = "rejected_unverified"    # Intento de sobrescritura no verificada rechazado


@dataclass(frozen=True)
class RankedMemoryItem:
    """Entrada de memoria calificada multidimensionalmente por el ranking engine."""

    entry: MemoryEntry
    total_score: float
    relevance_score: float
    confidence_score: float
    provenance_score: float
    recency_score: float
    frequency_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry.entry_id,
            "key": self.entry.key,
            "content": self.entry.content,
            "total_score": round(self.total_score, 4),
            "relevance_score": round(self.relevance_score, 4),
            "confidence_score": round(self.confidence_score, 4),
            "provenance_score": round(self.provenance_score, 4),
            "recency_score": round(self.recency_score, 4),
            "frequency_score": round(self.frequency_score, 4),
            "confidence": str(self.entry.confidence),
            "provenance_source": str(self.entry.provenance.source),
        }


@dataclass(frozen=True)
class ContradictionReport:
    """Reporte estructurado e inmutable de detección de contradicciones."""

    has_contradiction: bool
    contradiction_type: ContradictionType | None = None
    existing_entry: MemoryEntry | None = None
    new_entry: MemoryEntry | None = None
    similarity_key: str | None = None
    resolution: ContradictionResolution = ContradictionResolution.UNRESOLVED
    explanation: str = ""
    requires_user_clarification: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_contradiction": self.has_contradiction,
            "contradiction_type": str(self.contradiction_type) if self.contradiction_type else None,
            "existing_entry_id": self.existing_entry.entry_id if self.existing_entry else None,
            "new_entry_id": self.new_entry.entry_id if self.new_entry else None,
            "similarity_key": self.similarity_key,
            "resolution": str(self.resolution),
            "explanation": self.explanation,
            "requires_user_clarification": self.requires_user_clarification,
        }


@dataclass(frozen=True)
class MemoryContextBundle:
    """Paquete de contexto de memoria formateado y validado para consumo de agentes y LLMs."""

    query: str
    ranked_items: tuple[RankedMemoryItem, ...] = ()
    contradictions: tuple[ContradictionReport, ...] = ()
    formatted_context: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_items(self) -> int:
        return len(self.ranked_items)

    @property
    def has_unresolved_contradictions(self) -> bool:
        return any(c.has_contradiction and c.resolution == ContradictionResolution.UNRESOLVED for c in self.contradictions)
