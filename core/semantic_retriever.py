"""Motor de recuperación de memoria semántica vectorial (SemanticMemoryRetriever - Subetapa 12.2).

GARANTÍA ABSOLUTA DE SEGURIDAD:
MEMORY = EVIDENCE, MEMORY ≠ AUTHORITY.
Pipeline unidireccional estricto:
retrieval -> normalization -> sanitization -> ContextSecurityManager -> ContextSnapshot
NUNCA: retrieval -> direct prompt injection
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.command_output import SecretRedactor
from core.context_models import ContextItem, ContextQuery, ContextSource
from core.context_security import ContextSecurityManager
from core.logger import get_logger
from core.ocr_sanitizer import OCRTextSanitizer
from core.vector_store_models import (
    IEmbeddingProvider,
    IVectorStore,
    VectorDocument,
    VectorSearchResult,
)

logger = get_logger("jessyca.core.semantic_retriever")


class SemanticMemoryType(StrEnum):
    """Taxonomía formal de 6 tipos de memoria semántica (Etapa 12.0)."""

    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    EPISODIC = "EPISODIC"
    TASK = "TASK"
    TECHNICAL = "TECHNICAL"
    TEMPORARY = "TEMPORARY"


# Tiempos de retención por defecto en segundos para cada tipo de memoria
RETENTION_POLICY_SECONDS: dict[SemanticMemoryType, float | None] = {
    SemanticMemoryType.TEMPORARY: 3600.0,  # 1 hora
    SemanticMemoryType.EPISODIC: 30 * 86400.0,  # 30 días
    SemanticMemoryType.TASK: 60 * 86400.0,  # 60 días
    SemanticMemoryType.TECHNICAL: 90 * 86400.0,  # 90 días
    SemanticMemoryType.FACT: 365 * 86400.0,  # 365 días
    SemanticMemoryType.PREFERENCE: None,  # Permanente (sin caducidad por defecto)
}


class RelevanceScorer:
    """Motor de scoring y relevancia con acotamiento de top-k y ordenamiento determinista en empates."""

    def __init__(self, min_threshold: float = 0.3, max_top_k: int = 50) -> None:
        self.min_threshold = max(0.0, float(min_threshold))
        self.max_top_k = max(1, int(max_top_k))

    def score_and_rank(
        self,
        raw_results: list[VectorSearchResult] | tuple[VectorSearchResult, ...],
        top_k: int = 10,
    ) -> list[VectorSearchResult]:
        """Filtra por score mínimo y ordena deterministamente en empates por (-score, -timestamp, doc_id)."""
        bounded_top_k = min(max(1, top_k), self.max_top_k)

        valid_results: list[VectorSearchResult] = []
        for r in raw_results:
            if r.similarity_score >= self.min_threshold:
                valid_results.append(r)

        # Ordenamiento determinista: 1) Score descendente, 2) Timestamp descendente, 3) doc_id ascendente
        def _sort_key(res: VectorSearchResult) -> tuple[float, float, str]:
            ts = res.document.created_at.timestamp() if res.document.created_at else 0.0
            return (-res.similarity_score, -ts, str(res.document.doc_id))

        valid_results.sort(key=_sort_key)
        return valid_results[:bounded_top_k]


@dataclass(frozen=True)
class SemanticMemoryResult:
    """Resultado formal de memoria semántica normalizada y sanitizada."""

    doc_id: str
    content: str
    source: ContextSource = ContextSource.SEMANTIC_MEMORY
    memory_type: SemanticMemoryType = SemanticMemoryType.EPISODIC
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    relevance: float = 0.0
    provenance: dict[str, str] = field(default_factory=dict)


class SemanticMemoryRetriever:
    """Recuperador de Memoria Semántica Vectorial con Pipeline Unidireccional Estricto de Seguridad.

    PIPELINE:
    1. Retrieval (IVectorStore)
    2. Normalization & Relevance Scoring (RelevanceScorer + Retention Policy + Deduplication)
    3. Sanitization (SecretRedactor + OCRTextSanitizer)
    4. ContextSecurityManager (wrap_prompt_injection_safety + sanitize_text)
    5. ContextSnapshot Integration (ContextItem inmutable)
    """

    def __init__(
        self,
        vector_store: IVectorStore | None = None,
        embedding_provider: IEmbeddingProvider | None = None,
        scorer: RelevanceScorer | None = None,
        security_manager: ContextSecurityManager | None = None,
    ) -> None:
        from core.local_vector_store import LocalEmbeddingProvider, LocalVectorStore
        self.vector_store = vector_store or LocalVectorStore()
        self.embedding_provider = embedding_provider or LocalEmbeddingProvider()
        self.scorer = scorer or RelevanceScorer(min_threshold=0.1, max_top_k=50)
        self.security_manager = security_manager or ContextSecurityManager()
        self.sanitizer = OCRTextSanitizer()

    def store_memory_evidence(
        self,
        doc_id: str,
        content: str,
        memory_type: SemanticMemoryType = SemanticMemoryType.EPISODIC,
        metadata: dict[str, Any] | None = None,
    ) -> VectorDocument:
        """Almacena una nueva evidencia de memoria vectorial previa sanitización de secretos.

        REGLA DE SEGURIDAD: Guarda la evidencia pero NUNCA concede autoridad.
        """
        # Sanitizar credenciales y nulos antes de generar embedding
        res_san = self.sanitizer.sanitize_text(content)
        clean_content = res_san[0] if isinstance(res_san, tuple) else res_san

        embedding = self.embedding_provider.generate_embedding(clean_content)

        meta = dict(metadata or {})
        meta["memory_type"] = str(memory_type.value if isinstance(memory_type, SemanticMemoryType) else memory_type)
        meta["doc_id"] = str(doc_id)

        # Sanitizar metadatos malformados o no-string
        clean_meta: dict[str, str] = {}
        for k, v in meta.items():
            safe_k = re.sub(r"[\x00-\x1f]", "", str(k))[:64]
            safe_v = re.sub(r"[\x00-\x1f]", "", str(v))[:256]
            clean_meta[safe_k] = safe_v

        doc = VectorDocument(
            doc_id=doc_id,
            content=clean_content,
            embedding=embedding,
            metadata=clean_meta,
            created_at=datetime.now(UTC),
        )

        self.vector_store.add_document(doc)
        return doc

    def retrieve_semantic_memories(
        self,
        query: str,
        top_k: int = 5,
        min_relevance: float = 0.1,
        allowed_types: set[SemanticMemoryType] | None = None,
        max_age_seconds: float | None = None,
    ) -> tuple[ContextItem, ...]:
        """Ejecuta el Pipeline Completo de Seguridad para obtener ContextItems.

        PIPELINE DE SEGURIDAD:
        retrieval -> normalization -> sanitization -> ContextSecurityManager -> ContextSnapshot
        """
        # 1. RETRIEVAL: Invocación al almacén vectorial
        res_q = self.sanitizer.sanitize_text(query)
        clean_query = res_q[0] if isinstance(res_q, tuple) else res_q

        query_embedding = self.embedding_provider.generate_embedding(clean_query)
        raw_results = self.vector_store.search_similar(query_embedding, top_k=top_k * 2, min_score=min_relevance)

        # 2. NORMALIZATION & RETENTION POLICY & DEDUPLICATION & DETERMINISTIC SCORING
        now = datetime.now(UTC)
        normalized_results: list[VectorSearchResult] = []
        seen_content_hashes: set[str] = set()

        for r in raw_results:
            doc = r.document
            doc_type_str = doc.metadata.get("memory_type", SemanticMemoryType.EPISODIC.value)

            try:
                mem_type = SemanticMemoryType(doc_type_str)
            except ValueError:
                mem_type = SemanticMemoryType.EPISODIC

            # Filtrar por tipos de memoria permitidos
            if allowed_types and mem_type not in allowed_types:
                continue

            # Filtrar por política de retención / caducidad (Stale Memory)
            elapsed = (now - doc.created_at).total_seconds() if doc.created_at else 0.0
            max_allowed_age = max_age_seconds or RETENTION_POLICY_SECONDS.get(mem_type)
            if max_allowed_age is not None and elapsed > max_allowed_age:
                logger.info(f"[SEMANTIC RETRIEVER] Omitiendo memoria obsoleta [{doc.doc_id}] ({elapsed:.0f}s > {max_allowed_age:.0f}s)")
                continue

            # Deduplicación determinista por hash del contenido sanitizado
            content_hash = hashlib.sha256(doc.content.strip().lower().encode("utf-8")).hexdigest()
            if content_hash in seen_content_hashes:
                continue
            seen_content_hashes.add(content_hash)

            normalized_results.append(r)

        # Re-scoring determinista y acotamiento de top-k
        ranked_results = self.scorer.score_and_rank(normalized_results, top_k=top_k)

        # 3. SANITIZATION & 4. CONTEXT SECURITY MANAGER
        context_items: list[ContextItem] = []

        for r in ranked_results:
            doc = r.document
            # Sanitización de secretos
            res_doc = SecretRedactor.redact(doc.content)
            clean_content = res_doc[0] if isinstance(res_doc, tuple) else res_doc

            # Aislamiento contra Prompt Injection y caracteres de control
            safe_content = self.security_manager.wrap_prompt_injection_safety(clean_content)
            safe_key = self.security_manager.sanitize_text(f"vector_match_{doc.doc_id}")

            doc_type_str = doc.metadata.get("memory_type", SemanticMemoryType.EPISODIC.value)
            provenance_info = {
                "doc_id": doc.doc_id,
                "memory_type": doc_type_str,
                "similarity_score": f"{r.similarity_score:.4f}",
                "retrieved_at": now.isoformat(),
            }

            # 5. CONTEXT SNAPSHOT INTEGRATION ITEM
            item = ContextItem(
                item_id=f"sem-{doc.doc_id}",
                source=ContextSource.SEMANTIC_MEMORY,
                key=safe_key,
                content=safe_content,
                priority=3,
                timestamp=doc.created_at,
                metadata=provenance_info,
            )
            context_items.append(item)

        return tuple(context_items)

    def retrieve_context_items(self, query: ContextQuery) -> tuple[ContextItem, ...]:
        """Implementa la interfaz IMemoryRetriever para integración directa con ContextBuilder."""
        search_q = query.semantic_query or ""
        return self.retrieve_semantic_memories(
            query=search_q,
            top_k=query.max_semantic_items,
        )

    def retrieve_memory_evidence(

        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> tuple[VectorSearchResult, ...]:
        """Recupera evidencias de memoria por similitud semántica (vectorial cruda sanitizada).

        REGLA DE SEGURIDAD: Retorna evidencia contextual sanitizada. CERO autoridad de ejecución.
        """
        res_q = self.sanitizer.sanitize_text(query)
        clean_query = res_q[0] if isinstance(res_q, tuple) else res_q

        query_embedding = self.embedding_provider.generate_embedding(clean_query)
        raw_results = self.vector_store.search_similar(query_embedding, top_k=top_k, min_score=min_score)

        sanitized_results: list[VectorSearchResult] = []
        for r in raw_results:
            res_doc = self.sanitizer.sanitize_text(r.document.content)
            san_content = res_doc[0] if isinstance(res_doc, tuple) else res_doc
            san_doc = VectorDocument(
                doc_id=r.document.doc_id,
                content=san_content,
                embedding=r.document.embedding,
                metadata=r.document.metadata,
                created_at=r.document.created_at,
            )
            sanitized_results.append(VectorSearchResult(document=san_doc, similarity_score=r.similarity_score))

        return tuple(sanitized_results)

