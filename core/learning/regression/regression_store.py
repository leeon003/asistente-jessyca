"""Almacén Persistente de Casos de Regresión (regression_store.py - Fase 61).

Proporciona persistencia determinista y deduplicación para casos de regresión:
- IRegressionStore (protocolo de interfaz)
- InMemoryRegressionStore (almacén en memoria para testing)
- SQLiteRegressionStore (persistencia local SQLite con modo WAL e índices)
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Protocol, runtime_checkable

from core.learning.regression.regression_models import (
    RegressionCase,
    RegressionCategory,
    RegressionStatus,
)
from core.logger import get_logger

logger = get_logger("jessyca.learning.regression_store")


@runtime_checkable
class IRegressionStore(Protocol):
    """Protocolo de interfaz para el almacén de casos de prueba de regresión."""

    def save(self, case: RegressionCase) -> None: ...
    def get(self, case_id: str) -> RegressionCase | None: ...
    def get_by_signature(self, signature: str) -> RegressionCase | None: ...
    def query(
        self,
        status: RegressionStatus | str | None = None,
        category: RegressionCategory | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RegressionCase]: ...
    def count(
        self,
        status: RegressionStatus | str | None = None,
        category: RegressionCategory | str | None = None,
    ) -> int: ...
    def delete(self, case_id: str) -> bool: ...
    def clear(self) -> None: ...


class InMemoryRegressionStore:
    """Almacén en memoria thread-safe para casos de regresión."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: dict[str, RegressionCase] = {}
        self._sig_index: dict[str, str] = {}

    def save(self, case: RegressionCase) -> None:
        with self._lock:
            self._store[case.case_id] = case
            if case.failure_signature:
                self._sig_index[case.failure_signature] = case.case_id

    def get(self, case_id: str) -> RegressionCase | None:
        with self._lock:
            return self._store.get(case_id)

    def get_by_signature(self, signature: str) -> RegressionCase | None:
        with self._lock:
            case_id = self._sig_index.get(signature)
            return self._store.get(case_id) if case_id else None

    def query(
        self,
        status: RegressionStatus | str | None = None,
        category: RegressionCategory | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RegressionCase]:
        with self._lock:
            st_val = status.value if isinstance(status, RegressionStatus) else status
            cat_val = category.value if isinstance(category, RegressionCategory) else category

            results: list[RegressionCase] = []
            sorted_items = sorted(self._store.values(), key=lambda c: c.created_at, reverse=True)

            for item in sorted_items:
                if st_val and (item.status.value != st_val and item.status != st_val):
                    continue
                if cat_val and (item.category.value != cat_val and item.category != cat_val):
                    continue
                results.append(item)

            return results[offset : offset + limit]

    def count(
        self,
        status: RegressionStatus | str | None = None,
        category: RegressionCategory | str | None = None,
    ) -> int:
        with self._lock:
            st_val = status.value if isinstance(status, RegressionStatus) else status
            cat_val = category.value if isinstance(category, RegressionCategory) else category

            c = 0
            for item in self._store.values():
                if st_val and (item.status.value != st_val and item.status != st_val):
                    continue
                if cat_val and (item.category.value != cat_val and item.category != cat_val):
                    continue
                c += 1
            return c

    def delete(self, case_id: str) -> bool:
        with self._lock:
            if case_id in self._store:
                case = self._store.pop(case_id)
                if case.failure_signature in self._sig_index:
                    del self._sig_index[case.failure_signature]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._sig_index.clear()


class SQLiteRegressionStore:
    """Almacén persistente en base de datos SQLite para casos de regresión."""

    def __init__(self, db_path: str | None = None) -> None:
        from config.settings import AppSettings
        settings = AppSettings()

        self.db_path: str = str(db_path or getattr(settings, "REGRESSION_SQLITE_PATH", "data/regressions.db"))
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
                        CREATE TABLE IF NOT EXISTS regression_cases (
                            case_id TEXT PRIMARY KEY,
                            created_at TEXT NOT NULL,
                            status TEXT NOT NULL,
                            category TEXT NOT NULL,
                            failure_signature TEXT NOT NULL,
                            data_json TEXT NOT NULL
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_reg_status ON regression_cases(status);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_reg_category ON regression_cases(category);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_reg_signature ON regression_cases(failure_signature);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_reg_created ON regression_cases(created_at);")
            finally:
                conn.close()

    def save(self, case: RegressionCase) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                st_val = case.status.value if isinstance(case.status, RegressionStatus) else str(case.status)
                cat_val = case.category.value if isinstance(case.category, RegressionCategory) else str(case.category)
                ts_iso = case.created_at.isoformat()
                data_json = json.dumps(case.to_dict(), ensure_ascii=False)

                with conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO regression_cases
                        (case_id, created_at, status, category, failure_signature, data_json)
                        VALUES (?, ?, ?, ?, ?, ?);
                        """,
                        (case.case_id, ts_iso, st_val, cat_val, case.failure_signature, data_json),
                    )
            finally:
                conn.close()

    def get(self, case_id: str) -> RegressionCase | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data_json FROM regression_cases WHERE case_id = ?;",
                    (case_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                data = json.loads(row[0])
                return RegressionCase.from_dict(data)
            finally:
                conn.close()

    def get_by_signature(self, signature: str) -> RegressionCase | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data_json FROM regression_cases WHERE failure_signature = ? LIMIT 1;",
                    (signature,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                data = json.loads(row[0])
                return RegressionCase.from_dict(data)
            finally:
                conn.close()

    def query(
        self,
        status: RegressionStatus | str | None = None,
        category: RegressionCategory | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RegressionCase]:
        with self._lock:
            conn = self._get_connection()
            try:
                conditions: list[str] = []
                params: list[Any] = []

                if status:
                    st_val = status.value if isinstance(status, RegressionStatus) else status
                    conditions.append("status = ?")
                    params.append(st_val)
                if category:
                    cat_val = category.value if isinstance(category, RegressionCategory) else category
                    conditions.append("category = ?")
                    params.append(cat_val)

                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                query_sql = f"""
                    SELECT data_json FROM regression_cases
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?;
                """
                params.extend([limit, offset])

                cursor = conn.cursor()
                cursor.execute(query_sql, params)
                rows = cursor.fetchall()

                results: list[RegressionCase] = []
                for row in rows:
                    try:
                        data = json.loads(row[0])
                        results.append(RegressionCase.from_dict(data))
                    except Exception as ex:
                        logger.warning(f"Error deserializando caso de regresión: {ex}")
                        continue
                return results
            finally:
                conn.close()

    def count(
        self,
        status: RegressionStatus | str | None = None,
        category: RegressionCategory | str | None = None,
    ) -> int:
        with self._lock:
            conn = self._get_connection()
            try:
                conditions: list[str] = []
                params: list[Any] = []

                if status:
                    st_val = status.value if isinstance(status, RegressionStatus) else status
                    conditions.append("status = ?")
                    params.append(st_val)
                if category:
                    cat_val = category.value if isinstance(category, RegressionCategory) else category
                    conditions.append("category = ?")
                    params.append(cat_val)

                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                count_sql = f"SELECT COUNT(*) FROM regression_cases {where_clause};"

                cursor = conn.cursor()
                cursor.execute(count_sql, params)
                row = cursor.fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()

    def delete(self, case_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.execute(
                        "DELETE FROM regression_cases WHERE case_id = ?;",
                        (case_id,),
                    )
                    return cursor.rowcount > 0
            finally:
                conn.close()

    def clear(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM regression_cases;")
            finally:
                conn.close()
