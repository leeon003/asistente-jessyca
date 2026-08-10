"""Pruebas de IMemoryRetriever, SessionMemoryRetriever y FakeMemoryRetriever (Subetapa 10.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from core.context_models import (
    ContextItem,
    ContextQuery,
    ContextSource,
)
from core.memory_retriever import FakeMemoryRetriever, SessionMemoryRetriever
from core.session_manager import SessionManager
from core.session_models import SessionRole
from core.session_store import InMemorySessionStore


def test_fake_memory_retriever() -> None:
    now = datetime.now(UTC)
    preset = (
        ContextItem(
            item_id="f-1",
            source=ContextSource.FACTS,
            key="k1",
            content="v1",
            priority=3,
            timestamp=now,
            metadata={},
        ),
    )
    retriever = FakeMemoryRetriever(preset_items=preset)
    res = retriever.retrieve_context_items(ContextQuery(session_id="s1"))

    assert len(res) == 1
    assert res[0].key == "k1"


def test_session_memory_retriever_integrates_with_session_manager() -> None:
    store = InMemorySessionStore()
    sm = SessionManager(store=store)

    sm.create_session(user_id="alice", session_id="sm-retriever-1")
    sm.append_message("sm-retriever-1", SessionRole.USER, "Mensaje de prueba")
    sm.add_fact("sm-retriever-1", "fact_key", "fact_val")

    retriever = SessionMemoryRetriever(session_manager=sm)
    items = retriever.retrieve_context_items(ContextQuery(session_id="sm-retriever-1"))

    assert len(items) >= 3  # state + msg + fact
