"""Prueba del ciclo completo de auditoría para eventos de sesión (Subetapa 10.1)."""

from __future__ import annotations

from core.audit_logger import AuditEventType, MemoryAuditSink
from core.session_manager import SessionManager
from core.session_models import SessionRole
from core.session_store import InMemorySessionStore


def test_session_full_audit_sequence() -> None:
    sink = MemoryAuditSink()
    store = InMemorySessionStore()
    manager = SessionManager(store=store)
    manager.audit_logger.add_sink(sink)

    state = manager.create_session(user_id="user_audit_1", session_id="aud-session-1")
    manager.append_message("aud-session-1", SessionRole.USER, "Test audit message")
    manager.update_status("aud-session-1", str(state.status))

    events = sink.get_events(tool_name="system.session")
    event_types = [e.event_type for e in events]

    assert AuditEventType.SESSION_CREATED in event_types
    assert AuditEventType.SESSION_MESSAGE_ADDED in event_types
