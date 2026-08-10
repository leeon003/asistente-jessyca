"""Pruebas unitarias e integradas de ServiceControlBoundary (Etapa 15.3).

REQUISITOS Y ESCENARIOS PROBADOS:
1. protected service: Rechazo inmediato de servicios críticos (WinDefend, RPCSS, lsass).
2. unknown service: Rechazo de servicios no encontrados en el sistema.
3. unauthorized service: Rechazo cuando SERVICE_WRITE_ENABLED=False.
4. confirmation denied: Bloqueo de ejecución si la confirmación no fue aprobada.
5. confirmation accepted: Ejecución exitosa de start/stop/restart cuando la confirmación es aprobada.
6. failed start: Fallo en start dispara rollback devolviendo el servicio a Stopped.
7. failed stop: Fallo en stop dispara rollback devolviendo el servicio a Running.
8. rollback: Verificación de restauración completa del estado original del servicio.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.change_transaction import (
    ChangeTransactionManager,
    TransactionConfirmationRequiredError,
    TransactionState,
)
from core.confirmation import (
    ConfirmationManager,
    ConfirmationStatus,
    MockConfirmationProvider,
)
from core.service_boundary import (
    ProtectedServiceViolationError,
    ServiceControlBoundary,
    ServiceControlRequest,
    ServiceWriteDisabledError,
    UnknownServiceError,
)


def _approve_tx_confirmation(conf_manager: ConfirmationManager, request_id: str) -> None:
    req = conf_manager.get_pending_request(request_id)
    if req:
        conf_manager.submit_request(req, MockConfirmationProvider(ConfirmationStatus.APPROVED))


def test_unauthorized_service() -> None:
    """3. unauthorized service: SERVICE_WRITE_ENABLED=False por defecto lanza ServiceWriteDisabledError."""
    boundary = ServiceControlBoundary()
    req = ServiceControlRequest(service_name="CustomAppService", operation="start")

    with pytest.raises(ServiceWriteDisabledError) as exc_info:
        boundary.prepare_service_control(req)

    assert "SERVICE_WRITE_ENABLED=False" in str(exc_info.value)


def test_protected_service_rejection() -> None:
    """1. protected service: Intento de modificar WinDefend o RPCSS lanza ProtectedServiceViolationError."""
    boundary = ServiceControlBoundary(enabled=True)

    protected_services = ["WinDefend", "RPCSS", "lsass", "EventLog"]
    for prot_svc in protected_services:
        req = ServiceControlRequest(service_name=prot_svc, operation="stop")
        with pytest.raises(ProtectedServiceViolationError) as exc_info:
            boundary.prepare_service_control(req)
        assert "PROTECTED SERVICE REJECTED" in str(exc_info.value)


def test_unknown_service_rejection() -> None:
    """2. unknown service: Servicio no encontrado en el sistema lanza UnknownServiceError."""
    boundary = ServiceControlBoundary(enabled=True)

    def missing_inspector(name: str) -> dict[str, Any] | None:
        return {"exists": False}

    req = ServiceControlRequest(service_name="GhostServiceDoesNotExist", operation="start")
    with pytest.raises(UnknownServiceError) as exc_info:
        boundary.prepare_service_control(req, mock_service_inspector=missing_inspector)

    assert "UNKNOWN SERVICE" in str(exc_info.value)


def test_confirmation_denied() -> None:
    """4. confirmation denied: Intentar ejecutar sin aprobación previa del usuario genera error de confirmación."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)
    boundary = ServiceControlBoundary(transaction_manager=tx_manager, enabled=True)

    req = ServiceControlRequest(service_name="MyTestService", operation="start")
    tx, summary = boundary.prepare_service_control(req)

    assert tx.state == TransactionState.WAITING_CONFIRMATION

    # Sin aprobar confirmación -> Lanza error
    with pytest.raises(TransactionConfirmationRequiredError):
        tx_manager.execute_transaction(tx.transaction_id)


def test_confirmation_accepted() -> None:
    """5. confirmation accepted: Confirmación aprobada permite la ejecución de start/stop exitosa."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)
    boundary = ServiceControlBoundary(transaction_manager=tx_manager, enabled=True)

    state = {"status": "Stopped"}

    def inspector(name: str) -> dict[str, Any]:
        return {"service_name": name, "status": state["status"], "exists": True, "dependencies": []}

    def executor(name: str, op: str) -> bool:
        if op == "start":
            state["status"] = "Running"
        elif op == "stop":
            state["status"] = "Stopped"
        return True

    req = ServiceControlRequest(service_name="MyWorkerService", operation="start")
    tx, summary = boundary.prepare_service_control(req, mock_service_inspector=inspector, mock_service_executor=executor)

    _approve_tx_confirmation(conf_manager, tx.confirmation_id or "")

    res = tx_manager.execute_transaction(tx.transaction_id)

    assert res.success is True
    assert res.state == TransactionState.COMMITTED
    assert state["status"] == "Running"


def test_failed_start_triggers_rollback() -> None:
    """6. failed start: Fallo al arrancar dispara rollback restaurando el estado Stopped original."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)
    boundary = ServiceControlBoundary(transaction_manager=tx_manager, enabled=True)

    state = {"status": "Stopped"}

    def inspector(name: str) -> dict[str, Any]:
        return {"service_name": name, "status": state["status"], "exists": True, "dependencies": []}

    def failing_executor(name: str, op: str) -> bool:
        if op == "start":
            raise RuntimeError("Fallo al iniciar el proceso del servicio")
        elif op == "stop":
            state["status"] = "Stopped"
        return True

    req = ServiceControlRequest(service_name="CrashAppService", operation="start")
    tx, summary = boundary.prepare_service_control(req, mock_service_inspector=inspector, mock_service_executor=failing_executor)

    _approve_tx_confirmation(conf_manager, tx.confirmation_id or "")

    res = tx_manager.execute_transaction(tx.transaction_id)

    assert res.success is False
    assert res.state == TransactionState.ROLLED_BACK
    assert state["status"] == "Stopped"


def test_failed_stop_triggers_rollback() -> None:
    """7. failed stop: Fallo al detener dispara rollback restaurando el estado Running original."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)
    boundary = ServiceControlBoundary(transaction_manager=tx_manager, enabled=True)

    state = {"status": "Running"}

    def inspector(name: str) -> dict[str, Any]:
        return {"service_name": name, "status": state["status"], "exists": True, "dependencies": []}

    def failing_executor(name: str, op: str) -> bool:
        if op == "stop":
            raise RuntimeError("Servicio no responde al comando de parada")
        elif op == "start":
            state["status"] = "Running"
        return True

    req = ServiceControlRequest(service_name="StuckService", operation="stop")
    tx, summary = boundary.prepare_service_control(req, mock_service_inspector=inspector, mock_service_executor=failing_executor)

    _approve_tx_confirmation(conf_manager, tx.confirmation_id or "")

    res = tx_manager.execute_transaction(tx.transaction_id)

    assert res.success is False
    assert res.state == TransactionState.ROLLED_BACK
    assert state["status"] == "Running"


def test_rollback_restores_previous_state() -> None:
    """8. rollback: Verificación de la invocación completa del handler de rollback restaurando estado."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)
    boundary = ServiceControlBoundary(transaction_manager=tx_manager, enabled=True)

    state = {"status": "Stopped"}
    rollback_called = False

    def inspector(name: str) -> dict[str, Any]:
        return {"service_name": name, "status": state["status"], "exists": True, "dependencies": []}

    def executor(name: str, op: str) -> bool:
        nonlocal rollback_called
        if op == "start":
            state["status"] = "RunningCorrupted"  # Hace fallar la verificación post-escritura
        elif op == "stop":
            rollback_called = True
            state["status"] = "Stopped"
        return True

    req = ServiceControlRequest(service_name="RollbackTestService", operation="start")
    tx, summary = boundary.prepare_service_control(req, mock_service_inspector=inspector, mock_service_executor=executor)

    _approve_tx_confirmation(conf_manager, tx.confirmation_id or "")

    res = tx_manager.execute_transaction(tx.transaction_id)

    assert res.success is False
    assert res.state == TransactionState.ROLLED_BACK
    assert rollback_called is True
    assert state["status"] == "Stopped"
