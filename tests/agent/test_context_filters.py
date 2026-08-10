"""Pruebas de filtrado en ContextQuery para ContextBuilder (Subetapa 10.2)."""

from __future__ import annotations

from core.context_builder import ContextBuilder
from core.context_models import ContextQuery
from core.memory_retriever import SessionMemoryRetriever
from core.session_manager import SessionManager
from core.session_models import SessionRole
from core.session_store import InMemorySessionStore


def test_context_builder_applies_query_filters() -> None:
    store = InMemorySessionStore()
    sm = SessionManager(store=store)

    sm.create_session(user_id="alice", session_id="flt-sess-1")
    sm.append_message("flt-sess-1", SessionRole.USER, "Buscando informacion de Linux")
    sm.add_fact("flt-sess-1", "os_preference", "Linux Ubuntu")

    retriever = SessionMemoryRetriever(session_manager=sm)
    builder = ContextBuilder(retriever=retriever)

    query = ContextQuery(session_id="flt-sess-1", query_filter="Linux")
    snap = builder.build_context_snapshot(query)

    assert snap is not None
    assert snap.metadata.total_items >= 2
