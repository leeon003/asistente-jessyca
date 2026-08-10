"""Pruebas de los modelos inmutables de construcción de contexto (Subetapa 10.2)."""

from __future__ import annotations

from datetime import UTC, datetime
import pytest

from core.context_models import (
    ContextItem,
    ContextMetadata,
    ContextQuery,
    ContextSection,
    ContextSnapshot,
    ContextSource,
)


def test_context_query_immutability_and_validation() -> None:
    q = ContextQuery(session_id="ctx-sess-1", max_messages=20)
    assert q.session_id == "ctx-sess-1"
    assert q.max_messages == 20

    with pytest.raises(ValueError):
        ContextQuery(session_id="")

    with pytest.raises(AttributeError):
        q.max_messages = 100  # type: ignore


def test_context_snapshot_immutability_and_dict() -> None:
    now = datetime.now(UTC)
    q = ContextQuery(session_id="ctx-sess-2")
    item = ContextItem(
        item_id="item-1",
        source=ContextSource.SESSION_STATE,
        key="status",
        content="ACTIVE",
        priority=1,
        timestamp=now,
        metadata={},
    )
    sec = ContextSection(
        section_id="sec-1",
        title="State",
        source=ContextSource.SESSION_STATE,
        items=(item,),
        priority=1,
    )
    meta = ContextMetadata(
        query_id="q-1",
        session_id_hash="hash-1",
        created_at=now,
        total_items=1,
        total_size_bytes=100,
        truncated=False,
    )
    snap = ContextSnapshot(
        snapshot_id="snap-1",
        query=q,
        sections=(sec,),
        metadata=meta,
    )

    d = snap.to_dict()
    assert d["snapshot_id"] == "snap-1"
    assert len(d["sections"]) == 1

    with pytest.raises(AttributeError):
        snap.snapshot_id = "new-snap"  # type: ignore
