"""Pruebas de la Invariante de Privacidad de Auditoría para el motor de contexto (Subetapa 10.2)."""

from __future__ import annotations

from core.audit_logger import MemoryAuditSink
from core.context_builder import ContextBuilder
from core.context_models import ContextQuery
from core.memory_retriever import SessionMemoryRetriever
from core.session_manager import SessionManager
from core.session_models import SessionRole
from core.session_store import InMemorySessionStore


def test_context_builder_audit_privacy_no_raw_data_leak() -> None:
    mem_sink = MemoryAuditSink()
    store = InMemorySessionStore()
    sm = SessionManager(store=store)
    sm.create_session(user_id="alice", session_id="priv-ctx-1")
    sm.append_message("priv-ctx-1", SessionRole.USER, "SuperSecretPassword123!")

    retriever = SessionMemoryRetriever(session_manager=sm)
    builder = ContextBuilder(retriever=retriever)
    builder.audit_logger.add_sink(mem_sink)

    query = ContextQuery(session_id="priv-ctx-1")
    snap = builder.build_context_snapshot(query)
    assert snap is not None

    events = mem_sink.get_events(tool_name="system.context")
    assert len(events) >= 1

    sensitive_tokens = ["SuperSecretPassword123!", "priv-ctx-1"]

    for ev in events:
        meta_str = str(ev.metadata)
        for token in sensitive_tokens:
            assert token not in meta_str, f"Token sensible '{token}' encontrado en metadata de auditoría: {meta_str}"

        assert "session_id_hash" in ev.metadata
