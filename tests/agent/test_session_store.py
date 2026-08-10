"""Pruebas de los almacenes InMemorySessionStore y SQLiteSessionStore (Subetapa 10.1)."""

from __future__ import annotations

from datetime import UTC, datetime
import os
import tempfile
import pytest

from core.session_models import (
    SessionId,
    SessionMetadata,
    SessionState,
    SessionStatus,
)
from core.session_store import InMemorySessionStore, SQLiteSessionStore


def _create_sample_state(sid_str: str) -> SessionState:
    now = datetime.now(UTC)
    return SessionState(
        session_id=SessionId(value=sid_str),
        status=SessionStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        messages=(),
        facts=(),
        preferences=(),
        metadata=SessionMetadata(user_id="u-1", client_id="c-1", client_version="3.0"),
    )


def test_in_memory_session_store() -> None:
    store = InMemorySessionStore()
    state = _create_sample_state("mem-1")

    store.save_session(state)
    retrieved = store.get_session(SessionId(value="mem-1"))

    assert retrieved is not None
    assert str(retrieved.session_id) == "mem-1"
    assert len(store.list_sessions()) == 1

    deleted = store.delete_session(SessionId(value="mem-1"))
    assert deleted is True
    assert store.get_session(SessionId(value="mem-1")) is None


def test_sqlite_session_store_persistence() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = os.path.join(tmp_dir, "test_sessions.db")
        store = SQLiteSessionStore(db_path=db_file)

        state = _create_sample_state("sql-1")
        store.save_session(state)

        # Nueva instancia de store apuntando al mismo archivo DB
        store2 = SQLiteSessionStore(db_path=db_file)
        retrieved = store2.get_session(SessionId(value="sql-1"))

        assert retrieved is not None
        assert str(retrieved.session_id) == "sql-1"
        assert retrieved.status == SessionStatus.ACTIVE
