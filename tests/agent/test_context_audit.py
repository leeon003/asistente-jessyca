"""Prueba del ciclo de eventos de auditoría del motor de contexto (Subetapa 10.2)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.context_builder import ContextBuilder
from core.context_models import ContextQuery
from core.memory_retriever import SessionMemoryRetriever
from core.session_manager import SessionManager
from core.session_store import InMemorySessionStore


def test_context_audit_event_sequence() -> None:
    sink = MemoryAuditSink()
    store = InMemorySessionStore()
    sm = SessionManager(store=store)
    sm.create_session(user_id="user_aud_1", session_id="aud-ctx-1")

    retriever = SessionMemoryRetriever(session_manager=sm)
    builder = ContextBuilder(retriever=retriever)
    builder.audit_logger.add_sink(sink)

    snap = builder.build_context_snapshot(ContextQuery(session_id="aud-ctx-1"))
    assert snap is not None

    events = sink.get_events(tool_name="system.context")
    event_types = [e.event_type for e in events]

    assert AuditEventType.CONTEXT_BUILT in event_types
