"""Pruebas de retención, eliminación y consolidación de memoria (Subetapa 12.3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.audit_logger import MemoryAuditSink, get_audit_logger
from core.local_vector_store import LocalVectorStore
from core.memory_consolidation import (
    MemoryCompactionPolicy,
    MemoryRetentionPolicy,
    RetentionDecision,
    SessionConsolidator,
)
from core.semantic_retriever import SemanticMemoryType
from core.session_manager import SessionManager
from core.session_models import SessionRole
from core.session_store import InMemorySessionStore


def test_memory_retention_policy_rules() -> None:
    policy = MemoryRetentionPolicy(min_session_age_days=7)
    now = datetime.now(UTC)

    # 1. PREFERENCE -> Siempre KEEP
    pref_decision = policy.evaluate_retention(
        memory_type=SemanticMemoryType.PREFERENCE,
        created_at=now - timedelta(days=100),
    )
    assert pref_decision == RetentionDecision.KEEP

    # 2. FACT verificado -> KEEP
    fact_keep = policy.evaluate_retention(
        memory_type=SemanticMemoryType.FACT,
        created_at=now - timedelta(days=50),
        confidence=0.9,
    )
    assert fact_keep == RetentionDecision.KEEP

    # 3. FACT no verificado y antiguo -> EXPIRE_DELETE
    fact_expire = policy.evaluate_retention(
        memory_type=SemanticMemoryType.FACT,
        created_at=now - timedelta(days=100),
        confidence=0.5,
    )
    assert fact_expire == RetentionDecision.EXPIRE_DELETE

    # 4. EPISODIC con 10 días de antigüedad -> COMPACT_RESUME
    episodic_compact = policy.evaluate_retention(
        memory_type=SemanticMemoryType.EPISODIC,
        created_at=now - timedelta(days=10),
    )
    assert episodic_compact == RetentionDecision.COMPACT_RESUME

    # 5. TEMPORARY caducada (2 horas) -> EXPIRE_DELETE
    temp_expire = policy.evaluate_retention(
        memory_type=SemanticMemoryType.TEMPORARY,
        created_at=now - timedelta(hours=2),
    )
    assert temp_expire == RetentionDecision.EXPIRE_DELETE


def test_active_user_deletion_requires_confirmation() -> None:
    policy = MemoryRetentionPolicy(min_session_age_days=7)
    now = datetime.now(UTC)

    # Eliminación activa de PREFERENCE o FACT exige confirmación del usuario
    del_pref = policy.evaluate_retention(
        memory_type=SemanticMemoryType.PREFERENCE,
        created_at=now,
        is_active_user_deletion=True,
    )
    assert del_pref == RetentionDecision.REQUIRES_CONFIRMATION

    del_fact = policy.evaluate_retention(
        memory_type=SemanticMemoryType.FACT,
        created_at=now,
        is_active_user_deletion=True,
    )
    assert del_fact == RetentionDecision.REQUIRES_CONFIRMATION

    # Eliminación activa de TEMPORARY procede directo
    del_temp = policy.evaluate_retention(
        memory_type=SemanticMemoryType.TEMPORARY,
        created_at=now,
        is_active_user_deletion=True,
    )
    assert del_temp == RetentionDecision.EXPIRE_DELETE


def test_memory_compaction_policy() -> None:
    compactor = MemoryCompactionPolicy()
    session_store = InMemorySessionStore()
    sm = SessionManager(store=session_store)

    sm.create_session(user_id="user1", session_id="old-sess-1")
    sm.append_message("old-sess-1", SessionRole.USER, "Configurar base de datos en puerto 5432")
    sm.append_message("old-sess-1", SessionRole.ASSISTANT, "Base de datos PostgreSQL configurada.")

    state = sm.get_session("old-sess-1")
    facts = compactor.compact_session_messages(state.messages)

    assert len(facts) == 1
    assert facts[0].key == "episodic_summary"
    assert "PostgreSQL" in facts[0].value or "Configurar" in facts[0].value


def test_session_consolidator_background_execution() -> None:
    session_store = InMemorySessionStore()
    sm = SessionManager(store=session_store)
    vector_store = LocalVectorStore()

    # Crear una sesión antigua de hace 10 días
    old_time = datetime.now(UTC) - timedelta(days=10)
    sm.create_session(user_id="old_user", session_id="bg-sess-100")
    sm.append_message("bg-sess-100", SessionRole.USER, "Mensaje antiguo para compactar")


    # Ajustar fecha de creación para simular antigüedad
    old_state = sm.get_session("bg-sess-100")
    from core.session_models import SessionState
    fake_old_state = SessionState(
        session_id=old_state.session_id,
        status=old_state.status,
        created_at=old_time,
        updated_at=old_time,
        messages=old_state.messages,
        facts=old_state.facts,
        preferences=old_state.preferences,
        metadata=old_state.metadata,
        current_task_id=old_state.current_task_id,
    )
    session_store.save_session(fake_old_state)

    consolidator = SessionConsolidator(
        session_store=session_store,
        vector_store=vector_store,
        retention_policy=MemoryRetentionPolicy(min_session_age_days=7),
    )

    # Iniciar consolidación en hilo background
    thread = consolidator.run_consolidation_background()
    thread.join(timeout=5.0)
    assert not thread.is_alive()

    # Verificar que los mensajes fueron compactados en un fact sintetizado
    updated_state = sm.get_session("bg-sess-100")
    assert len(updated_state.messages) == 0
    assert len(updated_state.facts) >= 1


def test_session_consolidator_audit_metrics_only() -> None:
    mem_sink = MemoryAuditSink()
    audit_logger = get_audit_logger()
    audit_logger.add_sink(mem_sink)

    session_store = InMemorySessionStore()
    vector_store = LocalVectorStore()

    consolidator = SessionConsolidator(
        session_store=session_store,
        vector_store=vector_store,
    )

    report = consolidator.run_consolidation()
    assert report.status == "SUCCESS"

    # Verificar los registros de auditoría
    events = mem_sink.get_events()
    consolidate_events = [e for e in events if e.operation == "consolidate_memories"]

    assert len(consolidate_events) >= 1
    meta = consolidate_events[0].metadata

    # Registrar EXCLUSIVAMENTE métricas
    assert "sessions_scanned" in meta
    assert "sessions_compacted" in meta
    assert "bytes_reclaimed" in meta
    assert "duration_ms" in meta

    # CERO contenido de texto crudo en los logs
    meta_str = str(meta).lower()
    assert "mensaje" not in meta_str
    assert "secret" not in meta_str
