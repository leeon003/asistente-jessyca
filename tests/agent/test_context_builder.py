"""Pruebas del motor ContextBuilder (Subetapa 10.2)."""

from __future__ import annotations

from core.context_builder import ContextBuilder
from core.context_models import ContextQuery
from core.memory_retriever import SessionMemoryRetriever
from core.session_manager import SessionManager
from core.session_models import SessionRole
from core.session_store import InMemorySessionStore


def test_context_builder_builds_snapshot() -> None:
    store = InMemorySessionStore()
    sm = SessionManager(store=store)

    sm.create_session(user_id="bob", session_id="cb-sess-1")
    sm.append_message("cb-sess-1", SessionRole.USER, "Hola Jessyca")
    sm.add_fact("cb-sess-1", "user_city", "Madrid")

    retriever = SessionMemoryRetriever(session_manager=sm)
    builder = ContextBuilder(retriever=retriever)

    query = ContextQuery(session_id="cb-sess-1")
    snap = builder.build_context_snapshot(query)

    assert snap is not None
    assert snap.metadata.total_items >= 3
    assert len(snap.sections) >= 2
