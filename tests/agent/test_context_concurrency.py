"""Pruebas de concurrencia multi-hilo para ContextBuilder (Subetapa 10.2)."""

from __future__ import annotations

import concurrent.futures

from core.context_builder import ContextBuilder
from core.context_models import ContextQuery
from core.memory_retriever import SessionMemoryRetriever
from core.session_manager import SessionManager
from core.session_models import SessionRole
from core.session_store import InMemorySessionStore


def test_concurrent_context_builder_operations() -> None:
    store = InMemorySessionStore()
    sm = SessionManager(store=store)
    sm.create_session(user_id="alice", session_id="conc-ctx-1")

    for i in range(10):
        sm.append_message("conc-ctx-1", SessionRole.USER, f"Mensaje concurrent {i}")
        sm.add_fact("conc-ctx-1", f"key_{i}", f"val_{i}")

    retriever = SessionMemoryRetriever(session_manager=sm)
    builder = ContextBuilder(retriever=retriever)

    def worker(worker_id: int) -> bool:
        try:
            q = ContextQuery(session_id="conc-ctx-1")
            snap = builder.build_context_snapshot(q)
            return snap.metadata.total_items >= 5
        except Exception:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
