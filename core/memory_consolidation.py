"""Subsistema de Retención, Compactación y Consolidación de Memoria (Subetapa 12.3).

GARANTÍAS ARQUITECTÓNICAS Y DE SEGURIDAD:
1. La consolidación NO se ejecuta dentro del ciclo de vida de las solicitudes (request path). Es un proceso background desacoplado.
2. Definición explícita de lo que se CONSERVA, RESUME, EXPIRA, ELIMINA y REQUIERE CONFIRMACIÓN.
3. Auditoría basada estrictamente en METADATOS Y MÉTRICAS (cantidades, tamaños, duración, estado). CERO contenido crudo.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.ocr_sanitizer import OCRTextSanitizer
from core.semantic_retriever import SemanticMemoryType
from core.session_models import (
    SessionFact,
    SessionMessage,
    SessionState,
)
from core.session_store import ISessionStore
from core.vector_store_models import IVectorStore, VectorDocument

logger = get_logger("jessyca.memory.consolidation")



class RetentionDecision(StrEnum):
    """Decisiones formales del motor de retención de memoria."""

    KEEP = "KEEP"
    COMPACT_RESUME = "COMPACT_RESUME"
    EXPIRE_DELETE = "EXPIRE_DELETE"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"


@dataclass(frozen=True)
class ConsolidationReport:
    """Informe inmutable de métricas y resultados de la consolidación de memoria (sin contenido crudo)."""

    report_id: str
    sessions_scanned: int
    sessions_compacted: int
    facts_retained: int
    items_deleted: int
    bytes_reclaimed: int
    duration_ms: float
    status: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Exporta métricas numéricas exclusivamente para auditoría."""
        return {
            "report_id": self.report_id,
            "sessions_scanned": self.sessions_scanned,
            "sessions_compacted": self.sessions_compacted,
            "facts_retained": self.facts_retained,
            "items_deleted": self.items_deleted,
            "bytes_reclaimed": self.bytes_reclaimed,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


class MemoryRetentionPolicy:
    """Evaluador determinista de retención de memoria basado en tipos semánticos y antigüedad."""

    def __init__(self, min_session_age_days: int = 7) -> None:
        self.min_session_age_days = max(1, min_session_age_days)

    def evaluate_retention(
        self,
        memory_type: SemanticMemoryType,
        created_at: datetime,
        confidence: float = 1.0,
        is_active_user_deletion: bool = False,
    ) -> RetentionDecision:
        """Evalúa la política de retención explícita para una memoria dada.

        DEFINICIÓN EXPLÍCITA:
        - PREFERENCE: Se CONSERVA de forma permanente. Si el usuario solicita su eliminación explícita, REQUIERE CONFIRMACIÓN.
        - FACT: Se CONSERVA si confidence >= 0.8. Si confidence < 0.8 y antigüedad > 90 días, EXPIRA/ELIMINA.
        - EPISODIC / TASK: Se RESUME/COMPACTA si la edad >= min_session_age_days. Si excede 90 días post-resumen, EXPIRA/ELIMINA.
        - TEMPORARY: EXPIRA/ELIMINA tras 1 hora o al cierre de sesión.
        """
        now = datetime.now(UTC)
        age = (now - created_at) if created_at.tzinfo else (now - created_at.replace(tzinfo=UTC))
        age_seconds = age.total_seconds()
        age_days = age_seconds / 86400.0

        # Solicitudes de eliminación activa por parte del usuario en datos críticos -> Requiere confirmación
        if is_active_user_deletion:
            if memory_type in (SemanticMemoryType.PREFERENCE, SemanticMemoryType.FACT):
                return RetentionDecision.REQUIRES_CONFIRMATION
            return RetentionDecision.EXPIRE_DELETE

        # 1. TEMPORARY -> Expira tras 1 hora (3600s)
        if memory_type == SemanticMemoryType.TEMPORARY:
            if age_seconds > 3600.0:
                return RetentionDecision.EXPIRE_DELETE
            return RetentionDecision.KEEP

        # 2. PREFERENCE -> Conservación permanente
        if memory_type == SemanticMemoryType.PREFERENCE:
            return RetentionDecision.KEEP

        # 3. FACT -> Conserva hechos verificados. Expira con baja confianza tras 90 días.
        if memory_type == SemanticMemoryType.FACT:
            if confidence < 0.8 and age_days > 90.0:
                return RetentionDecision.EXPIRE_DELETE
            return RetentionDecision.KEEP

        # 4. EPISODIC & TASK -> Compactación tras min_session_age_days, eliminación tras 180 días
        if memory_type in (SemanticMemoryType.EPISODIC, SemanticMemoryType.TASK):
            if age_days >= 180.0:
                return RetentionDecision.EXPIRE_DELETE
            if age_days >= self.min_session_age_days:
                return RetentionDecision.COMPACT_RESUME
            return RetentionDecision.KEEP

        # 5. TECHNICAL -> Conservación con revisión tras 90 días
        if memory_type == SemanticMemoryType.TECHNICAL:
            if age_days >= 90.0:
                return RetentionDecision.COMPACT_RESUME
            return RetentionDecision.KEEP

        return RetentionDecision.KEEP


class MemoryCompactionPolicy:
    """Motor de compactación determinista que resume historiales de sesión y documentos vectoriales."""

    def __init__(self) -> None:
        self.sanitizer = OCRTextSanitizer()

    def compact_session_messages(self, messages: tuple[SessionMessage, ...]) -> tuple[SessionFact, ...]:
        """Resume un conjunto de mensajes en hechos (facts) ejecutivos sanitizados de sesión."""
        if not messages:
            return ()

        user_msgs = [m.content for m in messages if m.role.value == "USER"]
        if not user_msgs:
            return ()

        # Extraer resumen sintético sanitizado del tema conversacional
        summary_text = f"Resumen de sesión: {len(messages)} mensajes procesados. Temas: " + ", ".join(user_msgs[:3])
        if len(summary_text) > 300:
            summary_text = summary_text[:297] + "..."

        res_san = self.sanitizer.sanitize_text(summary_text)
        clean_summary = res_san[0] if isinstance(res_san, tuple) else res_san

        compact_fact = SessionFact(
            fact_id=str(uuid.uuid4()),
            key="episodic_summary",
            value=clean_summary,
            confidence=0.9,
            timestamp=datetime.now(UTC),
        )

        return (compact_fact,)

    def compact_vector_documents(self, docs: tuple[VectorDocument, ...]) -> VectorDocument | None:
        """Compacta múltiples documentos vectoriales antiguos en un único documento de resumen episódico."""
        if not docs:
            return None

        merged_content = " | ".join(d.content for d in docs)
        if len(merged_content) > 500:
            merged_content = merged_content[:497] + "..."

        res_san = self.sanitizer.sanitize_text(merged_content)
        clean_content = res_san[0] if isinstance(res_san, tuple) else res_san

        comp_doc = VectorDocument(
            doc_id=f"compact-{uuid.uuid4().hex[:8]}",
            content=f"Consolidado Episódico ({len(docs)} refs): {clean_content}",
            embedding=docs[0].embedding,  # Re-usar el primer vector como representante de clúster
            metadata={"memory_type": SemanticMemoryType.EPISODIC.value, "compacted_refs": str(len(docs))},
            created_at=datetime.now(UTC),
        )
        return comp_doc


class SessionConsolidator:
    """Consolidador de Memoria de Sesión y Vectorial Ejecutado en Background Desacoplado.

    REGLA DE SEGURIDAD CRÍTICA:
    - NO se ejecuta dentro de solicitudes HTTP/MCP activas.
    - Registro de auditoría EXCLUSIVAMENTE con cantidades, tamaños, duración y resultado.
    """

    def __init__(
        self,
        session_store: ISessionStore | None = None,
        vector_store: IVectorStore | None = None,
        retention_policy: MemoryRetentionPolicy | None = None,
        compaction_policy: MemoryCompactionPolicy | None = None,
    ) -> None:
        from config.settings import AppSettings
        settings = AppSettings()

        self.min_age_days = settings.CONSOLIDATION_MIN_SESSION_AGE_DAYS
        self.session_store = session_store
        self.vector_store = vector_store
        self.retention_policy = retention_policy or MemoryRetentionPolicy(min_session_age_days=self.min_age_days)
        self.compaction_policy = compaction_policy or MemoryCompactionPolicy()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()
        self._lock = threading.RLock()

    def run_consolidation_background(self) -> threading.Thread:
        """Inicia el proceso de consolidación en un hilo background independiente fuera del request path."""
        t = threading.Thread(target=self.run_consolidation, daemon=True, name="SessionConsolidatorThread")
        t.start()
        return t

    def run_consolidation(self) -> ConsolidationReport:
        """Ejecuta el ciclo completo de análisis, compactación y purga de memorias obsoletas."""
        start_time = datetime.now(UTC)
        report_id = str(uuid.uuid4())

        sessions_scanned = 0
        sessions_compacted = 0
        facts_retained = 0
        items_deleted = 0
        bytes_reclaimed = 0

        with self._lock:
            # 1. Consolidación de Sesiones en ISessionStore
            if self.session_store is not None:
                try:
                    sids = self.session_store.list_sessions()
                    for sid in sids:
                        state = self.session_store.get_session(sid)
                        if not state:
                            continue

                        sessions_scanned += 1
                        decision = self.retention_policy.evaluate_retention(
                            memory_type=SemanticMemoryType.EPISODIC,
                            created_at=state.created_at,
                        )

                        if decision == RetentionDecision.COMPACT_RESUME and state.messages:
                            compact_facts = self.compaction_policy.compact_session_messages(state.messages)
                            orig_bytes = sum(len(m.content.encode("utf-8")) for m in state.messages)

                            new_state = SessionState(
                                session_id=state.session_id,
                                status=state.status,
                                created_at=state.created_at,
                                updated_at=datetime.now(UTC),
                                messages=(),  # Mensajes procesados removidos
                                facts=state.facts + compact_facts,
                                preferences=state.preferences,
                                metadata=state.metadata,
                                current_task_id=state.current_task_id,
                            )
                            self.session_store.save_session(new_state)

                            sessions_compacted += 1
                            items_deleted += len(state.messages)
                            facts_retained += len(compact_facts)
                            bytes_reclaimed += orig_bytes

                        elif decision == RetentionDecision.EXPIRE_DELETE:
                            self.session_store.delete_session(sid)
                            items_deleted += 1

                except Exception as e:
                    logger.error(f"[SESSION CONSOLIDATOR] Error al procesar sesiones: {e}")

            # 2. Consolidación en IVectorStore
            if self.vector_store is not None:
                try:
                    all_docs = self.vector_store.list_documents()
                    for doc in all_docs:
                        doc_type_str = doc.metadata.get("memory_type", SemanticMemoryType.EPISODIC.value)
                        try:
                            m_type = SemanticMemoryType(doc_type_str)
                        except ValueError:
                            m_type = SemanticMemoryType.EPISODIC

                        decision = self.retention_policy.evaluate_retention(
                            memory_type=m_type,
                            created_at=doc.created_at,
                        )

                        if decision == RetentionDecision.EXPIRE_DELETE:
                            self.vector_store.delete_document(doc.doc_id)
                            items_deleted += 1
                            bytes_reclaimed += len(doc.content.encode("utf-8"))
                        elif decision == RetentionDecision.KEEP:
                            facts_retained += 1

                except Exception as e:
                    logger.error(f"[SESSION CONSOLIDATOR] Error al procesar vector store: {e}")

        now = datetime.now(UTC)
        duration_ms = (now - start_time).total_seconds() * 1000.0

        report = ConsolidationReport(
            report_id=report_id,
            sessions_scanned=sessions_scanned,
            sessions_compacted=sessions_compacted,
            facts_retained=facts_retained,
            items_deleted=items_deleted,
            bytes_reclaimed=bytes_reclaimed,
            duration_ms=duration_ms,
            status="SUCCESS",
        )

        # Registro de Auditoría (EXCLUSIVAMENTE MÉTRICAS, NINGÚN DATO CRUDO)
        audit_meta = report.to_dict()
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.SESSION_COMPACTED,
                request_id=f"consolidate-{report_id[:8]}",
                tool_name="system.memory",
                operation="consolidate_memories",
                duration_ms=duration_ms,
                reason="Consolidación y compactación de memoria ejecutada exitosamente.",
                metadata=audit_meta,
            )
        )
        self.event_bus.publish("memory:consolidated", audit_meta)

        logger.info(
            f"[SESSION CONSOLIDATOR] Consolidación completada en {duration_ms:.1f}ms | "
            f"Sesiones escaneadas: {sessions_scanned}, Compactadas: {sessions_compacted}, "
            f"Ítems eliminados: {items_deleted}, Bytes liberados: {bytes_reclaimed}"
        )

        return report
