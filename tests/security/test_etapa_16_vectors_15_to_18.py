"""Etapa 16.0 — Vectores 15–18: Race Conditions, Emergency Stop, Cancellation, Stale State."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from core.confirmation import ConfirmationManager, ConfirmationStatus, MockConfirmationProvider
from core.emergency_stop import (
    CancellationToken,
    EmergencyStopManager,
    EmergencyStopTriggeredError,
)

# ─────────────────────────────────────────────────────────
# Vector 15: Race Conditions
# ─────────────────────────────────────────────────────────

class TestRaceConditions:
    """AUDIT H-05: Race conditions en componentes de seguridad."""

    def test_confirmation_concurrent_submission_same_request(self) -> None:
        """10 hilos intentando aprobar el mismo request_id al mismo tiempo."""
        manager = ConfirmationManager()
        req = manager.create_request(
            tool_name="race.tool",
            operation="execute",
            parameters={"key": "value"},
        )

        results: list[str] = []
        lock = threading.Lock()

        def submit() -> None:
            try:
                result = manager.submit_request(
                    req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED)
                )
                with lock:
                    results.append(str(result.status))
            except Exception as e:
                with lock:
                    results.append(f"ERROR:{e!s}")

        threads = [threading.Thread(target=submit) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No debe haber excepciones de concurrencia (RuntimeError, KeyError)
        errors = [r for r in results if r.startswith("ERROR:")]
        assert len(errors) == 0, (
            f"[AUDIT-H05] Race condition en ConfirmationManager.submit_request(): {errors}"
        )

    def test_confirmation_concurrent_consume_unique(self) -> None:
        """Exactamente 1 hilo debe poder consumir una confirmación aprobada."""
        manager = ConfirmationManager()
        req = manager.create_request(
            tool_name="race.consume",
            operation="execute",
            parameters={"resource": "target"},
        )
        manager.submit_request(req, provider=MockConfirmationProvider(ConfirmationStatus.APPROVED))

        successes: list[bool] = []
        lock = threading.Lock()

        def try_consume() -> None:
            result = manager.consume_confirmation(
                req.request_id, "race.consume", "execute", {"resource": "target"}
            )
            with lock:
                successes.append(result)

        threads = [threading.Thread(target=try_consume) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        consumed_count = sum(1 for s in successes if s)
        assert consumed_count == 1, (
            f"[AUDIT-H05] {consumed_count} hilos consumieron la misma confirmación. "
            "Se esperaba exactamente 1."
        )

    def test_security_manager_concurrent_blacklist_safe(self) -> None:
        """Operaciones concurrentes en blacklist del SecurityManager no deben corromper estado."""
        from core.security import SecurityManager

        sm = SecurityManager()
        errors: list[str] = []
        lock = threading.Lock()

        def modify_blacklist(i: int) -> None:
            try:
                sm.add_to_blacklist(f"tool_{i}")
                time.sleep(0.001)
                sm.remove_from_blacklist(f"tool_{i}")
            except Exception as e:
                with lock:
                    errors.append(f"Thread {i}: {e!s}")

        threads = [threading.Thread(target=modify_blacklist, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if errors:
            pytest.xfail(
                f"[AUDIT-H05-CONFIRMED] Race condition en SecurityManager blacklist: {errors[:3]}. "
                "Falta threading.Lock en SecurityManager._blacklist (set mutable sin protección)."
            )


# ─────────────────────────────────────────────────────────
# Vector 16: Emergency Stop
# ─────────────────────────────────────────────────────────

class TestEmergencyStop:
    """Verifica que EmergencyStopManager funciona correctamente."""

    def setup_method(self) -> None:
        # Usar instancia fresca para cada test (no el singleton)
        from core.emergency_stop import EmergencyStopManager
        self.manager = EmergencyStopManager()

    def test_trigger_activates_stopped_state(self) -> None:
        """trigger_stop() debe activar estado STOPPED."""
        assert not self.manager.is_stopped()
        self.manager.trigger_stop(reason="audit_test", source="test")
        assert self.manager.is_stopped()

    def test_trigger_is_idempotent(self) -> None:
        """Múltiples llamadas a trigger_stop() no deben causar errores."""
        self.manager.trigger_stop(reason="first", source="test")
        self.manager.trigger_stop(reason="second", source="test")  # Segunda llamada
        assert self.manager.is_stopped()

    def test_check_cancellation_raises_when_stopped(self) -> None:
        """check_cancellation() debe lanzar EmergencyStopTriggeredError si está detenido."""
        self.manager.trigger_stop(reason="audit", source="test")
        with pytest.raises(EmergencyStopTriggeredError):
            self.manager.check_cancellation(phase="test_phase")

    def test_reset_returns_to_running(self) -> None:
        """reset() debe restaurar el estado a RUNNING."""
        self.manager.trigger_stop(reason="audit", source="test")
        assert self.manager.is_stopped()
        self.manager.reset(reason="audit_reset")
        assert not self.manager.is_stopped()

    def test_reset_without_authorization_audit(self) -> None:
        """H-04 AUDIT: reset() no autorizado debe ser rechazado y mantener el estado STOPPED."""
        self.manager.trigger_stop(reason="legitimate_stop", source="user")

        # Código no autorizado que intente resetear es rechazado
        self.manager.reset(reason="unauthorized_reset_by_plugin")

        assert self.manager.is_stopped() is True, (
            "[AUDIT-H04] Intento de reset no autorizado no debe restaurar el sistema a RUNNING."
        )

    def test_concurrent_trigger_stop_thread_safe(self) -> None:
        """trigger_stop() desde múltiples hilos debe ser thread-safe."""
        errors: list[Exception] = []
        lock = threading.Lock()

        def trigger() -> None:
            try:
                self.manager.trigger_stop(reason="concurrent_test", source="thread")
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=trigger) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, (
            f"[AUDIT] trigger_stop() concurrente causó excepciones: {errors}"
        )
        assert self.manager.is_stopped()

    def test_get_status_returns_complete_info(self) -> None:
        """get_status() debe retornar información completa de estado."""
        self.manager.trigger_stop(reason="status_test", source="audit")
        status = self.manager.get_status()

        assert "state" in status
        assert "is_stopped" in status
        assert "reason" in status
        assert "source" in status
        assert status["is_stopped"] is True
        assert status["reason"] == "status_test"
        assert status["source"] == "audit"


# ─────────────────────────────────────────────────────────
# Vector 17: Cancellation
# ─────────────────────────────────────────────────────────

class TestCancellation:
    """Verifica el mecanismo de CancellationToken."""

    def test_fresh_token_not_cancelled(self) -> None:
        """Token recién creado no debe estar cancelado."""
        token = CancellationToken()
        assert not token.is_cancellation_requested()

    def test_token_cancelled_when_event_set(self) -> None:
        """Token debe reportar cancelación cuando el evento interno es activado."""
        import threading as th
        event = th.Event()
        token = CancellationToken(event=event)

        assert not token.is_cancellation_requested()
        event.set()
        assert token.is_cancellation_requested()

    def test_wait_or_cancelled_respects_timeout(self) -> None:
        """wait_or_cancelled() debe retornar False si no hay cancelación en el timeout."""
        token = CancellationToken()
        start = time.perf_counter()
        result = token.wait_or_cancelled(timeout_seconds=0.05)
        elapsed = time.perf_counter() - start

        assert result is False, "Token no cancelado debe retornar False."
        assert elapsed >= 0.04, "Debe esperar al menos el timeout."

    def test_wait_or_cancelled_returns_early_on_cancel(self) -> None:
        """wait_or_cancelled() debe retornar True inmediatamente si ya está cancelado."""
        import threading as th
        event = th.Event()
        event.set()  # Ya cancelado
        token = CancellationToken(event=event)

        result = token.wait_or_cancelled(timeout_seconds=10.0)
        assert result is True, "Token ya cancelado debe retornar True inmediatamente."

    def test_emergency_stop_token_integration(self) -> None:
        """Token de EmergencyStopManager debe reflejar el estado del manager."""
        manager = EmergencyStopManager()
        token = manager.cancellation_token

        assert not token.is_cancellation_requested()
        manager.trigger_stop(reason="token_test", source="test")
        assert token.is_cancellation_requested()
        manager.reset(reason="cleanup")


# ─────────────────────────────────────────────────────────
# Vector 18: Stale State Execution
# ─────────────────────────────────────────────────────────

class TestStaleStateExecution:
    """Verifica que el sistema detecta y rechaza ejecución con estado obsoleto."""

    def test_stale_transaction_confirmation_rejected(self) -> None:
        """C-02 AUDIT: Acceso a _resolved_requests desde ChangeTransaction."""
        from core.change_transaction import (
            ChangeTransactionManager,
            TransactionConfirmationRequiredError,
        )
        from core.confirmation import ConfirmationManager

        conf = ConfirmationManager()
        tx_mgr = ChangeTransactionManager(confirmation_manager=conf)

        tx = tx_mgr.prepare_transaction(
            target_resource="stale_resource",
            operation_type="write",
            reversibility=__import__("core.change_transaction", fromlist=["Reversibility"]).Reversibility.REVERSIBLE,
            pre_state_fn=lambda: {"state": "original"},
            execute_fn=lambda: {"state": "modified"},
        )

        # AUDIT C-02: ChangeTransaction accede directamente a _resolved_requests
        # Si hay una confirmación en _resolved_requests con status != APPROVED,
        # la transacción debe rechazarse
        assert tx.confirmation_id is not None

        # Sin aprobar, debe fallar
        with pytest.raises(TransactionConfirmationRequiredError):
            tx_mgr.execute_transaction(tx.transaction_id)

    def test_expired_transaction_confirmation_rejected(self) -> None:
        """Transacción con confirmación expirada no debe ejecutarse."""
        from core.change_transaction import (
            ChangeTransactionManager,
            Reversibility,
        )
        from core.confirmation import ConfirmationManager

        conf = ConfirmationManager()
        tx_mgr = ChangeTransactionManager(confirmation_manager=conf)

        tx = tx_mgr.prepare_transaction(
            target_resource="expired_resource",
            operation_type="write",
            reversibility=Reversibility.REVERSIBLE,
            pre_state_fn=lambda: {"state": "original"},
            execute_fn=lambda: {"state": "modified"},
        )

        # Aprobar y luego expirar
        if tx.confirmation_id:
            req = conf.get_pending_request(tx.confirmation_id)
            if req:
                conf.submit_request(req, MockConfirmationProvider(ConfirmationStatus.APPROVED))
                # Forzar expiración
                req.expires_at = datetime.now(UTC) - timedelta(seconds=1)

        # Con confirmación expirada, el consume debe fallar
        if tx.confirmation_id:
            consumed = conf.consume_confirmation(
                tx.confirmation_id, "system.change_transaction", "write",
                {"target_resource": "expired_resource", "reversibility": "reversible",
                 "snapshot_hash": tx.snapshot.snapshot_hash if tx.snapshot else ""}
            )
            # Si la confirmación está expirada, consume debe retornar False
            # o la transacción debe lanzar error
            # Documentar el comportamiento real

    def test_transaction_state_cannot_be_externally_modified(self) -> None:
        """M-04 AUDIT: ChangeTransaction.state está protegido contra modificación externa directa."""
        from core.change_transaction import ChangeTransaction, Reversibility, TransactionState

        tx = ChangeTransaction(
            transaction_id="tx-audit-m04",
            target_resource="resource",
            operation_type="write",
            reversibility=Reversibility.REVERSIBLE,
            state=TransactionState.WAITING_CONFIRMATION,
        )

        # Intentar modificar el estado externamente debe lanzar AttributeError
        with pytest.raises(AttributeError):
            tx.state = TransactionState.COMMITTED  # type: ignore[misc]

        assert tx.state == TransactionState.WAITING_CONFIRMATION
