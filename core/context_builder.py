"""Motor orquestador de construcción de contexto y snapshots inmutables (ContextBuilder - Subetapa 10.2).

GARANTÍA ABSOLUTA DE SEGURIDAD Y PRIVACIDAD:
Construcción determinista, acotada y sanitized. Las secciones se agrupan e inmovilizan.
El AuditLogger y EventBus reciben ÚNICAMENTE METADATOS (session_id_hash, total_items, duration_ms).
INVARIANTE CRÍTICO: CERO mensajes crudos, hechos o instrucciones en auditoría. CERO ejecución de herramientas.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.context_models import (
    ContextItem,
    ContextMetadata,
    ContextQuery,
    ContextSection,
    ContextSnapshot,
    ContextSource,
)
from core.context_security import (
    ContextSecurityManager,
)
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.memory_retriever import IMemoryRetriever, SessionMemoryRetriever

logger = get_logger("jessyca.core.context_builder")


class ContextBuilder:
    """Motor de construcción de snapshots de contexto seguro e inmutable."""

    def __init__(
        self,
        retriever: IMemoryRetriever | None = None,
        semantic_retriever: Any | None = None,
        security_manager: ContextSecurityManager | None = None,
    ) -> None:
        self.retriever = retriever or SessionMemoryRetriever()
        self.semantic_retriever = semantic_retriever
        self.security_manager = security_manager or ContextSecurityManager()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def _hash_sid(self, sid_str: str) -> str:
        """Genera un hash SHA-256 anónimo del session_id para trazabilidad segura."""
        return hashlib.sha256(sid_str.encode("utf-8")).hexdigest()[:16]

    def build_context_snapshot(self, query: ContextQuery) -> ContextSnapshot:
        """Construye un ContextSnapshot determinista, aislado, sanitized y acotado. FAIL-SAFE DENY."""
        start_time = datetime.now(UTC)
        query_id = str(uuid.uuid4())
        sid_hash = self._hash_sid(query.session_id)

        # 1. Validación de la consulta (FAIL-SAFE DENY)
        valid_query = self.security_manager.validate_query(query)

        audit_meta = {
            "query_id": query_id,
            "session_id_hash": sid_hash,
            "status": "STARTED",
        }
        self.event_bus.publish("context:retrieval_started", audit_meta)

        # 2. Recuperación de memoria de sesión
        raw_items = list(self.retriever.retrieve_context_items(valid_query))

        # 2b. Recuperación de memoria semántica vectorial (si está habilitada)
        if valid_query.include_semantic_memory and self.semantic_retriever is not None:
            sem_query = valid_query.semantic_query or valid_query.query_filter or ""
            if sem_query:
                try:
                    sem_results = self.semantic_retriever.retrieve_memory_evidence(
                        query=sem_query,
                        top_k=valid_query.max_semantic_items,
                    )
                    for r in sem_results:
                        doc = r.document
                        sem_item = ContextItem(
                            item_id=f"sem-{doc.doc_id}",
                            source=ContextSource.SEMANTIC_MEMORY,
                            key=f"vector_match_{doc.doc_id}",
                            content=doc.content,
                            priority=3,
                            timestamp=doc.created_at,
                            metadata={"similarity_score": f"{r.similarity_score:.4f}", **doc.metadata},
                        )
                        raw_items.append(sem_item)
                except Exception as e:
                    logger.warning(f"[CONTEXT BUILDER] Error al recuperar memoria semántica: {e}")

        # 3. Sanitización, Aislamiento de Prompt-Injection y Redacción de Secretos
        sanitized_items: list[ContextItem] = []
        seen_keys: set[str] = set()

        for item in raw_items:
            key_id = f"{item.source}:{item.key}"
            if key_id in seen_keys:
                continue
            seen_keys.add(key_id)

            safe_content = self.security_manager.wrap_prompt_injection_safety(item.content)
            safe_item = ContextItem(
                item_id=item.item_id,
                source=item.source,
                key=self.security_manager.sanitize_text(item.key),
                content=safe_content,
                priority=item.priority,
                timestamp=item.timestamp,
                metadata=item.metadata,
            )
            sanitized_items.append(safe_item)

        # 4. Ordenamiento por prioridad determinista
        sanitized_items.sort(key=lambda x: (x.priority, x.timestamp))

        # 5. Agrupamiento en Secciones Estructuradas
        sections_map: dict[ContextSource, list[ContextItem]] = {}
        for item in sanitized_items:
            sections_map.setdefault(item.source, []).append(item)

        section_titles = {
            ContextSource.SESSION_STATE: "Estado de Sesión",
            ContextSource.RECENT_MESSAGES: "Mensajes Recientes",
            ContextSource.PREFERENCES: "Preferencias de Usuario",
            ContextSource.FACTS: "Memoria de Hechos (Facts)",
            ContextSource.HISTORICAL_CONTEXT: "Contexto Histórico",
            ContextSource.METADATA: "Metadatos del Entorno",
            ContextSource.SEMANTIC_MEMORY: "Memoria Semántica Vectorial",
        }


        sections_list: list[ContextSection] = []
        total_items_count = 0
        total_size_bytes = 0
        truncated = False

        for source, items in sections_map.items():
            bounded_items: list[ContextItem] = []
            for item in items:
                item_size = len(item.content.encode("utf-8"))
                if total_size_bytes + item_size > valid_query.max_total_size or total_items_count >= self.security_manager.max_items:
                    truncated = True
                    break

                bounded_items.append(item)
                total_size_bytes += item_size
                total_items_count += 1

            if bounded_items:
                sec = ContextSection(
                    section_id=f"sec-{source.value.lower()}",
                    title=section_titles.get(source, str(source)),
                    source=source,
                    items=tuple(bounded_items),
                    priority=bounded_items[0].priority,
                )
                sections_list.append(sec)

        # 6. Construcción de Metadatos y Snapshot Inmutable
        now = datetime.now(UTC)
        duration_ms = (now - start_time).total_seconds() * 1000.0

        ctx_meta = ContextMetadata(
            query_id=query_id,
            session_id_hash=sid_hash,
            created_at=now,
            total_items=total_items_count,
            total_size_bytes=total_size_bytes,
            truncated=truncated,
        )

        snapshot = ContextSnapshot(
            snapshot_id=str(uuid.uuid4()),
            query=valid_query,
            sections=tuple(sections_list),
            metadata=ctx_meta,
        )

        # 7. Auditoría y Publicación de Eventos (METADATOS EXCLUSIVAMENTE)
        audit_event_meta = {
            "query_id": query_id,
            "session_id_hash": sid_hash,
            "total_items": total_items_count,
            "total_size_bytes": total_size_bytes,
            "truncated": truncated,
            "duration_ms": duration_ms,
        }

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.CONTEXT_BUILT,
                request_id=f"ctx-{query_id[:8]}",
                tool_name="system.context",
                operation="build_context_snapshot",
                duration_ms=duration_ms,
                reason="ContextSnapshot construido exitosamente.",
                metadata=audit_event_meta,
            )
        )

        self.event_bus.publish("context:built", audit_event_meta)
        return snapshot
