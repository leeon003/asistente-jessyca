"""Prueba de privacidad e integridad de auditoría sin filtración de mensajes o hechos crudos (Subetapa 10.1)."""

from __future__ import annotations

from core.audit_logger import MemoryAuditSink
from core.session_manager import SessionManager
from core.session_models import SessionRole
from core.session_store import InMemorySessionStore


def test_session_audit_metadata_only_no_raw_data_leak() -> None:
    mem_sink = MemoryAuditSink()
    store = InMemorySessionStore()
    manager = SessionManager(store=store)
    manager.audit_logger.add_sink(mem_sink)

    state = manager.create_session(user_id="alice", session_id="priv-session-100")
    manager.append_message("priv-session-100", SessionRole.USER, "Secret Message: Password123!")
    manager.add_fact("priv-session-100", "secret_key", "secret_value", 1.0)

    events = mem_sink.get_events(tool_name="system.session")
    assert len(events) >= 2

    sensitive_tokens = ["Password123!", "secret_value", "priv-session-100"]

    for ev in events:
        meta_str = str(ev.metadata)
        for token in sensitive_tokens:
            assert token not in meta_str, f"Token sensible '{token}' encontrado en metadata de auditoría: {meta_str}"

        # Verificar que se utilice un hash anónimo del session_id
        assert "session_id_hash" in ev.metadata
