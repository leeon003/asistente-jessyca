"""Almacén Persistente y Desacoplado de Propuestas (proposal_store.py - Fase 59).

Proporciona almacenamiento persistente para propuestas de aprendizaje:
- Protocolo abstracto IProposalStore
- InMemoryProposalStore (thread-safe para tests)
- SQLiteProposalStore (persistencia determinista local en SQLite con modo WAL)
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Protocol, runtime_checkable

from core.learning.proposal_models import LearningProposal, ProposalCategory, ProposalStatus
from core.logger import get_logger

logger = get_logger("jessyca.learning.store")


@runtime_checkable
class IProposalStore(Protocol):
    """Protocolo de interfaz para el almacenamiento de propuestas de aprendizaje."""

    def save(self, proposal: LearningProposal) -> None: ...
    def get(self, proposal_id: str) -> LearningProposal | None: ...
    def query(
        self,
        status: ProposalStatus | str | None = None,
        category: ProposalCategory | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[LearningProposal]: ...
    def count(
        self,
        status: ProposalStatus | str | None = None,
        category: ProposalCategory | str | None = None,
    ) -> int: ...
    def delete(self, proposal_id: str) -> bool: ...
    def clear(self) -> None: ...


class InMemoryProposalStore:
    """Almacén en memoria thread-safe para propuestas de aprendizaje."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: dict[str, LearningProposal] = {}

    def save(self, proposal: LearningProposal) -> None:
        with self._lock:
            self._store[proposal.proposal_id] = proposal

    def get(self, proposal_id: str) -> LearningProposal | None:
        with self._lock:
            return self._store.get(proposal_id)

    def query(
        self,
        status: ProposalStatus | str | None = None,
        category: ProposalCategory | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[LearningProposal]:
        with self._lock:
            st_val = status.value if isinstance(status, ProposalStatus) else status
            cat_val = category.value if isinstance(category, ProposalCategory) else category

            results: list[LearningProposal] = []
            sorted_items = sorted(self._store.values(), key=lambda p: p.created_at, reverse=True)

            for prop in sorted_items:
                if st_val and (prop.status.value != st_val and prop.status != st_val):
                    continue
                if cat_val and (prop.category.value != cat_val and prop.category != cat_val):
                    continue
                results.append(prop)

            return results[offset : offset + limit]

    def count(
        self,
        status: ProposalStatus | str | None = None,
        category: ProposalCategory | str | None = None,
    ) -> int:
        with self._lock:
            st_val = status.value if isinstance(status, ProposalStatus) else status
            cat_val = category.value if isinstance(category, ProposalCategory) else category

            count_val = 0
            for prop in self._store.values():
                if st_val and (prop.status.value != st_val and prop.status != st_val):
                    continue
                if cat_val and (prop.category.value != cat_val and prop.category != cat_val):
                    continue
                count_val += 1
            return count_val

    def delete(self, proposal_id: str) -> bool:
        with self._lock:
            if proposal_id in self._store:
                del self._store[proposal_id]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


class SQLiteProposalStore:
    """Almacén persistente en base de datos SQLite para propuestas de aprendizaje."""

    def __init__(self, db_path: str | None = None) -> None:
        from config.settings import AppSettings
        settings = AppSettings()

        self.db_path: str = str(db_path or getattr(settings, "PROPOSAL_SQLITE_PATH", "data/proposals.db"))
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
                        CREATE TABLE IF NOT EXISTS learning_proposals (
                            proposal_id TEXT PRIMARY KEY,
                            created_at TEXT NOT NULL,
                            status TEXT NOT NULL,
                            category TEXT NOT NULL,
                            data_json TEXT NOT NULL
                        );
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_prop_status ON learning_proposals(status);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_prop_category ON learning_proposals(category);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_prop_created ON learning_proposals(created_at);")
            finally:
                conn.close()

    def save(self, proposal: LearningProposal) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                st_val = proposal.status.value if isinstance(proposal.status, ProposalStatus) else str(proposal.status)
                cat_val = proposal.category.value if isinstance(proposal.category, ProposalCategory) else str(proposal.category)
                ts_iso = proposal.created_at.isoformat()
                data_json = json.dumps(proposal.to_dict(), ensure_ascii=False)

                with conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO learning_proposals
                        (proposal_id, created_at, status, category, data_json)
                        VALUES (?, ?, ?, ?, ?);
                        """,
                        (proposal.proposal_id, ts_iso, st_val, cat_val, data_json),
                    )
            finally:
                conn.close()

    def get(self, proposal_id: str) -> LearningProposal | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT data_json FROM learning_proposals WHERE proposal_id = ?;",
                    (proposal_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                data = json.loads(row[0])
                return LearningProposal.from_dict(data)
            finally:
                conn.close()

    def query(
        self,
        status: ProposalStatus | str | None = None,
        category: ProposalCategory | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[LearningProposal]:
        with self._lock:
            conn = self._get_connection()
            try:
                conditions: list[str] = []
                params: list[Any] = []

                if status:
                    st_val = status.value if isinstance(status, ProposalStatus) else status
                    conditions.append("status = ?")
                    params.append(st_val)
                if category:
                    cat_val = category.value if isinstance(category, ProposalCategory) else category
                    conditions.append("category = ?")
                    params.append(cat_val)

                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                query_sql = f"""
                    SELECT data_json FROM learning_proposals
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?;
                """
                params.extend([limit, offset])

                cursor = conn.cursor()
                cursor.execute(query_sql, params)
                rows = cursor.fetchall()

                results: list[LearningProposal] = []
                for row in rows:
                    try:
                        data = json.loads(row[0])
                        results.append(LearningProposal.from_dict(data))
                    except Exception as ex:
                        logger.warning(f"Error deserializando propuesta: {ex}")
                        continue
                return results
            finally:
                conn.close()

    def count(
        self,
        status: ProposalStatus | str | None = None,
        category: ProposalCategory | str | None = None,
    ) -> int:
        with self._lock:
            conn = self._get_connection()
            try:
                conditions: list[str] = []
                params: list[Any] = []

                if status:
                    st_val = status.value if isinstance(status, ProposalStatus) else status
                    conditions.append("status = ?")
                    params.append(st_val)
                if category:
                    cat_val = category.value if isinstance(category, ProposalCategory) else category
                    conditions.append("category = ?")
                    params.append(cat_val)

                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                count_sql = f"SELECT COUNT(*) FROM learning_proposals {where_clause};"

                cursor = conn.cursor()
                cursor.execute(count_sql, params)
                row = cursor.fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()

    def delete(self, proposal_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.execute(
                        "DELETE FROM learning_proposals WHERE proposal_id = ?;",
                        (proposal_id,),
                    )
                    return cursor.rowcount > 0
            finally:
                conn.close()

    def clear(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM learning_proposals;")
            finally:
                conn.close()
