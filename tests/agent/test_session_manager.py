"""Pruebas del servicio SessionManager (Subetapa 10.1)."""

from __future__ import annotations

import pytest

from core.session_manager import SessionManager
from core.session_models import SessionRole, SessionStatus
from core.session_security import SessionSecurityError
from core.session_store import InMemorySessionStore


def test_session_manager_lifecycle_and_operations() -> None:
    store = InMemorySessionStore()
    manager = SessionManager(store=store)

    # 1. Crear sesión
    state = manager.create_session(user_id="user_test_1", session_id="sm-session-1")
    assert state.status == SessionStatus.ACTIVE
    assert str(state.session_id) == "sm-session-1"

    # 2. Agregar mensaje
    s2 = manager.append_message("sm-session-1", SessionRole.USER, "Hola Jessyca")
    assert len(s2.messages) == 1
    assert s2.messages[0].content == "Hola Jessyca"

    # 3. Agregar fact y preferencia
    s3 = manager.add_fact("sm-session-1", "editor", "VSCode", 0.95)
    s4 = manager.add_preference("sm-session-1", "theme", "dark")
    assert len(s4.facts) == 1
    assert len(s4.preferences) == 1

    # 4. Crear snapshot
    snap = manager.create_snapshot("sm-session-1")
    assert snap.message_count == 1
    assert snap.fact_count == 1

    # 5. Pausar y Reanudar
    s_paused = manager.pause_session("sm-session-1")
    assert s_paused.status == SessionStatus.PAUSED

    s_active = manager.resume_session("sm-session-1")
    assert s_active.status == SessionStatus.ACTIVE

    # 6. Cancelar sesión
    s_cancelled = manager.cancel_session("sm-session-1")
    assert s_cancelled.status == SessionStatus.CANCELLED

    # Intentar agregar mensaje a sesión cancelada debe fallar
    with pytest.raises(SessionSecurityError):
        manager.append_message("sm-session-1", SessionRole.USER, "Nuevo mensaje")
