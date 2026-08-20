"""Pruebas de los modelos inmutables de sesión y memoria (Subetapa 10.1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.session_models import (
    SessionFact,
    SessionId,
    SessionMetadata,
    SessionState,
    SessionStatus,
)


def test_session_id_validation_and_immutability() -> None:
    sid = SessionId(value="test-session-123")
    assert str(sid) == "test-session-123"

    with pytest.raises(ValueError):
        SessionId(value="")

    with pytest.raises(ValueError):
        SessionId(value="   ")

    with pytest.raises(AttributeError):
        sid.value = "new-value"  # type: ignore


def test_session_fact_confidence_range() -> None:
    now = datetime.now(UTC)
    fact = SessionFact(
        fact_id="f-1",
        key="browser",
        value="Chrome",
        confidence=0.9,
        timestamp=now,
    )
    assert fact.confidence == 0.9

    with pytest.raises(ValueError):
        SessionFact(fact_id="f-2", key="k", value="v", confidence=1.5, timestamp=now)

    with pytest.raises(ValueError):
        SessionFact(fact_id="f-3", key="k", value="v", confidence=-0.1, timestamp=now)


def test_session_state_immutability_and_dict() -> None:
    now = datetime.now(UTC)
    sid = SessionId(value="s-1")
    meta = SessionMetadata(user_id="u-1", client_id="c-1", client_version="3.0")

    state = SessionState(
        session_id=sid,
        status=SessionStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        messages=(),
        facts=(),
        preferences=(),
        metadata=meta,
    )

    assert state.status == SessionStatus.ACTIVE
    d = state.to_dict()
    assert d["session_id"] == "s-1"
    assert d["status"] == "ACTIVE"

    with pytest.raises(AttributeError):
        state.status = SessionStatus.PAUSED  # type: ignore
