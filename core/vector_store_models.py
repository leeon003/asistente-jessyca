"""Modelos e interfaces inmutables para la memoria semántica vectorial local (`core/vector_store_models.py` - Subetapa 12.1).

GARANTÍA ABSOLUTA DE SEGURIDAD:
REGLA CENTRAL DE NO AUTORIDAD:
MEMORY = EVIDENCE, MEMORY != AUTHORITY.
Los documentos vectoriales recuperados se tratan estrictamente como UNTRUSTED DATA.
No pueden conceder permisos, elevar el nivel de autonomía ni modificar decisiones del RiskEngine o PermissionManager.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from core.exceptions import MCPError


class VectorStoreError(MCPError):
    """Error base de la almacén vectorial de memoria semántica."""

    pass


class EmbeddingError(VectorStoreError):
    """Error emitido cuando falla la generación de vectores embedding."""

    pass


class VectorSizeExceededError(VectorStoreError):
    """Error emitido cuando se supera la capacidad máxima de almacenamiento de la memoria vectorial."""

    pass


@dataclass(frozen=True)
class EmbeddingVector:
    """Vector numérico embedding inmutable."""

    values: tuple[float, ...]
    dimension: int

    def __post_init__(self) -> None:
        if len(self.values) != self.dimension:
            raise EmbeddingError(f"La dimensión del vector ({len(self.values)}) no coincide con la esperada ({self.dimension}).")

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "sample": list(self.values[:5]),  # Muestra inicial para inspección ligera
        }


@dataclass(frozen=True)
class VectorDocument:
    """Documento inmutable almacenado en la memoria semántica vectorial."""

    doc_id: str
    content: str
    embedding: EmbeddingVector
    metadata: dict[str, str]
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "content_len": len(self.content),
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class VectorSearchResult:
    """Resultado inmutable de búsqueda por similitud semántica."""

    document: VectorDocument
    similarity_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.document.doc_id,
            "similarity_score": round(self.similarity_score, 4),
            "content_len": len(self.document.content),
            "metadata": dict(self.document.metadata),
        }


class IEmbeddingProvider(Protocol):
    """Protocolo abstracto para generadores locales de embeddings."""

    def generate_embedding(self, text: str) -> EmbeddingVector: ...


# Alias para conveniencia de importación
EmbeddingProvider = IEmbeddingProvider



class IVectorStore(Protocol):
    """Protocolo abstracto para almacenes vectoriales de memoria."""

    def add_document(self, doc: VectorDocument) -> bool: ...
    def search_similar(self, embedding: EmbeddingVector, top_k: int = 5, min_score: float = 0.5) -> tuple[VectorSearchResult, ...]: ...
    def delete_document(self, doc_id: str) -> bool: ...
    def list_documents(self) -> tuple[VectorDocument, ...]: ...
    def clear(self) -> bool: ...

