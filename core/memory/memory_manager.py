"""Gestor central de memoria multi-agente (memory_manager.py - Fase 12: Multi-Agent Memory).

Orquesta la memoria global, privada por agente, efímera por tarea y semántica con control
estricto de acceso, trazabilidad de procedencia, auditoría y aislamiento concurrente.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. MEMORY != AUTHORIZATION: Las entradas de memoria son evidencia (`EVIDENCE`), jamás autoridad de seguridad.
2. Aislamiento por agente: Búsquedas y lecturas son filtradas en el motor antes de ser entregadas al agente.
3. Thread-safe: Todo acceso y mutación está protegido mediante candados `threading.RLock`.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, ClassVar

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.command_output import SecretRedactor
from core.event_bus import get_event_bus
from core.local_vector_store import (
    LocalEmbeddingProvider,
    compute_cosine_similarity,
)
from core.logger import get_logger
from core.memory.memory_access import (
    MemoryAccessControl,
    MemoryPromotionRequest,
    MemoryShareRequest,
)
from core.memory.memory_entry import MemoryEntry
from core.memory.memory_exceptions import MemoryNotFoundError
from core.memory.memory_policy import MemoryPolicy
from core.memory.memory_provenance import (
    MemoryConfidence,
    MemoryProvenance,
)
from core.memory.memory_scope import MemoryScope
from core.vector_store_models import EmbeddingVector

logger = get_logger("jessyca.memory.manager")


class MemoryManager:
    """Orquestador central singleton thread-safe de la memoria multi-agente de JESSYCA 3.0."""

    _instance: ClassVar[MemoryManager | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        policy: MemoryPolicy | None = None,
        embedding_provider: LocalEmbeddingProvider | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.policy = policy or MemoryPolicy()
        self.access_control = MemoryAccessControl(policy=self.policy)
        self.embedding_provider = embedding_provider or LocalEmbeddingProvider()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

        # Almacenamiento primario en memoria indexado por entry_id
        self._entries: dict[str, MemoryEntry] = {}
        # Índice de vectores para búsqueda semántica: entry_id -> EmbeddingVector
        self._vectors: dict[str, EmbeddingVector] = {}

    @classmethod
    def get_instance(cls) -> MemoryManager:
        """Obtiene la instancia singleton global del MemoryManager."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = MemoryManager()
            return cls._instance

    def reset(self) -> None:
        """Restablece el estado de la memoria para aislamiento de pruebas."""
        with self._lock:
            self._entries.clear()
            self._vectors.clear()

    # ── ESCRITURA Y CREACIÓN ──

    def write_entry(
        self,
        agent_id: str,
        key: str,
        content: str,
        scope: MemoryScope = MemoryScope.AGENT,
        owner: str | None = None,
        provenance: MemoryProvenance | None = None,
        confidence: MemoryConfidence = MemoryConfidence.UNVERIFIED,
        task_id: str | None = None,
        session_id: str | None = None,
        tags: tuple[str, ...] | list[str] = (),
        metadata: dict[str, Any] | None = None,
        index_vector: bool = True,
    ) -> MemoryEntry:
        """Registra una nueva entrada de memoria validando permisos y procedencia."""
        target_owner = owner or agent_id
        clean_key = str(key).strip()
        sanitized_content, _ = SecretRedactor.redact(str(content))

        # 1. Enforzar política de escritura
        try:
            self.access_control.enforce_write(agent_id=agent_id, scope=scope, target_owner=target_owner)
        except Exception as e:
            self._log_audit_denial(
                agent_id=agent_id,
                operation="write_entry",
                reason=str(e),
                metadata={"key": clean_key, "scope": str(scope), "target_owner": target_owner},
            )
            raise

        # 2. Construir procedencia por defecto si no fue suministrada
        if provenance is None:
            if agent_id in ("system", "system_admin", "core"):
                prov = MemoryProvenance.create_for_system()
            elif agent_id in ("user", "interactive_user"):
                prov = MemoryProvenance.create_for_user(user_id=agent_id)
            else:
                prov = MemoryProvenance.create_for_agent(agent_id=agent_id)
        else:
            prov = provenance

        # 3. Crear entrada inmutable
        entry = MemoryEntry.create(
            key=clean_key,
            content=sanitized_content,
            scope=scope,
            owner=target_owner,
            provenance=prov,
            confidence=confidence,
            task_id=task_id,
            session_id=session_id,
            tags=tuple(tags),
            metadata=dict(metadata or {}),
        )

        with self._lock:
            self._entries[entry.entry_id] = entry
            if index_vector:
                try:
                    embed_text = f"{clean_key} {sanitized_content}"
                    self._vectors[entry.entry_id] = self.embedding_provider.generate_embedding(embed_text)
                except Exception as ex:
                    logger.warning(f"[MEMORY VECTOR INDEX WARNING] Falló indexación vectorial para '{entry.entry_id}': {ex}")

        # 4. Auditoría y eventos
        self._log_audit_event(
            event_type=AuditEventType.EXECUTION_SUCCEEDED,
            operation="MEMORY_WRITE",
            agent_id=agent_id,
            entry_id=entry.entry_id,
            metadata={"scope": str(scope), "owner": target_owner, "key": clean_key, "confidence": str(confidence)},
        )
        self.event_bus.publish("memory:entry_written", {"entry_id": entry.entry_id, "agent_id": agent_id, "scope": str(scope)})
        return entry

    # ── LECTURA Y CONSULTA ──

    def read_entry(self, agent_id: str, entry_id: str) -> MemoryEntry:
        """Recupera una entrada por su ID validando aislamiento y permisos de lectura."""
        with self._lock:
            entry = self._entries.get(entry_id)
            if not entry:
                raise MemoryNotFoundError(f"Entrada de memoria no encontrada: '{entry_id}'")

        try:
            self.access_control.enforce_read(agent_id=agent_id, entry=entry)
        except Exception as e:
            self._log_audit_denial(
                agent_id=agent_id,
                operation="read_entry",
                reason=str(e),
                metadata={"entry_id": entry_id, "scope": str(entry.scope), "owner": entry.owner},
            )
            raise

        self._log_audit_event(
            event_type=AuditEventType.EXECUTION_SUCCEEDED,
            operation="MEMORY_READ",
            agent_id=agent_id,
            entry_id=entry.entry_id,
            metadata={"scope": str(entry.scope), "owner": entry.owner},
        )
        return entry

    def get_by_key(
        self,
        agent_id: str,
        key: str,
        scope: MemoryScope | None = None,
        owner: str | None = None,
    ) -> MemoryEntry | None:
        """Busca la entrada más reciente con la clave indicada accesible para el agente."""
        clean_key = str(key).strip()
        candidates: list[MemoryEntry] = []

        with self._lock:
            for entry in self._entries.values():
                if entry.key == clean_key:
                    if scope is not None and entry.scope != scope:
                        continue
                    if owner is not None and entry.owner != owner:
                        continue
                    if self.policy.can_read(agent_id=agent_id, entry=entry):
                        candidates.append(entry)

        if not candidates:
            return None

        # Ordenar por fecha descendente
        candidates.sort(key=lambda e: e.updated_at, reverse=True)
        return candidates[0]

    def list_entries(
        self,
        agent_id: str,
        scope: MemoryScope | None = None,
        owner: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
        tag: str | None = None,
    ) -> list[MemoryEntry]:
        """Lista todas las entradas que el agente tiene permiso para leer."""
        results: list[MemoryEntry] = []

        with self._lock:
            for entry in self._entries.values():
                if scope is not None and entry.scope != scope:
                    continue
                if owner is not None and entry.owner != owner:
                    continue
                if task_id is not None and entry.task_id != task_id:
                    continue
                if session_id is not None and entry.session_id != session_id:
                    continue
                if tag is not None and tag not in entry.tags:
                    continue
                if self.policy.can_read(agent_id=agent_id, entry=entry):
                    results.append(entry)

        results.sort(key=lambda e: e.created_at, reverse=True)
        return results

    # ── ACTUALIZACIÓN Y ELIMINACIÓN ──

    def update_entry(
        self,
        agent_id: str,
        entry_id: str,
        content: str | None = None,
        confidence: MemoryConfidence | None = None,
        metadata_updates: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """Actualiza el contenido o metadatos de una entrada si el agente está autorizado."""
        with self._lock:
            entry = self._entries.get(entry_id)
            if not entry:
                raise MemoryNotFoundError(f"Entrada de memoria no encontrada: '{entry_id}'")

        try:
            self.access_control.enforce_update(agent_id=agent_id, entry=entry)
        except Exception as e:
            self._log_audit_denial(
                agent_id=agent_id,
                operation="update_entry",
                reason=str(e),
                metadata={"entry_id": entry_id},
            )
            raise

        sanitized_content = SecretRedactor.redact(content)[0] if content is not None else None
        updated_entry = entry.with_update(
            content=sanitized_content,
            confidence=confidence,
            metadata_updates=metadata_updates,
        )

        with self._lock:
            self._entries[entry_id] = updated_entry
            if content is not None:
                embed_text = f"{updated_entry.key} {updated_entry.content}"
                self._vectors[entry_id] = self.embedding_provider.generate_embedding(embed_text)

        self._log_audit_event(
            event_type=AuditEventType.EXECUTION_SUCCEEDED,
            operation="MEMORY_UPDATE",
            agent_id=agent_id,
            entry_id=entry_id,
            metadata={"scope": str(updated_entry.scope)},
        )
        return updated_entry

    def delete_entry(self, agent_id: str, entry_id: str) -> None:
        """Elimina una entrada de memoria si el agente posee autorización."""
        with self._lock:
            entry = self._entries.get(entry_id)
            if not entry:
                raise MemoryNotFoundError(f"Entrada de memoria no encontrada: '{entry_id}'")

        try:
            self.access_control.enforce_delete(agent_id=agent_id, entry=entry)
        except Exception as e:
            self._log_audit_denial(
                agent_id=agent_id,
                operation="delete_entry",
                reason=str(e),
                metadata={"entry_id": entry_id},
            )
            raise

        with self._lock:
            self._entries.pop(entry_id, None)
            self._vectors.pop(entry_id, None)

        self._log_audit_event(
            event_type=AuditEventType.EXECUTION_SUCCEEDED,
            operation="MEMORY_DELETE",
            agent_id=agent_id,
            entry_id=entry_id,
            metadata={"scope": str(entry.scope), "owner": entry.owner},
        )

    # ── COMPARTICIÓN Y PROMOCIÓN ──

    def share_entry(self, request: MemoryShareRequest) -> MemoryEntry:
        """Comparte una memoria entre dos agentes creando una copia enlazada en el scope acordado."""
        with self._lock:
            entry = self._entries.get(request.entry_id)
            if not entry:
                raise MemoryNotFoundError(f"Entrada de memoria no encontrada: '{request.entry_id}'")

        try:
            self.access_control.enforce_share(request=request, entry=entry)
        except Exception as e:
            self._log_audit_denial(
                agent_id=request.sender_agent_id,
                operation="share_entry",
                reason=str(e),
                metadata=request.to_dict(),
            )
            raise

        shared_meta = dict(entry.metadata)
        shared_meta["shared_from_entry_id"] = entry.entry_id
        shared_meta["shared_by_agent"] = request.sender_agent_id
        shared_meta["share_reason"] = request.reason

        shared_entry = self.write_entry(
            agent_id="system",  # Transacción autorizada ejecutada por el mediador
            key=f"{entry.key}_shared",
            content=entry.content,
            scope=request.target_scope,
            owner=request.recipient_agent_id,
            provenance=entry.provenance,
            confidence=entry.confidence,
            tags=(*entry.tags, "shared"),
            metadata=shared_meta,
        )

        self._log_audit_event(
            event_type=AuditEventType.EXECUTION_SUCCEEDED,
            operation="MEMORY_SHARE",
            agent_id=request.sender_agent_id,
            entry_id=shared_entry.entry_id,
            metadata=request.to_dict(),
        )
        return shared_entry

    def promote_entry(self, request: MemoryPromotionRequest) -> MemoryEntry:
        """Promueve formalmente el nivel de confianza de una memoria tras verificar su evidencia."""
        with self._lock:
            entry = self._entries.get(request.entry_id)
            if not entry:
                raise MemoryNotFoundError(f"Entrada de memoria no encontrada: '{request.entry_id}'")

        try:
            self.access_control.enforce_promotion(request=request, entry=entry)
        except Exception as e:
            self._log_audit_denial(
                agent_id=request.requested_by,
                operation="promote_entry",
                reason=str(e),
                metadata=request.to_dict(),
            )
            raise

        promoted_entry = entry.with_promoted_confidence(
            new_confidence=request.target_confidence,
            verifier_id=request.verifier_id,
            verifier_source=request.verifier_source,
            evidence=request.evidence,
        )

        with self._lock:
            self._entries[entry.entry_id] = promoted_entry

        self._log_audit_event(
            event_type=AuditEventType.EXECUTION_SUCCEEDED,
            operation="MEMORY_PROMOTION",
            agent_id=request.requested_by,
            entry_id=entry.entry_id,
            metadata=request.to_dict(),
        )
        return promoted_entry

    # ── BÚSQUEDA SEMÁNTICA VECTORIAL CON AISLAMIENTO DE SCOPE ──

    def search_semantic(
        self,
        agent_id: str,
        query_text: str,
        top_k: int = 5,
        min_threshold: float | None = None,
        filter_scope: MemoryScope | None = None,
        filter_owner: str | None = None,
    ) -> list[tuple[MemoryEntry, float]]:
        """Realiza búsqueda semántica vectorial aplicando filtro PRE-ENTREGA por permisos del agente."""
        query_clean, _ = SecretRedactor.redact(str(query_text).strip())
        query_vector = self.embedding_provider.generate_embedding(query_clean)

        candidates: list[tuple[MemoryEntry, float]] = []

        with self._lock:
            for entry_id, doc_vector in self._vectors.items():
                entry = self._entries.get(entry_id)
                if not entry:
                    continue

                # 1. Filtros explícitos de consulta
                if filter_scope is not None and entry.scope != filter_scope:
                    continue
                if filter_owner is not None and entry.owner != filter_owner:
                    continue

                # 2. FILTRO CRÍTICO DE SEGURIDAD: ¿El agente solicitante puede leer este documento?
                if not self.policy.can_read(agent_id=agent_id, entry=entry):
                    continue

                # 3. Similitud de coseno
                sim = compute_cosine_similarity(query_vector.values, doc_vector.values)
                if min_threshold is not None and sim < min_threshold:
                    continue
                candidates.append((entry, sim))

        # Ordenar por similitud descendente
        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates[:top_k]

    # ── MÉTODOS INTERNOS DE AUDITORÍA ──

    def _log_audit_event(
        self,
        event_type: AuditEventType,
        operation: str,
        agent_id: str,
        entry_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        meta = {
            "agent_id": agent_id,
            "entry_id": entry_id,
            **(metadata or {}),
        }
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=event_type,
                request_id=f"mem-{uuid.uuid4().hex[:8]}",
                tool_name="system.memory_manager",
                operation=operation,
                duration_ms=0.0,
                reason=f"Operación de memoria '{operation}' ejecutada por '{agent_id}'.",
                metadata=meta,
            )
        )

    def _log_audit_denial(
        self,
        agent_id: str,
        operation: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        meta = {
            "agent_id": agent_id,
            "blocked_operation": operation,
            "reason": reason,
            **(metadata or {}),
        }
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.SECURITY_ALERT,
                request_id=f"mem-deny-{uuid.uuid4().hex[:8]}",
                tool_name="system.memory_manager",
                operation="MEMORY_DENIED",
                duration_ms=0.0,
                reason=reason,
                metadata=meta,
            )
        )


def get_memory_manager() -> MemoryManager:
    """Acceso helper al singleton global de MemoryManager."""
    return MemoryManager.get_instance()
