"""Pruebas de enforzamiento de límites de mensajes, hechos y preferencias de sesión (Subetapa 10.1)."""

from __future__ import annotations

import pytest

from core.session_manager import SessionManager
from core.session_models import SessionRole
from core.session_security import SessionLimitExceededError
from core.session_store import InMemorySessionStore


def test_session_manager_enforces_message_length_limit() -> None:
    store = InMemorySessionStore()
    manager = SessionManager(store=store)
    manager.security_manager.max_msg_len = 20

    manager.create_session(user_id="user1", session_id="lim-1")

    # Mensaje corto permitido
    manager.append_message("lim-1", SessionRole.USER, "Hola")

    # Mensaje excesivo denegado
    with pytest.raises(SessionLimitExceededError):
        manager.append_message("lim-1", SessionRole.USER, "A" * 50)


def test_session_manager_enforces_max_messages_limit() -> None:
    store = InMemorySessionStore()
    manager = SessionManager(store=store)
    manager.security_manager.max_messages = 2

    manager.create_session(user_id="user1", session_id="lim-2")
    manager.append_message("lim-2", SessionRole.USER, "M1")
    manager.append_message("lim-2", SessionRole.ASSISTANT, "M2")

    # Tercer mensaje excede el límite máximo
    with pytest.raises(SessionLimitExceededError):
        manager.append_message("lim-2", SessionRole.USER, "M3")
