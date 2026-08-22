"""Almacenamiento Desacoplado y Persistente de Experiencias (experience_store.py - Fase 57).

Implementa la arquitectura desacoplada para persistencia de experiencias:
- Protocolo abstracto IExperienceStore (DIP)
- InMemoryExperienceStore (para tests y ejecución en memoria thread-safe)
- SQLiteExperienceStore (persistencia determinista local con modo WAL e índices)
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Protocol, runtime_checkable

from core.experience.models import Experience, ExperienceCategory
from core.logger import get_logger

logger = get_logger("jessyca.experience.store")


@runtime_checkable
class IExperienceStore(Protocol):
    """Protocolo abstracto para el almacenamiento y consulta de experiencias."""

    def save(self, experience: Experience) -> None:
        """Guarda o actualiza una experiencia en el almacén."""
        ...

    def get(self, experience_id: str) -> Experience | None:
        """Recupera una experiencia por su UUID único."""
        ...

    def query(
        self,
        session_id: str | None = None,
        correlation_id: str | None = None,
        category: ExperienceCategory | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Experience]:
        """Consulta experiencias filtrando por criterios opcionales."""
        ...

    def count(
        self,
        session_id: str | None = None,
        category: ExperienceCategory | str | None = None,
    ) -> int:
        """Cuenta el total de experiencias almacenadas según filtros."""
        ...

    def delete(self, experience_id: str) -> bool:
        """Elimina una experiencia por su identificador."""
        ...

    def clear(self) -> None:
        """Limpia todo el contenido del almacén."""
        ...


class InMemoryExperienceStore:
    """Almacén en memoria thread-safe de experiencias para pruebas y rendimiento rápido."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: dict[str, Experience] = {}

    def save(self, experience: Experience) -> None:
        with self._lock:
            self._store[experience.experience_id] = experience

    def get(self, experience_id: str) -> Experience | None:
        with self._lock:
            return self._store.get(experience_id)

    def query(
        self,
        session_id: str | None = None,
        correlation_id: str | None = None,
        category: ExperienceCategory | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Experience]:
        with self._lock:
            cat_val = category.value if isinstance(category, ExperienceCategory) else category
            results: list[Experience] = []

            # Ordenar por timestamp descendente
            sorted_items = sorted(
                self._store.values(),
                key=lambda exp: exp.timestamp,
                reverse=True,
            )

            for exp in sorted_items:
                if session_id and exp.session_id != session_id:
                    continue
                if correlation_id and exp.correlation_id != correlation_id:
                    continue
                if cat_val and (exp.category.value != cat_val and exp.category != cat_val):
                    continue
                results.append(exp)

            return results[offset : offset + limit]

    def count(
        self,
        session_id: str | None = None,
        category: ExperienceCategory | str | None = None,
    ) -> int:
        with self._lock:
            cat_val = category.value if isinstance(category, ExperienceCategory) else category
            count_val = 0
            for exp in self._store.values():
                if session_id and exp.session_id != session_id:
                    continue
                if cat_val and (exp.category.value != cat_val and exp.category != cat_val):
                    continue
                count_val += 1
            return count_val

    def delete(self, experience_id: str) -> bool:
        with self._lock:
            if experience_id in self._store:
                del self._store[experience_id]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


class SQLiteExperienceStore:
    """Almacén persistente de experiencias basado en SQLite con seguridad concurrente."""

    def __init__(self, db_path: str | None = None) -> None:
        from config.settings import AppSettings
        settings = AppSettings()

        self.db_path: str = str(db_path or getattr(settings, "EXPERIENCE_SQLITE_PATH", "data/experiences.db"))
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
                        CREATE TABLE IF NOT EXISTS experiences (
                            experience_id TEXT PRIMARY KEY,
                            timestamp TEXT NOT NULL,
                            category TEXT NOT NULL,
                            session_id TEXT,
                            correlation_id TEXT,
                            data_json TEXT NOT NULL
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_timestamp ON experiences(timestamp);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_category ON experiences(category);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_session ON experiences(session_id);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_correlation ON experiences(correlation_id);")
            finally:
                conn.close()

    def save(self, experience: Experience) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                cat_val = experience.category.value if isinstance(experience.category, ExperienceCategory) else str(experience.category)
                ts_iso = experience.timestamp.isoformat()
                data_json = json.dumps(experience.to_dict(), ensure_ascii=False)

                with conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO experiences
                        (experience_id, timestamp, category, session_id, correlation_id, data_json)
                        VALUES (?, ?, ?, ?, ?, ?);
                        """,
                        (
                            experience.experience_id,
                            ts_iso,
                            cat_val,
                            experience.session_id,
                            experience.correlation_id,
                            data_json,
                        ),
                    )
            finally:
                conn.close()

    def get(self, experience_id: str) -> Experience | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data_json FROM experiences WHERE experience_id = ?;",
                    (experience_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                data = json.loads(row[0])
                return Experience.from_dict(data)
            finally:
                conn.close()

    def query(
        self,
        session_id: str | None = None,
        correlation_id: str | None = None,
        category: ExperienceCategory | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Experience]:
        with self._lock:
            conn = self._get_connection()
            try:
                conditions: list[str] = []
                params: list[Any] = []

                if session_id:
                    conditions.append("session_id = ?")
                    params.append(session_id)
                if correlation_id:
                    conditions.append("correlation_id = ?")
                    params.append(correlation_id)
                if category:
                    cat_val = category.value if isinstance(category, ExperienceCategory) else category
                    conditions.append("category = ?")
                    params.append(cat_val)

                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                query_sql = f"""
                    SELECT data_json FROM experiences
                    {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?;
                """
                params.extend([limit, offset])

                cursor = conn.cursor()
                cursor.execute(query_sql, params)
                rows = cursor.fetchall()

                results: list[Experience] = []
                for row in rows:
                    try:
                        data = json.loads(row[0])
                        results.append(Experience.from_dict(data))
                    except Exception as ex:
                        logger.warning(f"Error al deserializar experiencia de SQLite: {ex}")
                        continue

                return results
            finally:
                conn.close()

    def count(
        self,
        session_id: str | None = None,
        category: ExperienceCategory | str | None = None,
    ) -> int:
        with self._lock:
            conn = self._get_connection()
            try:
                conditions: list[str] = []
                params: list[Any] = []

                if session_id:
                    conditions.append("session_id = ?")
                    params.append(session_id)
                if category:
                    cat_val = category.value if isinstance(category, ExperienceCategory) else category
                    conditions.append("category = ?")
                    params.append(cat_val)

                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                count_sql = f"SELECT COUNT(*) FROM experiences {where_clause};"

                cursor = conn.cursor()
                cursor.execute(count_sql, params)
                row = cursor.fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()

    def delete(self, experience_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.execute(
                        "DELETE FROM experiences WHERE experience_id = ?;",
                        (experience_id,),
                    )
                    return cursor.rowcount > 0
            finally:
                conn.close()

    def clear(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM experiences;")
            finally:
                conn.close()
