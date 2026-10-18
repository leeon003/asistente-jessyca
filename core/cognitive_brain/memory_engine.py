"""JESSYCA BRAIN 1.0 — Motor de Memoria Estructurada Unificado (MemoryEngine).

Implementa la arquitectura lógica de 4 niveles:
1. Working Memory (Memoria de Trabajo): Contexto de sesión, tarea activa y referencias temporales.
2. Episodic Memory (Memoria Episódica): Registro de experiencias, planes y resultados verificados (SQLite WAL).
3. Semantic Memory (Memoria Semántica): Hechos duraderos, preferencias y conocimiento conceptual.
4. Procedural Memory (Memoria Procedimental): Procedimientos aprendidos y versionados con ciclo de vida
   (CANDIDATE -> TESTING -> VALIDATED -> DEPRECATED).

INVARIANTES DE SEGURIDAD:
- MEMORY IS NOT AUTHORITY: Ningún recuerdo puede conceder permisos ni saltarse a JDE o RiskEngine.
- DEFENSE AGAINST INJECTION: Sanitización activa contra Prompt Injection y manipulación de instrucciones.
- PRIVACY BY DESIGN: Redacción preventiva de secretos (claves, tokens, contraseñas) antes de la persistencia.
- NON-DESTRUCTIVE: Preserva íntegramente las bases de datos y archivos preexistentes (data/memory_long_term).
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from core.cognitive_brain.contracts import (
    ContextBundle,
    LearnedProcedure,
    MemoryProvider,
    ProcedureLifecycleState,
    ProcedureRepository,
)
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.memory.long_term_memory import (
    LongTermMemoryEngine,
    MemoryRecordType,
    MemorySensitivity,
)

logger = logging.getLogger("jessyca.brain.memory")


# =========================================================================
# 1. WORKING MEMORY (MEMORIA DE TRABAJO - EFÍMERA Y DE TAREA ACTIVA)
# =========================================================================

@dataclass
class WorkingMemoryState:
    """Estado efímero de la tarea y conversación activa."""
    session_id: str
    active_goal: str = ""
    active_task_id: str | None = None
    active_plan_id: str | None = None
    current_step_index: int = 0
    selected_tools: list[str] = field(default_factory=list)
    current_application: str | None = None
    active_document_path: str | None = None
    active_app: str | None = None
    active_hwnd: int | None = None
    last_written_text: str | None = None
    last_written_topic: str | None = None
    anaphora_references: dict[str, Any] = field(default_factory=dict)
    last_action_result: Any = None
    context_variables: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.context_variables:
            d.update(self.context_variables)
        return d


class WorkingMemory:
    """Gestor de memoria de trabajo en RAM por sesión."""

    def __init__(self) -> None:
        self._sessions: dict[str, WorkingMemoryState] = {}
        self._lock = threading.RLock()

    def get_state(self, session_id: str) -> WorkingMemoryState:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = WorkingMemoryState(session_id=session_id)
            return self._sessions[session_id]

    def update(self, session_id: str, updates: dict[str, Any]) -> WorkingMemoryState:
        with self._lock:
            state = self.get_state(session_id)
            for k, v in updates.items():
                if hasattr(state, k):
                    setattr(state, k, v)
                else:
                    state.context_variables[k] = v
            state.updated_at = time.time()
            return state

    def set_reference(self, session_id: str, term: str, value: Any) -> None:
        """Asigna explícitamente una referencia para resolución anafórica."""
        with self._lock:
            state = self.get_state(session_id)
            state.anaphora_references[term.lower().strip()] = value
            state.updated_at = time.time()

    def resolve_reference(self, session_id: str, term: str) -> Any | None:
        """Resuelve anáforas como 'eso', 'aquello', 'el resumen', 'el archivo'."""
        with self._lock:
            state = self.get_state(session_id)
            clean_term = term.lower().strip()
            if clean_term in ("eso", "aquello"):
                return state.last_action_result or state.current_application or state.anaphora_references.get("last_target")
            if clean_term in ("la app", "el programa", "la aplicación"):
                return state.current_application or state.anaphora_references.get("last_target")
            if clean_term in ("el archivo", "el documento"):
                return state.active_document_path or state.anaphora_references.get("last_file")
            if clean_term in ("el resumen", "lo investigado"):
                return state.anaphora_references.get("last_summary")
            return state.anaphora_references.get(clean_term)

    def clear(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]

    def clear_session(self, session_id: str) -> None:
        self.clear(session_id)


# =========================================================================
# 2. EPISODIC MEMORY (MEMORIA EPISÓDICA - EXPERIENCIAS Y RESULTADOS)
# =========================================================================

@dataclass
class EpisodeRecord:
    """Registro inmutable de una experiencia y resultado de ejecución."""
    episode_id: str
    session_id: str = "default"
    user_instruction: str = ""
    intent: str = "general_query"
    plan_summary: str = ""
    tools_used: list[str] = field(default_factory=list)
    actions_executed: list[dict[str, Any]] = field(default_factory=list)
    success: bool = True
    verified_evidence: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    resolution_notes: str | None = None
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    # Campos ergonómicos y compatibilidad
    goal: str = ""
    plan_id: str | None = None
    subtasks: list[str] = field(default_factory=list)
    error_summary: str | None = None

    def __post_init__(self) -> None:
        if not self.user_instruction and self.goal:
            self.user_instruction = self.goal
        elif not self.goal and self.user_instruction:
            self.goal = self.user_instruction
        if self.plan_id and not self.plan_summary:
            self.plan_summary = f"Plan {self.plan_id}"
        if self.error_summary and not self.errors:
            self.errors = [self.error_summary]
        elif self.errors and not self.error_summary:
            self.error_summary = "; ".join(self.errors)
        if self.subtasks and not self.actions_executed:
            self.actions_executed = [{"step": s} for s in self.subtasks]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["goal"] = self.goal or self.user_instruction
        d["error_summary"] = self.error_summary
        return d


class EpisodicMemory:
    """Almacenamiento persistente de experiencias pasadas mediante SQLite WAL."""

    def __init__(self, db_path: str = "data/memory_brain.db") -> None:
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        parent_dir = os.path.dirname(self.db_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    user_instruction TEXT,
                    intent TEXT,
                    plan_summary TEXT,
                    tools_used TEXT,
                    actions_executed TEXT,
                    success INTEGER,
                    verified_evidence TEXT,
                    errors TEXT,
                    resolution_notes TEXT,
                    duration_ms REAL,
                    timestamp REAL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_intent ON episodes (intent);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes (timestamp);")
            conn.commit()

    def record_episode(self, episode: EpisodeRecord | dict[str, Any]) -> str:
        if isinstance(episode, dict):
            ep = EpisodeRecord(
                episode_id=episode.get("episode_id") or f"ep-{uuid.uuid4().hex[:10]}",
                session_id=episode.get("session_id", "default"),
                user_instruction=episode.get("user_instruction") or episode.get("goal", ""),
                intent=episode.get("intent", "general_query"),
                plan_summary=episode.get("plan_summary") or episode.get("plan_id", ""),
                tools_used=list(episode.get("tools_used", [])),
                actions_executed=list(episode.get("actions_executed", [])),
                success=bool(episode.get("success", False)),
                verified_evidence=dict(episode.get("verified_evidence", {})),
                errors=list(episode.get("errors", []) if episode.get("errors") else ([episode.get("error_summary")] if episode.get("error_summary") else [])),
                resolution_notes=episode.get("resolution_notes"),
                duration_ms=float(episode.get("duration_ms", 0.0)),
            )
        else:
            ep = episode

        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO episodes (
                    episode_id, session_id, user_instruction, intent, plan_summary,
                    tools_used, actions_executed, success, verified_evidence, errors,
                    resolution_notes, duration_ms, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                ep.episode_id,
                ep.session_id,
                ep.user_instruction,
                ep.intent,
                ep.plan_summary,
                json.dumps(ep.tools_used),
                json.dumps(ep.actions_executed),
                1 if ep.success else 0,
                json.dumps(ep.verified_evidence),
                json.dumps(ep.errors),
                ep.resolution_notes,
                ep.duration_ms,
                ep.timestamp,
            ))
            conn.commit()
        return ep.episode_id

    def find_recent_experiences(
        self,
        intent: str | None = None,
        only_successful: bool = False,
        limit: int = 5,
    ) -> list[EpisodeRecord]:
        query = "SELECT episode_id, session_id, user_instruction, intent, plan_summary, tools_used, actions_executed, success, verified_evidence, errors, resolution_notes, duration_ms, timestamp FROM episodes"
        clauses = []
        params: list[Any] = []
        if intent:
            clauses.append("intent = ?")
            params.append(intent)
        if only_successful:
            clauses.append("success = 1")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        records = []
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            for row in cursor.fetchall():
                records.append(self._row_to_episode(row))
        return records

    def get_recent_episodes(self, limit: int = 10) -> list[dict[str, Any]]:
        """Devuelve los episodios más recientes como diccionarios estructurados."""
        records = self.find_recent_experiences(limit=limit)
        return [r.to_dict() for r in records]

    def find_past_failures(self, query: str = "", limit: int = 5) -> list[dict[str, Any]]:
        """Busca episodios con fallas para evitar repetir errores pasados."""
        sql = """
            SELECT episode_id, session_id, user_instruction, intent, plan_summary,
                   tools_used, actions_executed, success, verified_evidence, errors,
                   resolution_notes, duration_ms, timestamp
            FROM episodes
            WHERE success = 0
        """
        params: list[Any] = []
        if query:
            tokens = [t.strip().lower() for t in query.split() if len(t.strip()) > 2]
            if tokens:
                token_clauses = ["(LOWER(user_instruction) LIKE ? OR LOWER(intent) LIKE ? OR LOWER(errors) LIKE ?)" for _ in tokens]
                sql += " AND (" + " OR ".join(token_clauses) + ")"
                for token in tokens:
                    pat = f"%{token}%"
                    params.extend([pat, pat, pat])

        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        results = []
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            for row in cursor.fetchall():
                results.append(self._row_to_episode(row).to_dict())
        return results

    def find_relevant_episodes(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Busca episodios relevantes por coincidencia léxica en la meta o plan."""
        tokens = [t.strip().lower() for t in query.split() if len(t.strip()) > 2]
        sql = "SELECT episode_id, session_id, user_instruction, intent, plan_summary, tools_used, actions_executed, success, verified_evidence, errors, resolution_notes, duration_ms, timestamp FROM episodes"
        params: list[Any] = []
        if tokens:
            token_clauses = ["(LOWER(user_instruction) LIKE ? OR LOWER(intent) LIKE ? OR LOWER(plan_summary) LIKE ?)" for _ in tokens]
            sql += " WHERE " + " OR ".join(token_clauses)
            for token in tokens:
                pat = f"%{token}%"
                params.extend([pat, pat, pat])
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        results = []
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            for row in cursor.fetchall():
                results.append(self._row_to_episode(row).to_dict())
        return results

    @staticmethod
    def _row_to_episode(row: tuple) -> EpisodeRecord:
        errors = json.loads(row[9]) if row[9] else []
        return EpisodeRecord(
            episode_id=row[0],
            session_id=row[1],
            user_instruction=row[2],
            intent=row[3],
            plan_summary=row[4],
            tools_used=json.loads(row[5]) if row[5] else [],
            actions_executed=json.loads(row[6]) if row[6] else [],
            success=bool(row[7]),
            verified_evidence=json.loads(row[8]) if row[8] else {},
            errors=errors,
            resolution_notes=row[10],
            duration_ms=row[11] or 0.0,
            timestamp=row[12],
            goal=row[2],
            error_summary="; ".join(errors) if errors else None,
        )


# =========================================================================
# 3. PROCEDURAL MEMORY & REPOSITORY (MEMORIA PROCEDIMENTAL)
# =========================================================================

class ProceduralMemory(ProcedureRepository):
    """Almacén y ciclo de vida de procedimientos automatizados reutilizables."""

    def __init__(self, db_path: str = "data/memory_brain.db") -> None:
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        parent_dir = os.path.dirname(self.db_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS procedures (
                    procedure_id TEXT PRIMARY KEY,
                    name TEXT,
                    description TEXT,
                    associated_intent TEXT,
                    required_applications TEXT,
                    input_parameters TEXT,
                    preconditions TEXT,
                    steps TEXT,
                    authorized_tools TEXT,
                    success_conditions TEXT,
                    error_conditions TEXT,
                    validation_evidence TEXT,
                    version INTEGER,
                    state TEXT,
                    modification_history TEXT,
                    created_at REAL,
                    updated_at REAL,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_proc_intent ON procedures (associated_intent);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_proc_state ON procedures (state);")
            conn.commit()

    def save_procedure(self, procedure: LearnedProcedure) -> bool:
        with self._lock:
            existing = self.get_procedure(procedure.procedure_id)
            if existing is not None:
                # Si ya existe y no se especificó una versión mayor, incrementar automáticamente
                if procedure.version <= existing.version:
                    procedure.version = existing.version + 1

            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO procedures (
                        procedure_id, name, description, associated_intent, required_applications,
                        input_parameters, preconditions, steps, authorized_tools, success_conditions,
                        error_conditions, validation_evidence, version, state, modification_history,
                        created_at, updated_at, success_count, failure_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    procedure.procedure_id,
                    procedure.name,
                    procedure.description,
                    procedure.associated_intent or procedure.intent,
                    json.dumps(procedure.required_applications),
                    json.dumps(procedure.input_parameters),
                    json.dumps(procedure.preconditions),
                    json.dumps(procedure.steps),
                    json.dumps(procedure.authorized_tools),
                    json.dumps(procedure.success_conditions),
                    json.dumps(procedure.error_conditions),
                    json.dumps(procedure.validation_evidence),
                    procedure.version,
                    procedure.state.value if isinstance(procedure.state, ProcedureLifecycleState) else str(procedure.state),
                    json.dumps(procedure.modification_history),
                    procedure.created_at,
                    procedure.updated_at,
                    getattr(procedure, "success_count", 0),
                    getattr(procedure, "failure_count", 0),
                ))
                conn.commit()
            return True

    def get_procedure(self, procedure_id: str) -> LearnedProcedure | None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT procedure_id, name, description, associated_intent, required_applications,
                       input_parameters, preconditions, steps, authorized_tools, success_conditions,
                       error_conditions, validation_evidence, version, state, modification_history,
                       created_at, updated_at, success_count, failure_count
                FROM procedures WHERE procedure_id = ?;
            """, (procedure_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_procedure(row)

    def find_matching(
        self,
        intent: str,
        app_context: str | None = None,
        only_validated: bool = True,
    ) -> list[LearnedProcedure]:
        """Busca procedimientos compatibles. Por defecto retorna ÚNICAMENTE procedimientos VALIDATED."""
        tokens = [t.strip().lower() for t in intent.split() if len(t.strip()) > 2]
        query = """
            SELECT procedure_id, name, description, associated_intent, required_applications,
                   input_parameters, preconditions, steps, authorized_tools, success_conditions,
                   error_conditions, validation_evidence, version, state, modification_history,
                   created_at, updated_at, success_count, failure_count
            FROM procedures
        """
        clauses = []
        params: list[Any] = []

        if tokens:
            token_subclauses = ["(LOWER(associated_intent) LIKE ? OR LOWER(name) LIKE ?)" for _ in tokens]
            clauses.append("(" + " OR ".join(token_subclauses) + ")")
            for t in tokens:
                pat = f"%{t}%"
                params.extend([pat, pat])
        else:
            clauses.append("associated_intent = ?")
            params.append(intent)

        if only_validated:
            clauses.append("state = 'VALIDATED'")

        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY version DESC, success_count DESC"

        results = []
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            for row in cursor.fetchall():
                proc = self._row_to_procedure(row)
                if app_context:
                    if not proc.required_applications or any(app_context.lower() in app.lower() for app in proc.required_applications):
                        results.append(proc)
                else:
                    results.append(proc)
        return results

    def promote_state(
        self,
        procedure_id: str,
        new_state: ProcedureLifecycleState,
        reason: str,
    ) -> bool:
        proc = self.get_procedure(procedure_id)
        if not proc:
            return False
        with self._lock, sqlite3.connect(self.db_path) as conn:
            history = list(proc.modification_history)
            history.append({
                "timestamp": time.time(),
                "from_state": proc.state.value if isinstance(proc.state, ProcedureLifecycleState) else str(proc.state),
                "to_state": new_state.value,
                "reason": reason,
            })
            conn.execute("""
                UPDATE procedures
                SET state = ?, modification_history = ?, updated_at = ?
                WHERE procedure_id = ?;
            """, (new_state.value, json.dumps(history), time.time(), procedure_id))
            conn.commit()
        return True

    def update_lifecycle_state(
        self,
        procedure_id: str,
        new_state: ProcedureLifecycleState,
        reason: str = "",
    ) -> bool:
        """Alias ergonómico de promote_state."""
        return self.promote_state(procedure_id, new_state, reason)

    def record_execution_result(
        self,
        procedure_id: str,
        success: bool,
        evidence: dict[str, Any] | None = None,
    ) -> bool:
        """Registra el resultado de ejecución para alimentar estadísticas de validación."""
        proc = self.get_procedure(procedure_id)
        if not proc:
            return False

        with self._lock, sqlite3.connect(self.db_path) as conn:
            new_success_count = proc.success_count + (1 if success else 0)
            new_failure_count = proc.failure_count + (0 if success else 1)
            current_evidence = list(proc.validation_evidence)
            if evidence:
                current_evidence.append({
                    "timestamp": time.time(),
                    "success": success,
                    "evidence": evidence,
                })

            conn.execute("""
                UPDATE procedures
                SET success_count = ?, failure_count = ?, validation_evidence = ?, updated_at = ?
                WHERE procedure_id = ?;
            """, (new_success_count, new_failure_count, json.dumps(current_evidence), time.time(), procedure_id))
            conn.commit()
        return True

    def delete_procedure(self, procedure_id: str) -> bool:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM procedures WHERE procedure_id = ?;", (procedure_id,))
            conn.commit()
            return cursor.rowcount > 0

    def list_procedures(self, state: ProcedureLifecycleState | None = None) -> list[LearnedProcedure]:
        query = """
            SELECT procedure_id, name, description, associated_intent, required_applications,
                   input_parameters, preconditions, steps, authorized_tools, success_conditions,
                   error_conditions, validation_evidence, version, state, modification_history,
                   created_at, updated_at, success_count, failure_count
            FROM procedures
        """
        params: list[Any] = []
        if state:
            query += " WHERE state = ?"
            params.append(state.value)
        query += " ORDER BY updated_at DESC"

        procs = []
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            for row in cursor.fetchall():
                procs.append(self._row_to_procedure(row))
        return procs

    @staticmethod
    def _row_to_procedure(row: tuple) -> LearnedProcedure:
        raw_state = row[13]
        try:
            state = ProcedureLifecycleState(raw_state)
        except ValueError:
            state = ProcedureLifecycleState.CANDIDATE

        success_count = row[17] if len(row) > 17 and row[17] is not None else 0
        failure_count = row[18] if len(row) > 18 and row[18] is not None else 0

        val_evidence = json.loads(row[11]) if row[11] else []
        last_val_time = None
        if val_evidence:
            timestamps = [e.get("timestamp") for e in val_evidence if isinstance(e, dict) and e.get("timestamp")]
            if timestamps:
                last_val_time = max(timestamps)
        if last_val_time is None and state == ProcedureLifecycleState.VALIDATED:
            last_val_time = row[16]

        return LearnedProcedure(
            procedure_id=row[0],
            name=row[1],
            description=row[2] or "",
            associated_intent=row[3] or "",
            required_applications=json.loads(row[4]) if row[4] else [],
            input_parameters=json.loads(row[5]) if row[5] else {},
            preconditions=json.loads(row[6]) if row[6] else [],
            steps=json.loads(row[7]) if row[7] else [],
            authorized_tools=json.loads(row[8]) if row[8] else [],
            success_conditions=json.loads(row[9]) if row[9] else [],
            error_conditions=json.loads(row[10]) if row[10] else [],
            validation_evidence=val_evidence,
            version=row[12],
            state=state,
            modification_history=json.loads(row[14]) if row[14] else [],
            created_at=row[15],
            updated_at=row[16],
            last_validated_at=last_val_time,
            approval_status="APPROVED" if state == ProcedureLifecycleState.VALIDATED else "PROPOSED",
            intent=row[3] or "",
            expected_outcome=row[2] or "",
            success_count=success_count,
            failure_count=failure_count,
        )


# =========================================================================
# 4. UNIFIED MEMORY ENGINE (ORQUESTADOR CENTRAL DE MEMORIA COGNITIVA)
# =========================================================================

class MemoryEngine(MemoryProvider):
    """Cerebro de memoria unificado que implementa MemoryProvider y conecta
    Working, Episodic, Semantic y Procedural Memory.
    """

    _instance: ClassVar[MemoryEngine | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        storage_dir: str = "data/memory_long_term",
        db_path: str = "data/memory_brain.db",
        emergency_stop: EmergencyStopManager | None = None,
        long_term_dir: str | None = None,
    ) -> None:
        actual_storage = str(long_term_dir) if long_term_dir else str(storage_dir)
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self.working_memory = WorkingMemory()
        self.episodic_memory = EpisodicMemory(db_path=db_path)
        self.procedural_memory = ProceduralMemory(db_path=db_path)
        # Reutiliza LongTermMemoryEngine de forma atómica y no destructiva
        self.semantic_memory_engine = LongTermMemoryEngine(
            storage_dir=actual_storage,
            emergency_stop=self.emergency_stop,
        )
        self._lock = threading.RLock()

    @classmethod
    def get_instance(
        cls,
        storage_dir: str = "data/memory_long_term",
        db_path: str = "data/memory_brain.db",
        long_term_dir: str | None = None,
    ) -> MemoryEngine:
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = MemoryEngine(storage_dir=storage_dir, db_path=db_path, long_term_dir=long_term_dir)
            return cls._instance

    # ── CONTRATO WORKING MEMORY ──

    def get_working_memory(self, session_id: str) -> dict[str, Any]:
        return self.working_memory.get_state(session_id).to_dict()

    get_working_context = get_working_memory

    def update_working_memory(self, session_id: str, updates: dict[str, Any]) -> None:
        self.working_memory.update(session_id, updates)

    # ── CONTRATO EPISODIC MEMORY ──

    def record_episode(self, episode: EpisodeRecord | dict[str, Any]) -> str:
        return self.episodic_memory.record_episode(episode)

    # ── CONTRATO SEMANTIC MEMORY ──

    @staticmethod
    def _sanitize_and_redact_input(text: str) -> tuple[str, bool]:
        """Neutraliza inyecciones de instrucciones y redacta secretos antes de persistir."""
        sanitized = text
        flagged = False

        # 1. Neutralización de Prompt Injection (Invariante: Memory is Not Authority)
        injection_patterns = [
            re.compile(r"(system\s+override|ignore\s+all\s+previous\s+instructions|DAN\s+jailbreak)", re.IGNORECASE),
            re.compile(r"(grant\s+root\s+admin|bypass\s+security\s+pipeline|override\s+permission)", re.IGNORECASE),
            re.compile(r"(\[INST\]|\[/INST\])", re.IGNORECASE),
        ]
        for pat in injection_patterns:
            if pat.search(sanitized):
                flagged = True
                sanitized = pat.sub("[FLAGGED_POTENTIAL_INJECTION]", sanitized)

        # 2. Redacción preventiva de secretos (Privacy By Design)
        # Claves API tipo OpenAI/Anthropic: sk-ant-..., sk-proj-..., sk-...
        sanitized = re.sub(r"\b(sk-[a-zA-Z0-9_\-]{20,})\b", "[REDACTED_API_KEY]", sanitized)
        # Tokens GitHub
        sanitized = re.sub(r"\b(gh[pousr][_A-Za-z0-9]{20,})\b", "[REDACTED_GITHUB_TOKEN]", sanitized)
        # Bearer tokens
        sanitized = re.sub(r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{15,}", r"\1[REDACTED_TOKEN]", sanitized)
        # Contraseñas asignadas: password es SuperSecret123!, password: foo, password=foo
        sanitized = re.sub(r"(?i)\b(password|passwd|pwd|contrase[ñn]a|clave)\s*(?:es|[:=])\s*['\"]?([^\s'\"]+)['\"]?", r"\1: [REDACTED_PASSWORD]", sanitized)
        sanitized = re.sub(
            r"(?i)\b(contrase[ñn]a|password|clave)\s+(?:bancaria|del banco|de wifi|del wifi)\s+(?:(?:es|[:=])\s*)?[^\s'\"]+",
            r"\1: [REDACTED_PASSWORD]", sanitized,
        )
        # API Keys asignadas: api_key: foo, api key es foo
        sanitized = re.sub(r"(?i)\b(api[-_]?key|secret[-_]?token)\s*(?:es|[:=])\s*['\"]?([^\s'\"]+)['\"]?", r"\1: [REDACTED_SECRET]", sanitized)

        return sanitized, flagged

    def store_semantic_fact(
        self,
        fact: str,
        category: str = "USER_PREFERENCES",
        confidence: float = 1.0,
        source: str = "user_conversation",
        sensitivity: MemorySensitivity = MemorySensitivity.INTERNAL,
    ) -> str:
        """Almacena un hecho semántico validado contra inyecciones y redactando secretos."""
        cleaned_fact, flagged = self._sanitize_and_redact_input(fact)
        rec_type = MemoryRecordType.USER_PREFERENCES if category.upper() in ("USER_PREFERENCES", "PREFERENCE") else MemoryRecordType.SEMANTIC_MEMORY
        rec = self.semantic_memory_engine.store_record(
            content=cleaned_fact,
            record_type=rec_type,
            source=source,
            confidence=confidence,
            sensitivity=sensitivity,
            provenance={"flagged": flagged, "source": source},
        )
        if rec and flagged:
            setattr(rec, "flagged", True)
        return rec.id if rec else ""

    def remember_fact(
        self,
        key_or_name: str,
        fact: str,
        category: str = "fact",
        confidence: float = 1.0,
    ) -> str:
        """Alias ergonómico para registrar un hecho semántico."""
        return self.store_semantic_fact(
            fact=f"{key_or_name}: {fact}" if key_or_name and not fact.startswith(f"{key_or_name}:") else fact,
            category="USER_PREFERENCES" if category in ("preference", "user_preferences") else "SEMANTIC_MEMORY",
            confidence=confidence,
        )

    def recall_facts(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Recupera hechos semánticos ordenados por relevancia léxica, confianza y recencia."""
        return self.recall_semantic_facts(query, limit=limit)

    def recall_semantic_facts(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        results = self.semantic_memory_engine.retrieve_records(query=query, limit=limit)
        facts = []
        for r in results:
            rec = r["record"]
            flagged = getattr(rec, "flagged", False) or rec.provenance.get("flagged", False) or "[FLAGGED_POTENTIAL_INJECTION]" in rec.content
            facts.append({
                "fact_id": rec.id,
                "content": rec.content,
                "type": rec.type.value,
                "confidence": r["effective_confidence"],
                "total_rank": r["total_rank"],
                "timestamp": rec.timestamp,
                "flagged": flagged,
            })
        return facts

    # ── CONTRATO PROCEDURAL MEMORY ──

    def learn_procedure(self, procedure: LearnedProcedure) -> bool:
        """Registra o actualiza un procedimiento en la memoria procedimental."""
        return self.procedural_memory.save_procedure(procedure)

    # ── CONTRATO CONTEXT RETRIEVAL (RECUPERACIÓN CONTEXTUAL CONDENSADA) ──

    def retrieve_context(
        self,
        query: str = "",
        active_task_id: str | None = None,
        session_id: str = "default",
        intent: str | None = None,
        token_budget: int = 2000,
    ) -> ContextBundle:
        """Recupera únicamente el contexto relevante sin saturar el prompt."""
        search_query = query or intent or ""
        # 1. Working Memory
        working = self.get_working_memory(session_id)

        # 2. Hechos semánticos relevantes
        relevant_memories = self.recall_semantic_facts(search_query, limit=4) if search_query else []

        # 3. Episodios relevantes
        episodic_examples = self.episodic_memory.find_relevant_episodes(search_query, limit=3) if search_query else []

        # 4. Procedimientos validados relevantes (SOLO VALIDATED por defecto)
        procedural_candidates: list[LearnedProcedure] = []
        effective_intent = intent or query
        if effective_intent:
            procedural_candidates = self.procedural_memory.find_matching(
                intent=effective_intent,
                only_validated=True,
            )

        return ContextBundle(
            working_context=working,
            relevant_memories=relevant_memories,
            procedural_candidates=procedural_candidates,
            untrusted_documents=[],
            episodic_examples=episodic_examples,
        )

    # ── MÉTODOS DE GOBERNANZA, PRIVACIDAD Y BORRADO ──

    def forget_memory(self, identifier_or_content: str | None = None, memory_id: str | None = None) -> bool:
        """Elimina un recuerdo específico por ID o por coincidencia exacta a solicitud del usuario."""
        target_id = memory_id or identifier_or_content
        if not target_id:
            return False

        with self._lock:
            for r_id, rec in list(self.semantic_memory_engine._records.items()):
                if r_id == target_id or rec.content.lower().strip() == target_id.lower().strip():
                    return self.semantic_memory_engine.delete_record(r_id)
            return False

    def export_all(self, target_dir: str) -> dict[str, int]:
        """Exporta de forma segura el estado de memoria estructurada para respaldos."""
        os.makedirs(target_dir, exist_ok=True)
        # Exportar procedimientos
        procs = self.procedural_memory.list_procedures()
        procs_file = os.path.join(target_dir, "procedures_export.json")
        with open(procs_file, "w", encoding="utf-8") as f:
            json.dump([asdict(p) for p in procs], f, indent=2, ensure_ascii=False)

        # Contar registros semánticos
        semantic_count = len(self.semantic_memory_engine._records)
        return {"procedures_exported": len(procs), "semantic_records": semantic_count}
