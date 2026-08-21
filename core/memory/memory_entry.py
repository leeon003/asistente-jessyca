"""Modelo inmutable para las entradas de memoria (memory_entry.py - Fase 12: Multi-Agent Memory).

Define la unidad fundamental de memoria en JESSYCA 3.0 con soporte explícito para scope,
propietario, procedencia, nivel de confianza epistémica y metadatos de contexto.

GARANTÍA DE SEGURIDAD:
- Modelo congelado (@dataclass(frozen=True)) para garantizar inmutabilidad.
- NUNCA contiene punteros de ejecución ni métodos con efectos colaterales.
- MEMORY = EVIDENCE, MEMORY != AUTHORITY.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.memory.memory_exceptions import MemoryError
from core.memory.memory_provenance import (
    MemoryConfidence,
    MemoryProvenance,
    ProvenanceSource,
)
from core.memory.memory_scope import MemoryScope


@dataclass(frozen=True)
class MemoryEntry:
    """Entrada inmutable de memoria gobernada."""

    entry_id: str
    scope: MemoryScope
    owner: str
    key: str
    content: str
    provenance: MemoryProvenance
    confidence: MemoryConfidence = MemoryConfidence.UNVERIFIED
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    task_id: str | None = None
    session_id: str | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.entry_id or not isinstance(self.entry_id, str) or not self.entry_id.strip():
            raise MemoryError("El entry_id de la memoria debe ser una cadena no vacía.")
        if not self.key or not isinstance(self.key, str) or not self.key.strip():
            raise MemoryError("La clave (key) de la entrada de memoria no puede estar vacía.")
        if not self.owner or not isinstance(self.owner, str) or not self.owner.strip():
            raise MemoryError("El propietario (owner) de la entrada de memoria no puede estar vacío.")

    @classmethod
    def create(
        cls,
        key: str,
        content: str,
        scope: MemoryScope = MemoryScope.GLOBAL,
        owner: str = "global",
        provenance: MemoryProvenance | None = None,
        confidence: MemoryConfidence = MemoryConfidence.UNVERIFIED,
        entry_id: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
        tags: tuple[str, ...] | list[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """Constructor de conveniencia seguro para crear nuevas entradas de memoria."""
        eid = entry_id or f"mem_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)
        prov = provenance or MemoryProvenance(source=ProvenanceSource.SYSTEM, creator_id="system")

        # Regla de seguridad: Si la procedencia proviene de un LLM y no está validada, forzar UNVERIFIED
        resolved_conf = confidence
        if prov.source == ProvenanceSource.LLM and prov.is_unverified_claim and confidence == MemoryConfidence.VERIFIED:
            resolved_conf = MemoryConfidence.UNVERIFIED

        return cls(
            entry_id=eid,
            scope=scope,
            owner=str(owner).strip(),
            key=str(key).strip(),
            content=str(content),
            provenance=prov,
            confidence=resolved_conf,
            created_at=now,
            updated_at=now,
            task_id=task_id,
            session_id=session_id,
            tags=tuple(tags),
            metadata=dict(metadata or {}),
        )

    def with_update(
        self,
        content: str | None = None,
        confidence: MemoryConfidence | None = None,
        metadata_updates: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """Genera una nueva instancia inmutable con campos actualizados manteniendo el entry_id y created_at."""
        new_meta = dict(self.metadata)
        if metadata_updates:
            new_meta.update(metadata_updates)

        return MemoryEntry(
            entry_id=self.entry_id,
            scope=self.scope,
            owner=self.owner,
            key=self.key,
            content=content if content is not None else self.content,
            provenance=self.provenance,
            confidence=confidence if confidence is not None else self.confidence,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            task_id=self.task_id,
            session_id=self.session_id,
            tags=self.tags,
            metadata=new_meta,
        )

    def with_promoted_confidence(
        self,
        new_confidence: MemoryConfidence,
        verifier_id: str,
        verifier_source: ProvenanceSource,
        evidence: str,
    ) -> MemoryEntry:
        """Promueve formalmente el nivel de confianza de la entrada actualizando su procedencia."""
        new_prov = self.provenance.promote_to_verified(
            verifier_id=verifier_id,
            verifier_source=verifier_source,
            evidence=evidence,
        )
        return MemoryEntry(
            entry_id=self.entry_id,
            scope=self.scope,
            owner=self.owner,
            key=self.key,
            content=self.content,
            provenance=new_prov,
            confidence=new_confidence,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            task_id=self.task_id,
            session_id=self.session_id,
            tags=self.tags,
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa la entrada de memoria a un diccionario seguro para auditoría o exportación."""
        return {
            "entry_id": self.entry_id,
            "scope": str(self.scope),
            "owner": self.owner,
            "key": self.key,
            "content": self.content,
            "confidence": str(self.confidence),
            "provenance": self.provenance.to_dict(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "task_id": self.task_id,
            "session_id": self.session_id,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }
