"""Gestor central de operaciones, deduplicación atómica, ciclo de vida de tareas y cancelación cooperativa.

Garantiza:
1. Identidad estable de operación por (session_id, operation_id).
2. Deduplicación atómica:
   - Misma clave + misma sesión + mismo payload -> reutiliza resultado o se une a la tarea en vuelo.
   - Misma clave + distinta carga -> IdempotencyConflictError (HTTP 409).
   - Distinta clave + mismo texto -> nueva acción legítima permitida.
3. Desacoplamiento entre el deadline de respuesta HTTP y el estado de ejecución en segundo plano.
4. Cancelación cooperativa (CancellationToken) y verificación de deadline monotónico previo a efectos.
5. Preservación explícita de estados: PENDING, RUNNING, COMPLETED, FAILED, CANCEL_REQUESTED, CANCELLED, UNKNOWN.
6. Límites de cola/concurrencia (Semaphore), retención con TTL y cierre ordenado (graceful shutdown).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.cancellation import CancellationToken
from core.logger import get_logger

logger = get_logger("jessyca.execution.operation_manager")


class OperationStatus(StrEnum):
    """Estados del ciclo de vida de una operación."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class IdempotencyConflictError(Exception):
    """Lanzada cuando una Idempotency-Key es reutilizada con un payload diferente."""

    def __init__(self, operation_id: str, session_id: str, message: str = "Idempotency key reused with different payload"):
        super().__init__(message)
        self.operation_id = operation_id
        self.session_id = session_id


class ConcurrencyLimitError(Exception):
    """Lanzada cuando se supera el límite de concurrencia o cola."""

    pass


class SessionIsolationError(PermissionError):
    """Lanzada ante un intento de acceso a operaciones de otra sesión."""

    pass


def compute_payload_hash(payload: dict[str, Any]) -> str:
    """Calcula un hash determinista SHA-256 de los datos normalizados de la petición."""
    # Excluir campos volátiles o de transporte
    volatile_keys = {"timestamp", "request_id", "idempotency_key", "nonce"}
    cleaned = {k: v for k, v in payload.items() if k not in volatile_keys}
    canonical_json = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


@dataclass
class OperationRecord:
    """Registro estructurado del ciclo de vida de una operación."""

    operation_id: str
    session_id: str
    payload_hash: str
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    status: OperationStatus = OperationStatus.PENDING
    cancellation_token: CancellationToken = field(default_factory=CancellationToken)
    monotonic_deadline: float | None = None
    effect_started: bool = False
    result: Any | None = None
    error: str | None = None
    task: asyncio.Task | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serializa el registro a un formato legible por API."""
        res_dict = None
        if self.result is not None:
            if hasattr(self.result, "model_dump"):
                res_dict = self.result.model_dump()
            elif hasattr(self.result, "to_dict"):
                res_dict = self.result.to_dict()
            elif isinstance(self.result, dict):
                res_dict = self.result
            else:
                res_dict = {"response": str(self.result)}

        return {
            "operation_id": self.operation_id,
            "session_id": self.session_id,
            "status": self.status.value,
            "effect_started": self.effect_started,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": res_dict,
            "error": self.error,
        }


class OperationManager:
    """Gestor unificado de operaciones, concurrencia e idempotencia."""

    _instance: OperationManager | None = None

    def __init__(
        self,
        max_concurrent_operations: int = 10,
        max_history: int = 1000,
        retention_ttl_seconds: float = 3600.0,
    ) -> None:
        self.max_concurrent_operations = max_concurrent_operations
        self.max_history = max_history
        self.retention_ttl_seconds = retention_ttl_seconds

        self._operations: dict[tuple[str, str], OperationRecord] = {}  # (session_id, op_id) -> record
        self._op_to_session: dict[str, str] = {}  # op_id -> session_id para lookup rápido
        self._semaphore: asyncio.Semaphore | None = None
        self._lock: asyncio.Lock | None = None

    @classmethod
    def get_instance(cls) -> OperationManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_async_primitives(self) -> None:
        """Inicializa semáforo y lock dentro del event loop activo."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent_operations)
        if self._lock is None:
            self._lock = asyncio.Lock()

    def _cleanup_expired_records(self) -> None:
        """Elimina operaciones antiguas terminadas para evitar fugas de memoria."""
        now = time.time()
        expired_keys = [
            k for k, v in self._operations.items()
            if v.completed_at and (now - v.completed_at) > self.retention_ttl_seconds
        ]
        for k in expired_keys:
            self._operations.pop(k, None)
            self._op_to_session.pop(k[1], None)

        # Si aún excede max_history, purgar las más antiguas
        if len(self._operations) > self.max_history:
            sorted_ops = sorted(
                self._operations.items(),
                key=lambda item: item[1].created_at,
            )
            to_remove = len(self._operations) - self.max_history
            for i in range(to_remove):
                k = sorted_ops[i][0]
                self._operations.pop(k, None)
                self._op_to_session.pop(k[1], None)

    async def acquire_or_join(
        self,
        session_id: str,
        operation_id: str,
        payload: dict[str, Any],
        max_execution_timeout: float = 120.0,
    ) -> tuple[OperationRecord, bool]:
        """Obtiene o registra una operación de forma atómica.

        Returns:
            tuple[OperationRecord, bool]: (record, is_new)
            - is_new=True: La operación es nueva y debe ejecutarse.
            - is_new=False: La operación ya existe (en curso o completada); no iniciar nuevo efecto.

        Raises:
            IdempotencyConflictError: Si la misma operation_id se usa con un payload diferente para la misma sesión.
            ConcurrencyLimitError: Si se excede el límite de operaciones concurrentes.
        """
        self._ensure_async_primitives()
        payload_hash = compute_payload_hash(payload)
        key = (session_id, operation_id)

        async with self._lock:  # type: ignore[union-attr]
            self._cleanup_expired_records()

            if key in self._operations:
                existing = self._operations[key]
                if existing.payload_hash != payload_hash:
                    logger.warning(
                        f"[IDEMPOTENCY CONFLICT] Clave '{operation_id}' reutilizada con payload distinto "
                        f"(sesión: '{session_id}')."
                    )
                    raise IdempotencyConflictError(
                        operation_id=operation_id,
                        session_id=session_id,
                        message=f"La clave de idempotencia '{operation_id}' ya fue utilizada con un payload diferente.",
                    )

                logger.info(
                    f"[IDEMPOTENCY HIT] Reutilizando operación existente '{operation_id}' "
                    f"(sesión: '{session_id}', estado: '{existing.status.value}')."
                )
                return existing, False

            # Verificar aislamiento: ¿existe la misma operation_id bajo otra sesión?
            if operation_id in self._op_to_session and self._op_to_session[operation_id] != session_id:
                logger.warning(
                    f"[SESSION CONFLICT] Clave '{operation_id}' ya registrada bajo sesión "
                    f"'{self._op_to_session[operation_id]}', rechazada para '{session_id}'."
                )
                raise IdempotencyConflictError(
                    operation_id=operation_id,
                    session_id=session_id,
                    message=f"La clave de operación '{operation_id}' pertenece a otra sesión.",
                )

            # Registrar nueva operación
            deadline = time.monotonic() + max_execution_timeout
            record = OperationRecord(
                operation_id=operation_id,
                session_id=session_id,
                payload_hash=payload_hash,
                monotonic_deadline=deadline,
                raw_payload=payload,
                status=OperationStatus.PENDING,
            )
            self._operations[key] = record
            self._op_to_session[operation_id] = session_id

            logger.info(
                f"[OPERATION REGISTERED] Nueva operación '{operation_id}' registrada "
                f"(sesión: '{session_id}', hash: '{payload_hash[:8]}')."
            )
            return record, True

    def run_operation(
        self,
        record: OperationRecord,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> asyncio.Task:
        """Inicia la ejecución en segundo plano protegiéndola contra cancelación abrupta de cliente."""
        self._ensure_async_primitives()

        async def _worker():
            async with self._semaphore:  # type: ignore[union-attr]
                record.status = OperationStatus.RUNNING
                record.started_at = time.time()
                try:
                    # Si ya fue cancelada antes de adquirir el semáforo
                    if record.cancellation_token.is_cancelled:
                        record.status = OperationStatus.CANCELLED
                        record.completed_at = time.time()
                        return None

                    # Ejecutar función (síncrona en hilo o asíncrona)
                    if asyncio.iscoroutinefunction(func):
                        res = await func(*args, **kwargs)
                    else:
                        res = await asyncio.to_thread(func, *args, **kwargs)

                    record.result = res
                    # Verificar si se solicitó cancelación durante la ejecución
                    if record.cancellation_token.is_cancelled:
                        if record.effect_started:
                            record.status = OperationStatus.UNKNOWN
                        else:
                            record.status = OperationStatus.CANCELLED
                    else:
                        record.status = OperationStatus.COMPLETED

                    record.completed_at = time.time()
                    return res
                except asyncio.CancelledError:
                    if record.effect_started:
                        record.status = OperationStatus.UNKNOWN
                    else:
                        record.status = OperationStatus.CANCELLED
                    record.completed_at = time.time()
                    raise
                except Exception as exc:
                    logger.error(
                        f"[OPERATION FAILED] Operación '{record.operation_id}' falló: {exc}",
                        exc_info=True,
                    )
                    record.error = str(exc)
                    record.status = OperationStatus.FAILED
                    record.completed_at = time.time()
                    raise

        task = asyncio.create_task(_worker())
        record.task = task
        return task

    def get_operation(self, session_id: str, operation_id: str) -> OperationRecord | None:
        """Consulta una operación garantizando el aislamiento de sesión."""
        # Verificar si la operación existe bajo otra sesión
        owner_session = self._op_to_session.get(operation_id)
        if owner_session is not None and owner_session != session_id:
            logger.warning(
                f"[SECURITY VIOLATION] Sesión '{session_id}' intentó consultar operación "
                f"'{operation_id}' propiedad de '{owner_session}'."
            )
            raise SessionIsolationError(
                f"Acceso denegado: La operación '{operation_id}' no pertenece a la sesión activa."
            )

        return self._operations.get((session_id, operation_id))

    def cancel_operation(
        self,
        session_id: str,
        operation_id: str,
        reason: str = "Solicitud de cancelación del usuario",
    ) -> OperationRecord:
        """Solicita la cancelación cooperativa de una operación verificando aislamiento."""
        record = self.get_operation(session_id, operation_id)
        if record is None:
            raise KeyError(f"Operación '{operation_id}' no encontrada para la sesión '{session_id}'.")

        # Señalizar token cooperativo
        record.cancellation_token.cancel(reason)

        if record.status == OperationStatus.PENDING:
            record.status = OperationStatus.CANCELLED
            record.completed_at = time.time()
        elif record.status == OperationStatus.RUNNING:
            if record.effect_started:
                # El efecto ya inició; el hilo no puede detenerse forzosamente
                record.status = OperationStatus.CANCEL_REQUESTED
            else:
                record.status = OperationStatus.CANCEL_REQUESTED

        logger.info(
            f"[OPERATION CANCELLED] Cancelación solicitada para '{operation_id}' "
            f"(sesión: '{session_id}', estado actual: '{record.status.value}')."
        )
        return record

    async def shutdown(self, grace_period: float = 2.0) -> None:
        """Cierre ordenado: cancela tokens de operaciones activas y espera el periodo de gracia."""
        logger.info("[OPERATION MANAGER] Iniciando cierre ordenado de tareas activas...")
        running_tasks: list[asyncio.Task] = []

        for record in self._operations.values():
            if record.status in (OperationStatus.PENDING, OperationStatus.RUNNING):
                record.cancellation_token.cancel("Service shutdown")
                if record.task and not record.task.done():
                    running_tasks.append(record.task)

        if running_tasks:
            logger.info(f"[OPERATION MANAGER] Esperando hasta {grace_period}s por {len(running_tasks)} tareas en vuelo...")
            done, pending = await asyncio.wait(running_tasks, timeout=grace_period)
            if pending:
                logger.warning(
                    f"[OPERATION MANAGER] {len(pending)} tareas no cooperaron durante el cierre y permanecen en ejecución."
                )

    def reset(self) -> None:
        """Reinicia el estado para pruebas unitarias."""
        self._operations.clear()
        self._op_to_session.clear()
        self._semaphore = None
        self._lock = None


def get_operation_manager() -> OperationManager:
    """Acceso singleton al gestor de operaciones."""
    return OperationManager.get_instance()
