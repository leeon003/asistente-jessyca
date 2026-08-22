"""Almacén Persistente de Preferencias del Usuario (preference_store.py - Fase 62).

Proporciona persistencia desacoplada y consultas indexadas por categoría y clave:
- IPreferenceStore (protocolo de interfaz)
- InMemoryPreferenceStore (almacén en memoria para tests unitarios)
- SQLitePreferenceStore (almacén persistente local en SQLite con modo WAL)
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Protocol, runtime_checkable

from core.logger import get_logger
from core.personalization.preference_models import (
    PreferenceCategory,
    PreferenceStatus,
    UserPreference,
)
from core.personalization.preference_validator import normalize_preference_key

logger = get_logger("jessyca.personalization.store")


@runtime_checkable
class IPreferenceStore(Protocol):
    """Protocolo de interfaz para el almacenamiento de preferencias de usuario."""

    def save(self, preference: UserPreference) -> None: ...
    def get(self, preference_id: str) -> UserPreference | None: ...
    def get_by_key(self, category: PreferenceCategory | str, key: str) -> list[UserPreference]: ...
    def query(
        self,
        category: PreferenceCategory | str | None = None,
        status: PreferenceStatus | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserPreference]: ...
    def count(
        self,
        category: PreferenceCategory | str | None = None,
        status: PreferenceStatus | str | None = None,
    ) -> int: ...
    def delete(self, preference_id: str) -> bool: ...
    def clear(self) -> None: ...


class InMemoryPreferenceStore:
    """Almacén en memoria thread-safe para preferencias de usuario."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: dict[str, UserPreference] = {}

    def save(self, preference: UserPreference) -> None:
        with self._lock:
            self._store[preference.preference_id] = preference

    def get(self, preference_id: str) -> UserPreference | None:
        with self._lock:
            return self._store.get(preference_id)

    def get_by_key(self, category: PreferenceCategory | str, key: str) -> list[UserPreference]:
        with self._lock:
            cat_val = category.value if isinstance(category, PreferenceCategory) else category
            norm_key = normalize_preference_key(key)

            matches: list[UserPreference] = []
            for pref in self._store.values():
                p_cat = pref.category.value if isinstance(pref.category, PreferenceCategory) else pref.category
                p_key = normalize_preference_key(pref.key)
                if p_cat == cat_val and p_key == norm_key:
                    matches.append(pref)
            return sorted(matches, key=lambda p: p.confidence, reverse=True)

    def query(
        self,
        category: PreferenceCategory | str | None = None,
        status: PreferenceStatus | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserPreference]:
        with self._lock:
            cat_val = category.value if isinstance(category, PreferenceCategory) else category
            st_val = status.value if isinstance(status, PreferenceStatus) else status

            results: list[UserPreference] = []
            sorted_items = sorted(self._store.values(), key=lambda p: p.updated_at, reverse=True)

            for pref in sorted_items:
                p_cat = pref.category.value if isinstance(pref.category, PreferenceCategory) else pref.category
                p_st = pref.status.value if isinstance(pref.status, PreferenceStatus) else pref.status

                if cat_val and p_cat != cat_val:
                    continue
                if st_val and p_st != st_val:
                    continue
                results.append(pref)

            return results[offset : offset + limit]

    def count(
        self,
        category: PreferenceCategory | str | None = None,
        status: PreferenceStatus | str | None = None,
    ) -> int:
        with self._lock:
            cat_val = category.value if isinstance(category, PreferenceCategory) else category
            st_val = status.value if isinstance(status, PreferenceStatus) else status

            c = 0
            for pref in self._store.values():
                p_cat = pref.category.value if isinstance(pref.category, PreferenceCategory) else pref.category
                p_st = pref.status.value if isinstance(pref.status, PreferenceStatus) else pref.status

                if cat_val and p_cat != cat_val:
                    continue
                if st_val and p_st != st_val:
                    continue
                c += 1
            return c

    def delete(self, preference_id: str) -> bool:
        with self._lock:
            if preference_id in self._store:
                del self._store[preference_id]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


class SQLitePreferenceStore:
    """Almacén persistente en base de datos SQLite para preferencias de usuario."""

    def __init__(self, db_path: str | None = None) -> None:
        from config.settings import AppSettings
        settings = AppSettings()

        self.db_path: str = str(db_path or getattr(settings, "PREFERENCE_SQLITE_PATH", "data/preferences.db"))
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        dir_name = os.path.dirname(os.path.abspath(self.db_path))
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS user_preferences (
                            preference_id TEXT PRIMARY KEY,
                            category TEXT NOT NULL,
                            pref_key TEXT NOT NULL,
                            status TEXT NOT NULL,
                            confidence REAL NOT NULL,
                            updated_at TEXT NOT NULL,
                            last_observed TEXT NOT NULL,
                            data_json TEXT NOT NULL
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_pref_cat_key ON user_preferences(category, pref_key);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_pref_status ON user_preferences(status);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_pref_updated ON user_preferences(updated_at);")
            finally:
                conn.close()

    def save(self, preference: UserPreference) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                cat_val = preference.category.value if isinstance(preference.category, PreferenceCategory) else str(preference.category)
                st_val = preference.status.value if isinstance(preference.status, PreferenceStatus) else str(preference.status)
                norm_key = normalize_preference_key(preference.key)
                up_iso = preference.updated_at.isoformat()
                obs_iso = preference.last_observed.isoformat()
                data_json = json.dumps(preference.to_dict(), ensure_ascii=False)

                with conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO user_preferences
                        (preference_id, category, pref_key, status, confidence, updated_at, last_observed, data_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (preference.preference_id, cat_val, norm_key, st_val, preference.confidence, up_iso, obs_iso, data_json),
                    )
            finally:
                conn.close()

    def get(self, preference_id: str) -> UserPreference | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data_json FROM user_preferences WHERE preference_id = ?;",
                    (preference_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                data = json.loads(row[0])
                return UserPreference.from_dict(data)
            finally:
                conn.close()

    def get_by_key(self, category: PreferenceCategory | str, key: str) -> list[UserPreference]:
        with self._lock:
            conn = self._get_connection()
            try:
                cat_val = category.value if isinstance(category, PreferenceCategory) else str(category)
                norm_key = normalize_preference_key(key)

                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT data_json FROM user_preferences
                    WHERE category = ? AND pref_key = ?
                    ORDER BY confidence DESC;
                    """,
                    (cat_val, norm_key),
                )
                rows = cursor.fetchall()
                results: list[UserPreference] = []
                for row in rows:
                    try:
                        results.append(UserPreference.from_dict(json.loads(row[0])))
                    except Exception as ex:
                        logger.warning(f"Error deserializando preferencia: {ex}")
                return results
            finally:
                conn.close()

    def query(
        self,
        category: PreferenceCategory | str | None = None,
        status: PreferenceStatus | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserPreference]:
        with self._lock:
            conn = self._get_connection()
            try:
                conditions: list[str] = []
                params: list[Any] = []

                if category:
                    cat_val = category.value if isinstance(category, PreferenceCategory) else str(category)
                    conditions.append("category = ?")
                    params.append(cat_val)
                if status:
                    st_val = status.value if isinstance(status, PreferenceStatus) else str(status)
                    conditions.append("status = ?")
                    params.append(st_val)

                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                query_sql = f"""
                    SELECT data_json FROM user_preferences
                    {where_clause}
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?;
                """
                params.extend([limit, offset])

                cursor = conn.cursor()
                cursor.execute(query_sql, params)
                rows = cursor.fetchall()

                results: list[UserPreference] = []
                for row in rows:
                    try:
                        results.append(UserPreference.from_dict(json.loads(row[0])))
                    except Exception as ex:
                        logger.warning(f"Error deserializando preferencia: {ex}")
                return results
            finally:
                conn.close()

    def count(
        self,
        category: PreferenceCategory | str | None = None,
        status: PreferenceStatus | str | None = None,
    ) -> int:
        with self._lock:
            conn = self._get_connection()
            try:
                conditions: list[str] = []
                params: list[Any] = []

                if category:
                    cat_val = category.value if isinstance(category, PreferenceCategory) else str(category)
                    conditions.append("category = ?")
                    params.append(cat_val)
                if status:
                    st_val = status.value if isinstance(status, PreferenceStatus) else str(status)
                    conditions.append("status = ?")
                    params.append(st_val)

                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                count_sql = f"SELECT COUNT(*) FROM user_preferences {where_clause};"

                cursor = conn.cursor()
                cursor.execute(count_sql, params)
                row = cursor.fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()

    def delete(self, preference_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.execute(
                        "DELETE FROM user_preferences WHERE preference_id = ?;",
                        (preference_id,),
                    )
                    return cursor.rowcount > 0
            finally:
                conn.close()

    def clear(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM user_preferences;")
            finally:
                conn.close()
