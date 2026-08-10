"""Pruebas de concurrencia multi-hilo para SessionManager y SessionStore (Subetapa 10.1)."""

from __future__ import annotations

import concurrent.futures

from core.session_manager import SessionManager
from core.session_models import SessionRole
from core.session_store import InMemorySessionStore


def test_concurrent_session_manager_operations() -> None:
    store = InMemorySessionStore()
    manager = SessionManager(store=store)
    manager.create_session(user_id="shared_user", session_id="conc-session-1")

    def worker(worker_id: int) -> bool:
        try:
            manager.append_message("conc-session-1", SessionRole.USER, f"Message from worker {worker_id}")
            manager.add_fact("conc-session-1", f"key_{worker_id}", f"val_{worker_id}")
            snap = manager.create_snapshot("conc-session-1")
            return snap.message_count >= 1
        except Exception:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
    final_state = manager.get_session("conc-session-1")
    assert len(final_state.messages) == 20
    assert len(final_state.facts) == 20
