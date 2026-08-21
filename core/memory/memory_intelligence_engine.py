"""Motor Orquestador de Inteligencia de Memoria (memory_intelligence_engine.py - Fase 21: Memory Intelligence).

Orquesta el pipeline integral:
STORE -> INDEX -> RETRIEVE -> RANK -> VALIDATE -> CONTEXT

INVARIANTE DE SEGURIDAD ABSOLUTA:
MEMORY != AUTHORIZATION
La memoria provee contexto y evidencia (EVIDENCE) a los agentes pero jamás sustituye al SecurityPipeline
ni otorga autoridad para ejecutar herramientas o modificar políticas.
"""

from __future__ import annotations

from typing import Any, ClassVar

from core.logger import get_logger
from core.memory.contradiction_detector import ContradictionDetector
from core.memory.memory_entry import MemoryEntry
from core.memory.memory_expiration import MemoryExpirationManager
from core.memory.memory_intelligence_models import (
    ContradictionReport,
    ContradictionResolution,
    MemoryContextBundle,
    RankedMemoryItem,
)
from core.memory.memory_manager import MemoryManager
from core.memory.memory_provenance import (
    MemoryConfidence,
    MemoryProvenance,
)
from core.memory.memory_ranker import MemoryRanker
from core.memory.memory_scope import MemoryScope

logger = get_logger("jessyca.memory.intelligence_engine")


class MemoryIntelligenceEngine:
    """Motor de orquestación de inteligencia, ranking semántico y gobernanza de memoria."""

    _instance: ClassVar[MemoryIntelligenceEngine | None] = None

    def __init__(
        self,
        memory_manager: MemoryManager | None = None,
        ranker: MemoryRanker | None = None,
        contradiction_detector: ContradictionDetector | None = None,
    ) -> None:
        self.memory_manager = memory_manager or MemoryManager.get_instance()
        self.ranker = ranker or MemoryRanker()
        self.contradiction_detector = contradiction_detector or ContradictionDetector()

    @classmethod
    def get_instance(cls) -> MemoryIntelligenceEngine:
        """Obtiene la instancia singleton global del motor de inteligencia de memoria."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── 1. ALMACENAMIENTO INTELIGENTE Y ACTUALIZACIÓN ──

    def store_with_intelligence(
        self,
        agent_id: str,
        key: str,
        content: str,
        scope: MemoryScope = MemoryScope.AGENT,
        owner: str | None = None,
        provenance: MemoryProvenance | None = None,
        confidence: MemoryConfidence = MemoryConfidence.UNVERIFIED,
        ttl_seconds: float | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
        tags: tuple[str, ...] | list[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> tuple[MemoryEntry | None, ContradictionReport]:
        """Almacena una memoria aplicando validación de contradicciones, TTL y deduplicación."""
        target_owner = owner or agent_id
        prov = provenance or (
            MemoryProvenance.create_for_user(user_id=agent_id)
            if agent_id in ("user", "interactive_user")
            else MemoryProvenance.create_for_agent(agent_id=agent_id)
        )

        expires_at = MemoryExpirationManager.calculate_expiration_time(ttl_seconds) if ttl_seconds is not None else None

        # 1. Recuperar entradas existentes para evaluar contradicciones
        existing_entries = self.memory_manager.list_entries(
            agent_id=agent_id,
            scope=scope,
            owner=target_owner,
        )

        # Crear entrada candidata provisional para análisis
        candidate = MemoryEntry.create(
            key=key,
            content=content,
            scope=scope,
            owner=target_owner,
            provenance=prov,
            confidence=confidence,
            expires_at=expires_at,
            task_id=task_id,
            session_id=session_id,
            tags=tags,
            metadata=metadata,
        )

        # 2. Detección de Contradicciones
        report = self.contradiction_detector.detect_contradiction(candidate, existing_entries)

        if report.has_contradiction:
            if report.resolution == ContradictionResolution.REJECTED_UNVERIFIED:
                logger.warning(
                    f"[MEMORY STORE REJECTED] Rechazado intento de sobrescritura no verificada: {report.explanation}"
                )
                return None, report

            if report.resolution == ContradictionResolution.SUPERSEDED and report.existing_entry:
                # Actualización de memoria existente sin duplicación
                logger.info(
                    f"[MEMORY AUTO-UPDATE] Sobrescribiendo memoria '{report.existing_entry.entry_id}' por actualización válida."
                )
                updated = self.memory_manager.update_entry(
                    agent_id=agent_id,
                    entry_id=report.existing_entry.entry_id,
                    content=content,
                    confidence=confidence,
                    metadata_updates={
                        **(metadata or {}),
                        "superseded_previous": True,
                        "updated_reason": report.explanation,
                    },
                )
                return updated, report

        # 3. Almacenamiento estándar si no hay conflicto o es aditivo
        entry = self.memory_manager.write_entry(
            agent_id=agent_id,
            key=key,
            content=content,
            scope=scope,
            owner=target_owner,
            provenance=prov,
            confidence=confidence,
            task_id=task_id,
            session_id=session_id,
            tags=tags,
            metadata=metadata,
        )
        return entry, report

    # ── 2. RECUPERACIÓN, RANKING Y CONTEXTO ──

    def retrieve_and_rank(
        self,
        agent_id: str,
        query_text: str,
        top_k: int = 5,
        min_score: float | None = None,
        filter_scope: MemoryScope | None = None,
        filter_owner: str | None = None,
        increment_access: bool = True,
    ) -> list[RankedMemoryItem]:
        """Ejecuta búsqueda semántica, filtrado de expirados y ranking multidimensional."""
        # 1. Búsqueda semántica con similitud de coseno
        raw_candidates = self.memory_manager.search_semantic(
            agent_id=agent_id,
            query_text=query_text,
            top_k=top_k * 2,  # Recuperar candidatos adicionales para permitir filtrado y re-ranking
            filter_scope=filter_scope,
            filter_owner=filter_owner,
        )

        # 2. Re-ranking multidimensional (Relevancia, Confianza, Procedencia, Recencia, Frecuencia)
        ranked = self.ranker.rank_entries(
            entries_with_similarity=raw_candidates,
            query_text=query_text,
            top_k=top_k,
            min_score=min_score,
        )

        # 3. Registrar acceso si corresponde
        if increment_access:
            for item in ranked:
                try:
                    # Incrementar contador de accesos en la memoria
                    self.memory_manager.update_entry(
                        agent_id=agent_id,
                        entry_id=item.entry.entry_id,
                        metadata_updates={"last_accessed_by": agent_id},
                    )
                except Exception:
                    pass

        return ranked

    def build_context_bundle(
        self,
        agent_id: str,
        query_text: str,
        top_k: int = 5,
        min_score: float | None = None,
        filter_scope: MemoryScope | None = None,
    ) -> MemoryContextBundle:
        """Construye un bundle de contexto enriquecido y formateado para prompts y agentes."""
        ranked_items = self.retrieve_and_rank(
            agent_id=agent_id,
            query_text=query_text,
            top_k=top_k,
            min_score=min_score,
            filter_scope=filter_scope,
        )

        # Formatear contexto estructurado
        context_lines: list[str] = []
        if ranked_items:
            context_lines.append("=== CONTEXTO DE MEMORIA RELEVANTE ===")
            for idx, item in enumerate(ranked_items, start=1):
                e = item.entry
                context_lines.append(
                    f"[{idx}] (Confianza: {e.confidence.value.upper()} | Origen: {e.provenance.source.value.upper()}) "
                    f"{e.key}: {e.content}"
                )
            context_lines.append("=====================================")

        formatted_text = "\n".join(context_lines)

        return MemoryContextBundle(
            query=query_text,
            ranked_items=tuple(ranked_items),
            formatted_context=formatted_text,
            metadata={
                "agent_id": agent_id,
                "items_retrieved": len(ranked_items),
            },
        )

    def purge_expired_memories(self, agent_id: str = "system") -> int:
        """Elimina todas las memorias que han superado su TTL."""
        entries = self.memory_manager.list_entries(agent_id=agent_id)
        expired = MemoryExpirationManager.find_expired(entries)
        count = 0
        for e in expired:
            try:
                self.memory_manager.delete_entry(agent_id=agent_id, entry_id=e.entry_id)
                count += 1
            except Exception as ex:
                logger.warning(f"[PURGE ERROR] Fallo al purgar '{e.entry_id}': {ex}")
        return count
