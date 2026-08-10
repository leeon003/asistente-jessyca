"""Pruebas de enforzamiento de timeout no anulable en ContextBuilder (Subetapa 10.2)."""

from __future__ import annotations

from core.context_builder import ContextBuilder
from core.context_models import ContextQuery
from core.memory_retriever import FakeMemoryRetriever


def test_context_builder_timeout_setting() -> None:
    retriever = FakeMemoryRetriever()
    builder = ContextBuilder(retriever=retriever)

    assert builder.security_manager.timeout > 0.0
    query = ContextQuery(session_id="timeout-sess-1")
    snap = builder.build_context_snapshot(query)
    assert snap is not None
