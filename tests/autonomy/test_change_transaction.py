"""Pruebas unitarias e integradas de ChangeTransactionManager (Etapa 15.1).

REQUISITOS PROBADOS:
1. Flujo obligatorio de 6 pasos: PREPARE -> SNAPSHOT -> CONFIRM -> EXECUTE -> VERIFY -> COMMIT.
2. Fallo en ejecución dispara Rollback automático a pre-state data (state = ROLLED_BACK).
3. Fallo en verificación post-escritura dispara Rollback automático a pre-state data (state = ROLLED_BACK).
4. Cambios declarados IRREVERSIBLE no ejecutan rollback y pasan a estado IRREVERSIBLE.
5. Requiere confirmación interactiva en ConfirmationManager (TTL corto).
6. FakeTransactionProvider funciona desacoplado en memoria.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.change_transaction import (
    ChangeTransactionManager,
    FakeTransactionProvider,
    Reversibility,
    TransactionConfirmationRequiredError,
    TransactionState,
)
from core.confirmation import (
    ConfirmationManager,
    ConfirmationStatus,
    MockConfirmationProvider,
)


def _approve_tx(conf_manager: ConfirmationManager, request_id: str) -> None:
    req = conf_manager.get_pending_request(request_id)
    if req:
        conf_manager.submit_request(req, MockConfirmationProvider(ConfirmationStatus.APPROVED))



def test_transaction_successful_flow() -> None:
    """Verifica el flujo completo de 6 pasos exitoso."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)

    target_res = "HKCU\\Software\\Jessyca\\TestKey"
    original_state = {"Value": "OldValue"}

    def pre_fn() -> dict[str, Any]:
        return original_state

    def exec_fn() -> dict[str, Any]:
        return {"Value": "NewValue"}

    def verify_fn(post_data: dict[str, Any]) -> bool:
        return post_data.get("Value") == "NewValue"

    # PASO 1 & 2: PREPARE & SNAPSHOT
    tx = tx_manager.prepare_transaction(
        target_resource=target_res,
        operation_type="registry.write",
        reversibility=Reversibility.REVERSIBLE,
        pre_state_fn=pre_fn,
        execute_fn=exec_fn,
        verify_fn=verify_fn,
    )

    assert tx.state == TransactionState.WAITING_CONFIRMATION
    assert tx.snapshot is not None
    assert tx.snapshot.pre_state_data == original_state
    assert len(tx.snapshot.snapshot_hash) == 64

    # Intentar ejecutar sin confirmar lanza error
    with pytest.raises(TransactionConfirmationRequiredError):
        tx_manager.execute_transaction(tx.transaction_id)

    # PASO 3: CONFIRM
    _approve_tx(conf_manager, tx.confirmation_id or "")


    # PASO 4, 5, 6: EXECUTE -> VERIFY -> COMMIT
    res = tx_manager.execute_transaction(tx.transaction_id)

    assert res.success is True
    assert res.state == TransactionState.COMMITTED
    assert res.post_state_data == {"Value": "NewValue"}


def test_transaction_execution_failure_triggers_rollback() -> None:
    """Verifica que un fallo durante la ejecución dispare Rollback a pre-state."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)

    original_state = {"Value": "Original"}
    rolled_back_data: dict[str, Any] = {}

    def pre_fn() -> dict[str, Any]:
        return original_state

    def exec_fn() -> dict[str, Any]:
        raise RuntimeError("Fallo simulado en escritura física")

    def rollback_fn(pre_data: dict[str, Any]) -> bool:
        nonlocal rolled_back_data
        rolled_back_data = pre_data
        return True

    tx = tx_manager.prepare_transaction(
        target_resource="HKCU\\Software\\Jessyca\\CrashKey",
        operation_type="registry.write",
        reversibility=Reversibility.REVERSIBLE,
        pre_state_fn=pre_fn,
        execute_fn=exec_fn,
        rollback_fn=rollback_fn,
    )

    _approve_tx(conf_manager, tx.confirmation_id or "")

    res = tx_manager.execute_transaction(tx.transaction_id)

    assert res.success is False
    assert res.state == TransactionState.ROLLED_BACK
    assert rolled_back_data == original_state
    assert "Fallo en ejecución" in res.error_message


def test_transaction_verification_failure_triggers_rollback() -> None:
    """Verifica que un fallo en la verificación post-escritura dispare Rollback."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)

    original_state = {"Setting": "Enabled"}
    rolled_back_data: dict[str, Any] = {}

    def pre_fn() -> dict[str, Any]:
        return original_state

    def exec_fn() -> dict[str, Any]:
        return {"Setting": "CorruptedValue"}

    def verify_fn(post_data: dict[str, Any]) -> bool:
        # Verificación falla porque la escritura no coincide con lo esperado
        return False

    def rollback_fn(pre_data: dict[str, Any]) -> bool:
        nonlocal rolled_back_data
        rolled_back_data = pre_data
        return True

    tx = tx_manager.prepare_transaction(
        target_resource="HKCU\\Software\\Jessyca\\VerifyKey",
        operation_type="registry.write",
        reversibility=Reversibility.REVERSIBLE,
        pre_state_fn=pre_fn,
        execute_fn=exec_fn,
        rollback_fn=rollback_fn,
        verify_fn=verify_fn,
    )

    _approve_tx(conf_manager, tx.confirmation_id or "")

    res = tx_manager.execute_transaction(tx.transaction_id)

    assert res.success is False
    assert res.state == TransactionState.ROLLED_BACK
    assert rolled_back_data == original_state
    assert "Fallo en verificación" in res.error_message


def test_irreversible_change_cannot_rollback() -> None:
    """Verifica que cambios declarados IRREVERSIBLE pasen al estado IRREVERSIBLE si la ejecución falla."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)

    def pre_fn() -> dict[str, Any]:
        return {"Data": "Important"}

    def exec_fn() -> dict[str, Any]:
        raise RuntimeError("Fallo irrecuperable")

    tx = tx_manager.prepare_transaction(
        target_resource="HKLM\\SYSTEM\\IrreversibleResource",
        operation_type="software.install",
        reversibility=Reversibility.IRREVERSIBLE,
        pre_state_fn=pre_fn,
        execute_fn=exec_fn,
    )

    _approve_tx(conf_manager, tx.confirmation_id or "")

    res = tx_manager.execute_transaction(tx.transaction_id)

    assert res.success is False
    assert res.state == TransactionState.IRREVERSIBLE
    assert "IRREVERSIBLE FAILURE" in res.error_message


def test_fake_transaction_provider() -> None:
    """Verifica el funcionamiento desacoplado de FakeTransactionProvider."""
    fake_provider = FakeTransactionProvider()

    tx = fake_provider.prepare_transaction(
        target_resource="HKCU\\Software\\Test",
        operation_type="service.write",
        reversibility=Reversibility.REVERSIBLE,
        pre_state_fn=lambda: {"Status": "Stopped"},
        execute_fn=lambda: {"Status": "Running"},
    )

    assert tx.state == TransactionState.WAITING_CONFIRMATION

    # Aprobar confirmación en el gestor interno del fake provider
    _approve_tx(fake_provider.manager.confirmation_manager, tx.confirmation_id or "")
    res = fake_provider.execute_transaction(tx.transaction_id)


    assert res.success is True
    assert res.state == TransactionState.COMMITTED
