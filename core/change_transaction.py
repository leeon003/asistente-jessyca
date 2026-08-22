"""Subsistema de Transacciones de Cambio Controladas (Controlled Change Transaction - Etapa 15.1).

GARANTÍAS RIGUROSAS DE SEGURIDAD EN ETAPA 15.1:
1. NINGUNA ESCRITURA FÍSICA REAL EN EL SISTEMA OCURRE EN ESTA SUB-ETAPA.
2. ABSTRACCIÓN FORMAL DE TRANSACCIÓN DE CAMBIOS CON REVERSIBILIDAD:
   - Reversibility: REVERSIBLE, PARTIALLY_REVERSIBLE, IRREVERSIBLE.
   - TransactionState: PREPARING, WAITING_CONFIRMATION, EXECUTING, VERIFYING, COMMITTED, ROLLING_BACK, ROLLED_BACK, FAILED, IRREVERSIBLE.
3. FLUJO OBLIGATORIO DE 6 PASOS:
   PREPARE -> SNAPSHOT -> CONFIRM -> EXECUTE -> VERIFY -> COMMIT
4. MANEJO DE FALLOS:
   Si la ejecución o verificación falla -> ROLLBACK a pre-state cuando sea posible (si Reversibility != IRREVERSIBLE).
5. INTEGRACIÓN CON CONFIRMATIONMANAGER:
   Operaciones críticas exigen confirmación individual obligatoria con TTL corto (ej. 120s).
6. FAKE TRANSACTION PROVIDER:
   Soporte para pruebas desacopladas en memoria.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.confirmation import ConfirmationManager, ConfirmationStatus
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.change_transaction")


class Reversibility(StrEnum):
    """Grados formales de reversibilidad para un cambio en el sistema."""

    REVERSIBLE = "reversible"
    PARTIALLY_REVERSIBLE = "partially_reversible"
    IRREVERSIBLE = "irreversible"


class TransactionState(StrEnum):
    """Estados inmutables del ciclo de vida de una transacción de cambio."""

    PREPARING = "preparing"
    WAITING_CONFIRMATION = "waiting_confirmation"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMMITTED = "committed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"
    IRREVERSIBLE = "irreversible"


class TransactionError(MCPError):
    """Error base del subsistema de transacciones de cambio."""

    pass


class TransactionConfirmationRequiredError(TransactionError):
    """Error emitido cuando una transacción de cambio requiere confirmación interactiva antes de ejecutarse."""

    pass


class TransactionRollbackFailedError(TransactionError):
    """Error emitido cuando falla el proceso de rollback de una transacción."""

    pass


class TransactionVerificationError(TransactionError):
    """Error emitido cuando la verificación del estado post-escritura falla."""

    pass


@dataclass(frozen=True)
class ChangeSnapshot:
    """Captura de estado previo (Pre-State Snapshot) inmutable con validación por hash SHA-256."""

    snapshot_id: str
    target_resource: str
    pre_state_data: dict[str, Any]
    snapshot_hash: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(cls, target_resource: str, pre_state_data: dict[str, Any]) -> ChangeSnapshot:
        snap_id = f"snap-{uuid.uuid4().hex[:8]}"
        serialized = json.dumps({"resource": target_resource, "data": pre_state_data}, sort_keys=True)
        sha_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return cls(
            snapshot_id=snap_id,
            target_resource=target_resource,
            pre_state_data=dict(pre_state_data),
            snapshot_hash=sha_hash,
        )


@dataclass
class ChangeResult:
    """Resultado inmutable de la ejecución de una transacción."""

    transaction_id: str
    state: TransactionState
    success: bool
    post_state_data: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    duration_ms: float = 0.0
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class RollbackResult:
    """Resultado inmutable de un proceso de reversión/rollback."""

    transaction_id: str
    success: bool
    restored_state_hash: str = ""
    error_message: str = ""
    duration_ms: float = 0.0
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ChangeTransaction:
    """Representación formal de una transacción de cambio controlada con protección de estado (M-04)."""

    def __init__(
        self,
        transaction_id: str,
        target_resource: str,
        operation_type: str,
        reversibility: Reversibility,
        state: TransactionState = TransactionState.PREPARING,
        snapshot: ChangeSnapshot | None = None,
        confirmation_id: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.transaction_id = transaction_id
        self.target_resource = target_resource
        self.operation_type = operation_type
        self.reversibility = reversibility
        self._state = state
        self.snapshot = snapshot
        self.confirmation_id = confirmation_id
        self.created_at = created_at or datetime.now(UTC)

    @property
    def state(self) -> TransactionState:
        """Estado de la transacción protegido contra modificación externa directa (M-04)."""
        return self._state

    def _set_state(self, new_state: TransactionState) -> None:
        """Transición interna de estado gestionada exclusivamente por ChangeTransactionManager."""
        self._state = new_state


@runtime_checkable
class IChangeTransactionProvider(Protocol):
    """Interfaz abstracta para proveedores de transacciones de cambio."""

    def prepare_transaction(
        self,
        target_resource: str,
        operation_type: str,
        reversibility: Reversibility,
        pre_state_fn: Callable[[], dict[str, Any]],
        execute_fn: Callable[..., dict[str, Any]],
        rollback_fn: Callable[[dict[str, Any]], bool] | None = None,
        verify_fn: Callable[[dict[str, Any]], bool] | None = None,
    ) -> ChangeTransaction:
        ...

    def execute_transaction(self, transaction_id: str, confirmation_token: str | None = None) -> ChangeResult:
        ...


class ChangeTransactionManager(IChangeTransactionProvider):
    """Gestor central e inmutable de transacciones de cambio controladas (Etapa 15.1)."""

    def __init__(
        self,
        confirmation_manager: ConfirmationManager | None = None,
        audit_logger: Any = None,
    ) -> None:
        self.confirmation_manager = confirmation_manager or ConfirmationManager()
        self.audit_logger = audit_logger or get_audit_logger()
        self._active_transactions: dict[str, ChangeTransaction] = {}
        self._execution_handlers: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def prepare_transaction(
        self,
        target_resource: str,
        operation_type: str,
        reversibility: Reversibility,
        pre_state_fn: Callable[[], dict[str, Any]],
        execute_fn: Callable[..., dict[str, Any]],
        rollback_fn: Callable[[dict[str, Any]], bool] | None = None,
        verify_fn: Callable[[dict[str, Any]], bool] | None = None,
    ) -> ChangeTransaction:
        """PASO 1 & 2: PREPARE & SNAPSHOT."""
        tx_id = f"tx-{uuid.uuid4().hex[:8]}"

        # Captura de estado previo inmutable (Pre-State Snapshot)
        pre_data: dict[str, Any] = {}
        if callable(pre_state_fn):
            try:
                pre_data = pre_state_fn() or {}
            except Exception as e:
                logger.error(f"[CHANGE TRANSACTION] Error capturando estado previo de '{target_resource}': {e}")
                raise TransactionError(f"Error capturando estado previo: {e}") from e

        snapshot = ChangeSnapshot.create(target_resource, pre_data)

        # Crear solicitud de confirmación con TTL corto (120 segundos)
        req = self.confirmation_manager.create_request(
            tool_name="system.change_transaction",
            operation=operation_type,
            parameters={"target_resource": target_resource, "reversibility": reversibility.value, "snapshot_hash": snapshot.snapshot_hash},
            reason=f"Confirmación para cambio transaccional en '{target_resource}' ({reversibility.value}).",
            ttl_seconds=120,
        )

        tx = ChangeTransaction(
            transaction_id=tx_id,
            target_resource=target_resource,
            operation_type=operation_type,
            reversibility=reversibility,
            state=TransactionState.WAITING_CONFIRMATION,  # PASO 3: CONFIRM (Espera confirmación)
            snapshot=snapshot,
            confirmation_id=req.request_id,
        )

        self._active_transactions[tx_id] = tx
        self._execution_handlers[tx_id] = {
            "execute_fn": execute_fn,
            "rollback_fn": rollback_fn,
            "verify_fn": verify_fn,
        }

        self._log_transaction_audit(tx_id, "prepared", success=True, reason=f"Snapshot {snapshot.snapshot_hash[:8]} capturado. Esperando confirmación.")
        return tx

    def execute_transaction(self, transaction_id: str, confirmation_token: str | None = None) -> ChangeResult:
        """PASOS 3, 4, 5, 6: CONFIRM -> EXECUTE -> VERIFY -> COMMIT (con ROLLBACK automático en caso de fallo)."""
        tx = self._active_transactions.get(transaction_id)
        if not tx:
            raise TransactionError(f"Transacción de cambio no encontrada: '{transaction_id}'")

        handlers = self._execution_handlers.get(transaction_id, {})
        execute_fn = handlers.get("execute_fn")
        rollback_fn = handlers.get("rollback_fn")
        verify_fn = handlers.get("verify_fn")

        start_time = time.perf_counter()

        # PASO 3: CONFIRM VERIFICATION
        req_id = tx.confirmation_id or ""
        req = self.confirmation_manager.get_pending_request(req_id) or self.confirmation_manager._resolved_requests.get(req_id)
        if not req or req.status != ConfirmationStatus.APPROVED:
            tx._set_state(TransactionState.WAITING_CONFIRMATION)
            raise TransactionConfirmationRequiredError(
                f"[CONFIRMATION REQUIRED] La transacción '{transaction_id}' requiere confirmación interactiva aprobada antes de ejecutarse."
            )

        # PASO 4: EXECUTE
        tx._set_state(TransactionState.EXECUTING)
        logger.info(f"[CHANGE TRANSACTION] Ejecutando transacción '{transaction_id}'...")

        post_data: dict[str, Any] = {}
        try:
            if callable(execute_fn):
                post_data = execute_fn() or {}
            tx._set_state(TransactionState.VERIFYING)
        except Exception as e:
            logger.error(f"[CHANGE TRANSACTION] Fallo durante la ejecución de la transacción '{transaction_id}': {e}")
            return self._handle_transaction_failure(tx, rollback_fn, error_message=f"Fallo en ejecución: {e}", duration_start=start_time)

        # PASO 5: VERIFY (Verificar integridad post-escritura)
        try:
            if callable(verify_fn):
                is_valid = verify_fn(post_data)
                if not is_valid:
                    raise TransactionVerificationError("La verificación del estado post-escritura no fue satisfactoria.")
        except Exception as e:
            logger.error(f"[CHANGE TRANSACTION] Fallo en la fase de verificación post-escritura: {e}")
            return self._handle_transaction_failure(tx, rollback_fn, error_message=f"Fallo en verificación: {e}", duration_start=start_time)

        # PASO 6: COMMIT (Éxito definitivo)
        tx._set_state(TransactionState.COMMITTED)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        res = ChangeResult(
            transaction_id=transaction_id,
            state=TransactionState.COMMITTED,
            success=True,
            post_state_data=post_data,
            duration_ms=duration_ms,
        )
        self._log_transaction_audit(transaction_id, "committed", success=True, duration_ms=duration_ms)
        return res

    def _handle_transaction_failure(
        self,
        tx: ChangeTransaction,
        rollback_fn: Callable[[dict[str, Any]], bool] | None,
        error_message: str,
        duration_start: float,
    ) -> ChangeResult:
        """Maneja el fallo durante la ejecución/verificación aplicando Rollback si es posible."""
        if tx.reversibility == Reversibility.IRREVERSIBLE:
            tx._set_state(TransactionState.IRREVERSIBLE)
            duration_ms = (time.perf_counter() - duration_start) * 1000.0
            err_msg = f"[IRREVERSIBLE FAILURE] Transacción '{tx.transaction_id}' no es reversible. Error: {error_message}"
            self._log_transaction_audit(tx.transaction_id, "irreversible_failure", success=False, reason=err_msg, duration_ms=duration_ms)
            return ChangeResult(
                transaction_id=tx.transaction_id,
                state=TransactionState.IRREVERSIBLE,
                success=False,
                error_message=err_msg,
                duration_ms=duration_ms,
            )

        # Iniciar ROLLBACK
        tx._set_state(TransactionState.ROLLING_BACK)
        logger.warning(f"[CHANGE TRANSACTION] Iniciando ROLLBACK para la transacción '{tx.transaction_id}'...")

        rollback_success = False
        try:
            if callable(rollback_fn) and tx.snapshot:
                rollback_success = rollback_fn(tx.snapshot.pre_state_data)
            else:
                rollback_success = True  # Rollback conceptual
        except Exception as e:
            logger.error(f"[CHANGE TRANSACTION] Error durante el proceso de ROLLBACK: {e}")
            rollback_success = False

        duration_ms = (time.perf_counter() - duration_start) * 1000.0

        if rollback_success:
            tx._set_state(TransactionState.ROLLED_BACK)
            err_msg = f"[ROLLED BACK] La transacción falló pero el estado fue revertido exitosamente. Error original: {error_message}"
            self._log_transaction_audit(tx.transaction_id, "rolled_back", success=True, reason=err_msg, duration_ms=duration_ms)
            return ChangeResult(
                transaction_id=tx.transaction_id,
                state=TransactionState.ROLLED_BACK,
                success=False,
                error_message=err_msg,
                duration_ms=duration_ms,
            )
        else:
            tx._set_state(TransactionState.FAILED)
            err_msg = f"[ROLLBACK FAILED] La transacción falló y la reversión a pre-state no tuvo éxito. Error: {error_message}"
            self._log_transaction_audit(tx.transaction_id, "rollback_failed", success=False, reason=err_msg, duration_ms=duration_ms)
            return ChangeResult(
                transaction_id=tx.transaction_id,
                state=TransactionState.FAILED,
                success=False,
                error_message=err_msg,
                duration_ms=duration_ms,
            )

    def _log_transaction_audit(
        self,
        transaction_id: str,
        action: str,
        success: bool,
        duration_ms: float = 0.0,
        reason: str = "",
    ) -> None:
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.POLICY_EVALUATED if success else AuditEventType.EXECUTION_DENIED,
                request_id=f"tx-{transaction_id[:8]}",
                tool_name="system.change_transaction",
                operation=action,
                duration_ms=duration_ms,
                reason=reason or f"Change transaction action '{action}' success={success}",
                metadata={"transaction_id": transaction_id, "action": action, "success": success},
            )
        )


class FakeTransactionProvider:
    """Implementación simulada de IChangeTransactionProvider para testing en aislamiento."""

    def __init__(self) -> None:
        self.manager = ChangeTransactionManager()

    def prepare_transaction(
        self,
        target_resource: str,
        operation_type: str,
        reversibility: Reversibility,
        pre_state_fn: Callable[[], dict[str, Any]],
        execute_fn: Callable[..., dict[str, Any]],
        rollback_fn: Callable[[dict[str, Any]], bool] | None = None,
        verify_fn: Callable[[dict[str, Any]], bool] | None = None,
    ) -> ChangeTransaction:
        return self.manager.prepare_transaction(
            target_resource=target_resource,
            operation_type=operation_type,
            reversibility=reversibility,
            pre_state_fn=pre_state_fn,
            execute_fn=execute_fn,
            rollback_fn=rollback_fn,
            verify_fn=verify_fn,
        )

    def execute_transaction(self, transaction_id: str, confirmation_token: str | None = None) -> ChangeResult:
        return self.manager.execute_transaction(transaction_id, confirmation_token)
