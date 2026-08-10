"""Almacenamiento persistente y desacoplado de sesiones de usuario (SessionStore - Subetapa 10.1).

GARANTÍA ABSOLUTA DE SEGURIDAD Y CONCURRENCIA:
Protocolo abstracto ISessionStore. Implementaciones InMemorySessionStore (con RLock thread-safe)
y SQLiteSessionStore (con persistencia SQLite parametrizada sin dependencias externas).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Protocol

from core.logger import get_logger
from core.session_models import (
    SessionFact,
    SessionId,
    SessionMessage,
    SessionMetadata,
    SessionPreference,
    SessionRole,
    SessionState,
    SessionStatus,
)

logger = get_logger("jessyca.core.session_store")


class ISessionStore(Protocol):
    """Protocolo abstracto para el almacenamiento y persistencia de estados de sesión."""

    def save_session(self, state: SessionState) -> None:
        """Guarda o actualiza el estado de una sesión."""
        ...

    def get_session(self, session_id: SessionId) -> SessionState | None:
        """Recupera el estado de una sesión por su SessionId."""
        ...

    def delete_session(self, session_id: SessionId) -> bool:
        """Elimina una sesión almacenada."""
        ...

    def list_sessions(self) -> tuple[SessionId, ...]:
        """Lista los identificadores de todas las sesiones registradas."""
        ...


class InMemorySessionStore:
    """Almacenamiento en memoria thread-safe para sesiones de usuario."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: dict[str, SessionState] = {}

    def save_session(self, state: SessionState) -> None:
        with self._lock:
            self._store[str(state.session_id)] = state

    def get_session(self, session_id: SessionId) -> SessionState | None:
        with self._lock:
            return self._store.get(str(session_id))

    def delete_session(self, session_id: SessionId) -> bool:
        with self._lock:
            sid = str(session_id)
            if sid in self._store:
                del self._store[sid]
                return True
            return False

    def list_sessions(self) -> tuple[SessionId, ...]:
        with self._lock:
            return tuple(SessionId(value=k) for k in self._store.keys())


class SQLiteSessionStore:
    """Almacenamiento persistente en base de datos SQLite con seguridad thread-safe."""

    def __init__(self, db_path: str | None = None) -> None:
        from config.settings import AppSettings
        settings = AppSettings()

        self.db_path = db_path or settings.SESSION_SQLITE_PATH
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        payload TEXT NOT NULL
                    );
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def save_session(self, state: SessionState) -> None:
        sid = str(state.session_id)
        payload_json = json.dumps(state.to_dict())

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO sessions (session_id, status, created_at, updated_at, payload)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        status = excluded.status,
                        updated_at = excluded.updated_at,
                        payload = excluded.payload;
                    """,
                    (
                        sid,
                        str(state.status),
                        state.created_at.isoformat(),
                        state.updated_at.isoformat(),
                        payload_json,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get_session(self, session_id: SessionId) -> SessionState | None:
        sid = str(session_id)
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT payload FROM sessions WHERE session_id = ?;", (sid,))
                row = cursor.fetchone()
                if not row:
                    return None

                d = json.loads(row[0])
                return self._deserialize_session_state(d)
            finally:
                conn.close()

    def delete_session(self, session_id: SessionId) -> bool:
        sid = str(session_id)
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sessions WHERE session_id = ?;", (sid,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def list_sessions(self) -> tuple[SessionId, ...]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT session_id FROM sessions;")
                rows = cursor.fetchall()
                return tuple(SessionId(value=r[0]) for r in rows)
            finally:
                conn.close()


    def _deserialize_session_state(self, d: dict[str, Any]) -> SessionState:
        """Reconstruye el objeto inmutable SessionState a partir del diccionario serializado."""
        sid = SessionId(value=d["session_id"])
        status = SessionStatus(d["status"])
        created_at = datetime.fromisoformat(d["created_at"])
        updated_at = datetime.fromisoformat(d["updated_at"])

        messages = tuple(
            SessionMessage(
                message_id=m["message_id"],
                role=SessionRole(m["role"]),
                content=m["content"],
                timestamp=datetime.fromisoformat(m["timestamp"]),
            )
            for m in d.get("messages", [])
        )

        facts = tuple(
            SessionFact(
                fact_id=f["fact_id"],
                key=f["key"],
                value=f["value"],
                confidence=float(f["confidence"]),
                timestamp=datetime.fromisoformat(f["timestamp"]),
            )
            for f in d.get("facts", [])
        )

        preferences = tuple(
            SessionPreference(
                preference_id=p["preference_id"],
                key=p["key"],
                value=p["value"],
                timestamp=datetime.fromisoformat(p["timestamp"]),
            )
            for p in d.get("preferences", [])
        )

        meta_dict = d.get("metadata", {})
        metadata = SessionMetadata(
            user_id=meta_dict.get("user_id", "unknown_user"),
            client_id=meta_dict.get("client_id", "desktop_client"),
            client_version=meta_dict.get("client_version", "3.0"),
            ip_address_hash=meta_dict.get("ip_address_hash"),
        )

        return SessionState(
            session_id=sid,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            messages=messages,
            facts=facts,
            preferences=preferences,
            metadata=metadata,
            current_task_id=d.get("current_task_id"),
        )
