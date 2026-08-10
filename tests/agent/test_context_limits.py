"""Pruebas de enforzamiento de límites de tamaño y cantidad de elementos en ContextSnapshot (Subetapa 10.2)."""

from __future__ import annotations

import pytest

from core.context_builder import ContextBuilder
from core.context_models import ContextQuery
from core.context_security import ContextLimitExceededError
from core.memory_retriever import SessionMemoryRetriever
from core.session_manager import SessionManager
from core.session_models import SessionRole
from core.session_store import InMemorySessionStore


def test_context_builder_truncates_large_context() -> None:
    store = InMemorySessionStore()
    sm = SessionManager(store=store)
    sm.create_session(user_id="user1", session_id="lim-ctx-1")

    for i in range(10):
        sm.append_message("lim-ctx-1", SessionRole.USER, f"Mensaje largo de prueba {i} " * 20)

    retriever = SessionMemoryRetriever(session_manager=sm)
    builder = ContextBuilder(retriever=retriever)

    # Solicitar tamaño muy pequeño para forzar truncamiento
    query = ContextQuery(session_id="lim-ctx-1", max_total_size=500)
    snap = builder.build_context_snapshot(query)

    assert snap.metadata.truncated is True


def test_context_builder_rejects_excessive_requested_limits() -> None:
    builder = ContextBuilder()

    # Pedir max_messages que excede el máximo permitido en configuración
    with pytest.raises(ContextLimitExceededError):
        query = ContextQuery(session_id="s1", max_messages=10000)
        builder.build_context_snapshot(query)
