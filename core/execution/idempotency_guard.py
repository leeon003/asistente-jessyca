"""Mecanismo de idempotencia, deduplicación y trazabilidad de ejecuciones (idempotency_guard.py).

Garantiza la regla fundamental:
    1 USER REQUEST -> 1 EXECUTION INTENT -> 1 ACTION INVOCATION -> VERIFICATION -> RESULT

Previene la ejecución duplicada o redundante de acciones sobre el sistema operativo,
proporcionando un registro estructurado con huella digital (ExecutionFingerprint).
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.core.execution.idempotency_guard")


@dataclass(frozen=True)
class ExecutionFingerprint:
    """Huella digital inmutable de una intención de ejecución."""

    session_id: str
    request_id: str
    intent: str
    skill: str
    action: str
    target: str
    attempt_number: int = 1
    created_at: float = field(default_factory=time.time)

    def compute_hash(self) -> str:
        """Calcula el hash determinista SHA-256 de la petición."""
        norm_target = (self.target or "").strip().lower()
        norm_action = (self.action or "").strip().lower()
        norm_intent = (self.intent or "").strip().lower()
        norm_skill = (self.skill or "").strip().lower()
        raw = f"{self.session_id}:{self.request_id}:{norm_intent}:{norm_skill}:{norm_action}:{norm_target}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class ExecutionRecord:
    """Registro de ciclo de vida de una ejecución auditable."""

    execution_id: str
    fingerprint: ExecutionFingerprint
    invocation_timestamp: float
    execution_timestamp: float | None = None
    verification_timestamp: float | None = None
    attempt_number: int = 1
    actual_execution_count: int = 0
    is_reused_instance: bool = False
    status: str = "IN_PROGRESS"  # IN_PROGRESS, SUCCEEDED, FAILED, DUPLICATE_BLOCKED, VERIFICATION_FAILED
    result_message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "session_id": self.fingerprint.session_id,
            "request_id": self.fingerprint.request_id,
            "intent": self.fingerprint.intent,
            "skill": self.fingerprint.skill,
            "action": self.fingerprint.action,
            "target": self.fingerprint.target,
            "attempt_number": self.attempt_number,
            "invocation_timestamp": self.invocation_timestamp,
            "execution_timestamp": self.execution_timestamp,
            "verification_timestamp": self.verification_timestamp,
            "actual_execution_count": self.actual_execution_count,
            "is_reused_instance": self.is_reused_instance,
            "status": self.status,
            "result_message": self.result_message,
            "details": self.details,
        }


class ExecutionIdempotencyGuard:
    """Guardián de idempotencia y trazabilidad de ejecuciones."""

    _instance: ExecutionIdempotencyGuard | None = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._mutex = threading.Lock()
        self._records: dict[str, ExecutionRecord] = {}
        self._hash_to_execution_id: dict[str, str] = {}

    @classmethod
    def get_instance(cls) -> ExecutionIdempotencyGuard:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def acquire_execution(
        self,
        fingerprint: ExecutionFingerprint,
    ) -> tuple[bool, ExecutionRecord]:
        """Intenta adquirir el derecho de ejecución para una huella digital.

        Returns:
            tuple[bool, ExecutionRecord]:
                - (True, new_record) si la ejecución fue adquirida exitosamente.
                - (False, existing_record) si la ejecución fue bloqueada por ser duplicada.
        """
        f_hash = fingerprint.compute_hash()
        with self._mutex:
            if f_hash in self._hash_to_execution_id:
                exec_id = self._hash_to_execution_id[f_hash]
                existing = self._records.get(exec_id)
                if existing and existing.status in ("IN_PROGRESS", "SUCCEEDED"):
                    logger.warning(
                        f"[IDEMPOTENCY DUPLICATE BLOCKED] Petición duplicada bloqueada | "
                        f"execution_id={existing.execution_id} request_id={fingerprint.request_id} "
                        f"intent={fingerprint.intent} target={fingerprint.target} status={existing.status}"
                    )
                    return False, existing

            # Registrar nueva ejecución autorizada
            exec_id = f"exec_{uuid.uuid4().hex[:12]}"
            now = time.time()
            record = ExecutionRecord(
                execution_id=exec_id,
                fingerprint=fingerprint,
                invocation_timestamp=now,
                attempt_number=fingerprint.attempt_number,
                status="IN_PROGRESS",
            )
            self._records[exec_id] = record
            self._hash_to_execution_id[f_hash] = exec_id

            logger.info(
                f"[EXECUTION REGISTERED] execution_id={exec_id} request_id={fingerprint.request_id} "
                f"session_id={fingerprint.session_id} intent={fingerprint.intent} skill={fingerprint.skill} "
                f"target_application={fingerprint.target} attempt_number={fingerprint.attempt_number}"
            )
            return True, record

    def record_execution_invoked(
        self,
        execution_id: str,
        count: int = 1,
        is_reused: bool = False,
    ) -> None:
        """Registra que la acción fue efectivamente invocada a nivel del sistema operativo."""
        with self._mutex:
            rec = self._records.get(execution_id)
            if rec:
                rec.execution_timestamp = time.time()
                rec.actual_execution_count += count
                rec.is_reused_instance = is_reused

    def record_verification_completed(
        self,
        execution_id: str,
        status: str,
        result_message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Registra el resultado de la verificación determinista y emite log estructurado."""
        with self._mutex:
            rec = self._records.get(execution_id)
            if not rec:
                return
            rec.verification_timestamp = time.time()
            rec.status = status
            rec.result_message = result_message
            if details:
                rec.details.update(details)

        # Log estructurado conforme a la especificación
        t_exec_str = f"{rec.execution_timestamp:.4f}" if rec.execution_timestamp else "N/A"
        t_verif_str = f"{rec.verification_timestamp:.4f}" if rec.verification_timestamp else "N/A"
        logger.info(
            f"[EXECUTION AUDIT] execution_id={rec.execution_id} "
            f"request_id={rec.fingerprint.request_id} "
            f"session_id={rec.fingerprint.session_id} "
            f"intent={rec.fingerprint.intent} "
            f"skill={rec.fingerprint.skill} "
            f"target_application={rec.fingerprint.target} "
            f"attempt_number={rec.attempt_number} "
            f"invocation_timestamp={rec.invocation_timestamp:.4f} "
            f"execution_timestamp={t_exec_str} "
            f"verification_timestamp={t_verif_str} "
            f"actual_execution_count={rec.actual_execution_count} "
            f"is_reused={rec.is_reused_instance} "
            f"result={rec.status}"
        )

    def get_record(self, execution_id: str) -> ExecutionRecord | None:
        with self._mutex:
            return self._records.get(execution_id)

    def get_records_for_session(self, session_id: str) -> list[ExecutionRecord]:
        with self._mutex:
            return [r for r in self._records.values() if r.fingerprint.session_id == session_id]

    def get_all_records(self) -> list[ExecutionRecord]:
        with self._mutex:
            return list(self._records.values())

    def reset(self) -> None:
        """Reinicia el estado en memoria para aislamiento de pruebas unitarias."""
        with self._mutex:
            self._records.clear()
            self._hash_to_execution_id.clear()


def get_idempotency_guard() -> ExecutionIdempotencyGuard:
    """Función de acceso singleton al guardián de idempotencia."""
    return ExecutionIdempotencyGuard.get_instance()
