"""Almacenamiento persistente y cálculo estadístico para Model Performance Learning (performance_store.py - Fase 26).

Gestiona la persistencia segura en SQLite con redacción estricta de secretos y
recuperación automática ante corrupción de datos y gestión estricta de conexiones en Windows.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. Sanitización de Secretos: Toda cadena de error o metadato pasa obligatoriamente por SecretRedactor.
2. MODEL PERFORMANCE STORE != AUTHORIZATION: No autoriza ni modifica políticas de seguridad.
"""

from __future__ import annotations

import gc
import json
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.command_output import SecretRedactor
from core.llm.performance_models import (
    InferenceExecutionRecord,
    ModelPerformanceStats,
)
from core.llm.smart_routing_models import TaskType
from core.logger import get_logger

logger = get_logger("jessyca.llm.performance_store")

DEFAULT_DB_PATH = Path("data/model_performance.db")
COLD_START_THRESHOLD: int = 5


class ModelPerformanceStore:
    """Almacén SQLite thread-safe para telemetría y métricas de inferencias de modelos."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._lock = threading.RLock()
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Crea una conexión SQLite y asegura su cierre determinista (prevención de bloqueos en Windows)."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Inicializa las tablas e índices de la base de datos con manejo de corrupción."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS model_inferences (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            model_name TEXT NOT NULL,
                            task_type TEXT NOT NULL,
                            latency_ms REAL NOT NULL,
                            tokens INTEGER NOT NULL,
                            success INTEGER NOT NULL,
                            error_message TEXT,
                            is_timeout INTEGER NOT NULL,
                            confidence REAL NOT NULL,
                            vram_mb REAL NOT NULL,
                            is_fallback INTEGER NOT NULL,
                            validation_passed INTEGER NOT NULL,
                            timestamp TEXT NOT NULL,
                            metadata TEXT
                        )
                        """
                    )
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_model_task ON model_inferences (model_name, task_type)"
                    )
                    conn.commit()
            except sqlite3.DatabaseError as e:
                logger.error(f"[PERFORMANCE STORE CORRUPTION] Error al abrir BD ({e}). Recreando base de datos...")
                self._recover_corrupted_db()

    def _recover_corrupted_db(self) -> None:
        """Recupera la base de datos eliminando el archivo dañado y reinicializando el esquema."""
        try:
            gc.collect()
            if self.db_path.exists():
                try:
                    self.db_path.unlink()
                except Exception:
                    # En caso de lock en Windows, truncar archivo
                    with open(self.db_path, "wb"):
                        pass
            with self._get_connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS model_inferences (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        model_name TEXT NOT NULL,
                        task_type TEXT NOT NULL,
                        latency_ms REAL NOT NULL,
                        tokens INTEGER NOT NULL,
                        success INTEGER NOT NULL,
                        error_message TEXT,
                        is_timeout INTEGER NOT NULL,
                        confidence REAL NOT NULL,
                        vram_mb REAL NOT NULL,
                        is_fallback INTEGER NOT NULL,
                        validation_passed INTEGER NOT NULL,
                        timestamp TEXT NOT NULL,
                        metadata TEXT
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_model_task ON model_inferences (model_name, task_type)"
                )
                conn.commit()
        except Exception as err:
            logger.critical(f"[PERFORMANCE STORE RECOVERY FAILED] No se pudo recuperar la BD: {err}")

    def record_execution(self, record: InferenceExecutionRecord) -> None:
        """Persiste un registro de inferencia tras sanitizar cualquier contenido sensible."""
        with self._lock:
            # 1. Redacción de secretos en mensaje de error
            clean_error = None
            if record.error_message:
                clean_error, _ = SecretRedactor.redact(str(record.error_message))

            # 2. Redacción de secretos en metadatos
            sanitized_meta: dict[str, Any] = {}
            for k, v in record.metadata.items():
                if isinstance(v, str):
                    clean_v, _ = SecretRedactor.redact(v)
                    sanitized_meta[k] = clean_v
                else:
                    sanitized_meta[k] = v

            meta_json = json.dumps(sanitized_meta)
            m_name = record.model_name.strip().lower()
            t_type = str(record.task_type.value if hasattr(record.task_type, "value") else record.task_type)

            try:
                with self._get_connection() as conn:
                    conn.execute(
                        """
                        INSERT INTO model_inferences (
                            model_name, task_type, latency_ms, tokens, success,
                            error_message, is_timeout, confidence, vram_mb,
                            is_fallback, validation_passed, timestamp, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            m_name,
                            t_type,
                            float(record.latency_ms),
                            int(record.tokens),
                            1 if record.success else 0,
                            clean_error,
                            1 if record.is_timeout else 0,
                            float(record.confidence),
                            float(record.vram_mb),
                            1 if record.is_fallback else 0,
                            1 if record.validation_passed else 0,
                            record.timestamp.isoformat(),
                            meta_json,
                        ),
                    )
                    conn.commit()
            except sqlite3.DatabaseError as e:
                logger.error(f"[PERFORMANCE STORE WRITE ERROR] {e}. Reintentando tras recuperación...")
                self._recover_corrupted_db()
                try:
                    with self._get_connection() as conn:
                        conn.execute(
                            """
                            INSERT INTO model_inferences (
                                model_name, task_type, latency_ms, tokens, success,
                                error_message, is_timeout, confidence, vram_mb,
                                is_fallback, validation_passed, timestamp, metadata
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                m_name,
                                t_type,
                                float(record.latency_ms),
                                int(record.tokens),
                                1 if record.success else 0,
                                clean_error,
                                1 if record.is_timeout else 0,
                                float(record.confidence),
                                float(record.vram_mb),
                                1 if record.is_fallback else 0,
                                1 if record.validation_passed else 0,
                                record.timestamp.isoformat(),
                                meta_json,
                            ),
                        )
                        conn.commit()
                except Exception as write_err:
                    logger.error(f"[PERFORMANCE STORE RETRY WRITE ERROR] {write_err}")

    def get_stats(
        self,
        model_name: str,
        task_type: TaskType | None = None,
    ) -> ModelPerformanceStats:
        """Calcula estadísticas agregadas para un modelo y tipo de tarea."""
        m_name = model_name.strip().lower()
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    if task_type is not None:
                        t_val = str(task_type.value if hasattr(task_type, "value") else task_type)
                        cursor.execute(
                            """
                            SELECT latency_ms, tokens, success, is_timeout, confidence, vram_mb, is_fallback, validation_passed
                            FROM model_inferences
                            WHERE model_name = ? AND task_type = ?
                            ORDER BY id ASC
                            """,
                            (m_name, t_val),
                        )
                    else:
                        cursor.execute(
                            """
                            SELECT latency_ms, tokens, success, is_timeout, confidence, vram_mb, is_fallback, validation_passed
                            FROM model_inferences
                            WHERE model_name = ?
                            ORDER BY id ASC
                            """,
                            (m_name,),
                        )
                    rows = cursor.fetchall()
            except sqlite3.DatabaseError:
                rows = []

        total = len(rows)
        if total == 0:
            return ModelPerformanceStats(
                model_name=m_name,
                task_type=task_type,
                total_executions=0,
                successful_executions=0,
                failed_executions=0,
                timeout_count=0,
                fallback_count=0,
                success_rate=1.0,
                avg_latency_ms=50.0,
                p95_latency_ms=50.0,
                avg_tokens=0.0,
                avg_vram_mb=0.0,
                avg_confidence=1.0,
                validation_pass_rate=1.0,
                is_cold_start=True,
            )

        latencies = [r[0] for r in rows]
        latencies_sorted = sorted(latencies)
        p95_idx = int(0.95 * total)
        p95_latency = latencies_sorted[min(p95_idx, total - 1)]

        success_count = sum(1 for r in rows if r[2] == 1)
        timeout_count = sum(1 for r in rows if r[3] == 1)
        fallback_count = sum(1 for r in rows if r[6] == 1)
        val_pass_count = sum(1 for r in rows if r[7] == 1)

        avg_lat = sum(latencies) / total
        avg_tok = sum(r[1] for r in rows) / total
        avg_conf = sum(r[4] for r in rows) / total
        avg_vram = sum(r[5] for r in rows) / total

        return ModelPerformanceStats(
            model_name=m_name,
            task_type=task_type,
            total_executions=total,
            successful_executions=success_count,
            failed_executions=total - success_count,
            timeout_count=timeout_count,
            fallback_count=fallback_count,
            success_rate=success_count / total,
            avg_latency_ms=avg_lat,
            p95_latency_ms=p95_latency,
            avg_tokens=avg_tok,
            avg_vram_mb=avg_vram,
            avg_confidence=avg_conf,
            validation_pass_rate=val_pass_count / total,
            is_cold_start=total < COLD_START_THRESHOLD,
        )

    def get_aggregated_task_stats(self, task_type: TaskType) -> dict[str, ModelPerformanceStats]:
        """Retorna las estadísticas de todos los modelos que hayan ejecutado este tipo de tarea."""
        t_val = str(task_type.value if hasattr(task_type, "value") else task_type)
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT DISTINCT model_name FROM model_inferences WHERE task_type = ?", (t_val,))
                    model_names = [r[0] for r in cursor.fetchall()]
            except sqlite3.DatabaseError:
                model_names = []

        result: dict[str, ModelPerformanceStats] = {}
        for name in model_names:
            result[name] = self.get_stats(model_name=name, task_type=task_type)
        return result

    def get_recent_records(self, limit: int = 50) -> list[InferenceExecutionRecord]:
        """Obtiene las inferencias más recientes."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT model_name, task_type, latency_ms, tokens, success,
                               error_message, is_timeout, confidence, vram_mb,
                               is_fallback, validation_passed, timestamp, metadata
                        FROM model_inferences
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (limit,),
                    )
                    rows = cursor.fetchall()
            except sqlite3.DatabaseError:
                rows = []

        records: list[InferenceExecutionRecord] = []
        for r in rows:
            try:
                t_type = TaskType(r[1])
            except ValueError:
                t_type = TaskType.ANALYSIS_VERIFICATION

            meta = json.loads(r[12]) if r[12] else {}
            records.append(
                InferenceExecutionRecord(
                    model_name=r[0],
                    task_type=t_type,
                    latency_ms=float(r[2]),
                    tokens=int(r[3]),
                    success=bool(r[4]),
                    error_message=r[5],
                    is_timeout=bool(r[6]),
                    confidence=float(r[7]),
                    vram_mb=float(r[8]),
                    is_fallback=bool(r[9]),
                    validation_passed=bool(r[10]),
                    timestamp=datetime.fromisoformat(r[11]) if r[11] else datetime.now(UTC),
                    metadata=meta,
                )
            )
        return records

    def clear(self) -> None:
        """Elimina todos los registros (usado en tests)."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    conn.execute("DELETE FROM model_inferences")
                    conn.commit()
            except sqlite3.DatabaseError:
                self._recover_corrupted_db()
