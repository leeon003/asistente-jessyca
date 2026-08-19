"""Persistencia Segura y Recuperación de Workflows tras Reinicio/Crash (Etapa 18.2).

GARANTÍAS DE SEGURIDAD Y PRIVACIDAD:
1. Almacena ÚNICAMENTE la información mínima necesaria (workflow_id, step, status, timestamps, metadata sanitizada).
2. Los datos pasan obligatoriamente por SecretRedactor para garantizar que no se almacenen secretos/contraseñas.
3. REGLA INMUTABLE DE REINICIO:
   - Al reiniciar el sistema, los workflows DANGEROUS o CRITICAL NUNCA se continúan automáticamente.
   - Quedan en estado PAUSED_REQUIRES_REVIEW y requieren autorización explícita del usuario.
   - Los workflows READ_ONLY y LOW_RISK pueden reanudarse de forma segura.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from core.autonomy.autonomy_level import TaskActionRisk
from core.command_output import SecretRedactor
from core.exceptions import MCPError
from core.logger import get_logger
from core.observability.structured_event import sanitize_bounded_metadata
from core.workflow.models import (
    WorkflowState,
    WorkflowStateSnapshot,
)

logger = get_logger("jessyca.workflow.store")


class WorkflowPersistenceError(MCPError):
    """Error base de persistencia de workflows."""

    pass


class WorkflowResumptionBlockedError(MCPError):
    """Error emitido cuando un workflow en PAUSED_REQUIRES_REVIEW intenta reanudarse sin autorización humana."""

    pass


class IWorkflowStore(Protocol):
    """Protocolo para almacenamiento persistente del estado de workflows."""

    def save_snapshot(self, snapshot: WorkflowStateSnapshot) -> None:
        """Guarda o actualiza una instantánea del estado de un workflow."""
        ...

    def get_snapshot(self, workflow_id: str) -> WorkflowStateSnapshot | None:
        """Recupera la instantánea de un workflow por su ID."""
        ...

    def list_active_snapshots(self) -> list[WorkflowStateSnapshot]:
        """Lista todas las instantáneas activas o no completadas."""
        ...

    def delete_snapshot(self, workflow_id: str) -> bool:
        """Elimina la instantánea de un workflow."""
        ...


class InMemoryWorkflowStore:
    """Implementación thread-safe en memoria para pruebas o almacenamiento efímero."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: dict[str, WorkflowStateSnapshot] = {}

    def save_snapshot(self, snapshot: WorkflowStateSnapshot) -> None:
        with self._lock:
            # Sanitizar metadatos y outputs antes de almacenar
            clean_summary = sanitize_bounded_metadata(snapshot.step_results_summary)
            clean_reason = SecretRedactor.redact(snapshot.failure_reason or "")[0] if snapshot.failure_reason else None

            clean_snapshot = WorkflowStateSnapshot(
                workflow_id=snapshot.workflow_id,
                name=snapshot.name,
                status=snapshot.status,
                risk_level=snapshot.risk_level,
                current_step_id=snapshot.current_step_id,
                completed_steps=snapshot.completed_steps,
                step_results_summary=clean_summary if isinstance(clean_summary, dict) else {},
                failure_reason=clean_reason,
                requires_user_review=snapshot.requires_user_review,
                auto_resume_allowed=snapshot.auto_resume_allowed,
                created_at=snapshot.created_at,
                updated_at=datetime.now(UTC),
            )
            self._store[snapshot.workflow_id] = clean_snapshot

    def get_snapshot(self, workflow_id: str) -> WorkflowStateSnapshot | None:
        with self._lock:
            return self._store.get(workflow_id)

    def list_active_snapshots(self) -> list[WorkflowStateSnapshot]:
        with self._lock:
            active_states = {
                WorkflowState.CREATED,
                WorkflowState.VALIDATING,
                WorkflowState.RUNNING,
                WorkflowState.WAITING,
                WorkflowState.PAUSED,
                WorkflowState.PAUSED_REQUIRES_REVIEW,
                WorkflowState.ROLLING_BACK,
            }
            return [s for s in self._store.values() if s.status in active_states]

    def delete_snapshot(self, workflow_id: str) -> bool:
        with self._lock:
            if workflow_id in self._store:
                del self._store[workflow_id]
                return True
            return False


class SQLiteWorkflowStore:
    """Implementación persistente en SQLite con sanitización garantizada de secretos."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_snapshots (
                        workflow_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        risk_level TEXT NOT NULL,
                        current_step_id TEXT,
                        completed_steps TEXT NOT NULL,
                        step_results_summary TEXT NOT NULL,
                        failure_reason TEXT,
                        requires_user_review INTEGER NOT NULL,
                        auto_resume_allowed INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def save_snapshot(self, snapshot: WorkflowStateSnapshot) -> None:
        clean_summary = sanitize_bounded_metadata(snapshot.step_results_summary)
        clean_reason = SecretRedactor.redact(snapshot.failure_reason or "")[0] if snapshot.failure_reason else None

        with self._lock:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            try:
                conn.execute(
                    """
                    INSERT INTO workflow_snapshots (
                        workflow_id, name, status, risk_level, current_step_id,
                        completed_steps, step_results_summary, failure_reason,
                        requires_user_review, auto_resume_allowed, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workflow_id) DO UPDATE SET
                        status=excluded.status,
                        risk_level=excluded.risk_level,
                        current_step_id=excluded.current_step_id,
                        completed_steps=excluded.completed_steps,
                        step_results_summary=excluded.step_results_summary,
                        failure_reason=excluded.failure_reason,
                        requires_user_review=excluded.requires_user_review,
                        auto_resume_allowed=excluded.auto_resume_allowed,
                        updated_at=excluded.updated_at
                    """,
                    (
                        snapshot.workflow_id,
                        snapshot.name,
                        snapshot.status.value,
                        snapshot.risk_level.value,
                        snapshot.current_step_id,
                        json.dumps(list(snapshot.completed_steps)),
                        json.dumps(clean_summary if isinstance(clean_summary, dict) else {}),
                        clean_reason,
                        1 if snapshot.requires_user_review else 0,
                        1 if snapshot.auto_resume_allowed else 0,
                        snapshot.created_at.isoformat(),
                        datetime.now(UTC).isoformat(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get_snapshot(self, workflow_id: str) -> WorkflowStateSnapshot | None:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT * FROM workflow_snapshots WHERE workflow_id = ?",
                    (workflow_id,),
                ).fetchone()

                if not row:
                    return None

                return self._row_to_snapshot(row)
            finally:
                conn.close()

    def list_active_snapshots(self) -> list[WorkflowStateSnapshot]:
        active_states = (
            WorkflowState.CREATED.value,
            WorkflowState.VALIDATING.value,
            WorkflowState.RUNNING.value,
            WorkflowState.WAITING.value,
            WorkflowState.PAUSED.value,
            WorkflowState.PAUSED_REQUIRES_REVIEW.value,
            WorkflowState.ROLLING_BACK.value,
        )
        placeholders = ",".join("?" * len(active_states))

        with self._lock:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    f"SELECT * FROM workflow_snapshots WHERE status IN ({placeholders})",
                    active_states,
                ).fetchall()

                return [self._row_to_snapshot(r) for r in rows]
            finally:
                conn.close()

    def delete_snapshot(self, workflow_id: str) -> bool:
        with self._lock:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            try:
                cur = conn.execute("DELETE FROM workflow_snapshots WHERE workflow_id = ?", (workflow_id,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def _row_to_snapshot(self, row: sqlite3.Row) -> WorkflowStateSnapshot:
        return WorkflowStateSnapshot(
            workflow_id=row["workflow_id"],
            name=row["name"],
            status=WorkflowState(row["status"]),
            risk_level=TaskActionRisk(row["risk_level"]),
            current_step_id=row["current_step_id"],
            completed_steps=tuple(json.loads(row["completed_steps"])),
            step_results_summary=json.loads(row["step_results_summary"]),
            failure_reason=row["failure_reason"],
            requires_user_review=bool(row["requires_user_review"]),
            auto_resume_allowed=bool(row["auto_resume_allowed"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


class WorkflowRecoveryManager:
    """Gestor de recuperación de workflows interrumpidos tras reinicio o fallo del sistema."""

    @classmethod
    def handle_system_restart(cls, store: IWorkflowStore) -> list[WorkflowStateSnapshot]:
        """Evalúa todos los workflows interrumpidos durante el arranque de JESSYCA.

        INVARIANTE DE SEGURIDAD ABSOLUTA (Etapa 18.2):
        1. Workflows DANGEROUS o CRITICAL -> Quedan en PAUSED_REQUIRES_REVIEW.
           NO se reanudan automáticamente bajo ninguna circunstancia.
        2. Workflows READ_ONLY o LOW_RISK -> Se marcan como PAUSED con auto_resume_allowed=True.
        """
        active_snapshots = store.list_active_snapshots()
        recovered: list[WorkflowStateSnapshot] = []

        for snap in active_snapshots:
            # Si el workflow estaba en ejecución activa cuando ocurrió la interrupción/reinicio
            if snap.status in (WorkflowState.RUNNING, WorkflowState.VALIDATING, WorkflowState.WAITING, WorkflowState.ROLLING_BACK):
                is_dangerous = snap.risk_level in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL)

                if is_dangerous:
                    logger.warning(
                        f"[WORKFLOW RECOVERY] Workflow interrumpido '{snap.workflow_id}' ({snap.name}) "
                        f"es de riesgo {snap.risk_level.value}. Colocando en PAUSED_REQUIRES_REVIEW. "
                        "Reanudación automática BLOQUEADA por seguridad."
                    )
                    new_status = WorkflowState.PAUSED_REQUIRES_REVIEW
                    requires_review = True
                    auto_resume = False
                    reason = "Workflow interrumpido requiere revisión humana obligatoria antes de reanudarse debido a su nivel de riesgo DANGEROUS/CRITICAL."
                else:
                    logger.info(
                        f"[WORKFLOW RECOVERY] Workflow interrumpido '{snap.workflow_id}' ({snap.name}) "
                        f"es de bajo riesgo ({snap.risk_level.value}). Colocando en PAUSED (elegible para reanudación)."
                    )
                    new_status = WorkflowState.PAUSED
                    requires_review = False
                    auto_resume = True
                    reason = "Workflow interrumpido en reinicio previo. Listo para reanudar de forma segura."

                updated_snap = WorkflowStateSnapshot(
                    workflow_id=snap.workflow_id,
                    name=snap.name,
                    status=new_status,
                    risk_level=snap.risk_level,
                    current_step_id=snap.current_step_id,
                    completed_steps=snap.completed_steps,
                    step_results_summary=snap.step_results_summary,
                    failure_reason=reason,
                    requires_user_review=requires_review,
                    auto_resume_allowed=auto_resume,
                    created_at=snap.created_at,
                    updated_at=datetime.now(UTC),
                )
                store.save_snapshot(updated_snap)
                recovered.append(updated_snap)

        return recovered
