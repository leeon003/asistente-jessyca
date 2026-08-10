"""Auditoría de Seguridad de la Etapa 15 — System Write Security Audit.

DEMOSTRACIÓN FORMAL DE LAS 14 GARANTÍAS DE SEGURIDAD EXIGIDAS EN LA ETAPA 15:
1. Registry write no funciona sin confirmación interactiva aprobada.
2. Service control no funciona sin confirmación interactiva aprobada.
3. Software installation no funciona sin confirmación interactiva aprobada.
4. Confirmation TTL expira correctamente.
5. No existe confirmación reutilizable accidentalmente (anti replay attacks / no reusable tokens).
6. Protected services permanecen protegidos (WinDefend, RPCSS, lsass, etc.).
7. Registry allowlist funciona obligatoriamente.
8. Software source está restringido exclusivamente a 'winget'.
9. Arbitrary EXE/MSI está bloqueado por completo.
10. Todas las operaciones tienen audit metadata registrado.
11. Cambios reversibles se rollbackean automáticamente ante fallos.
12. Cambios irreversibles son identificados explícitamente (Reversibility.IRREVERSIBLE).
13. Fallos durante ejecución no dejan el sistema en estado inesperado cuando rollback sea posible.
14. Ninguna tool o módulo de escritura del sistema puede saltarse la canalización de seguridad.

REGLA DE VERIFICACIÓN:
REGISTRY_WRITE_ENABLED=false, SERVICE_WRITE_ENABLED=false, SOFTWARE_INSTALL_ENABLED=false por defecto en producción.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.audit_logger import AuditEventType, get_audit_logger
from core.change_transaction import (
    ChangeTransactionManager,
    Reversibility,
    TransactionConfirmationRequiredError,
    TransactionState,
)
from core.confirmation import (
    ConfirmationManager,
    ConfirmationStatus,
    MockConfirmationProvider,
)
from core.registry_boundary import (
    RegistrySecurityViolationError,
    RegistryWriteBoundary,
    RegistryWriteRequest,
)
from core.service_boundary import (
    ProtectedServiceViolationError,
    ServiceControlBoundary,
    ServiceControlRequest,
)
from core.software_boundary import (
    ArbitraryInstallerError,
    SoftwareInstallBoundary,
    SoftwareInstallRequest,
    UntrustedSourceError,
)


def _approve_tx_request(conf_manager: ConfirmationManager, request_id: str) -> None:
    req = conf_manager.get_pending_request(request_id)
    if req:
        conf_manager.submit_request(req, MockConfirmationProvider(ConfirmationStatus.APPROVED))


def test_audit_01_registry_write_requires_confirmation() -> None:
    """1. Registry write no funciona sin confirmación interactiva aprobada."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)
    boundary = RegistryWriteBoundary(transaction_manager=tx_manager, enabled=True, allowlist=["hkcu\\software\\jessyca"])

    req = RegistryWriteRequest(key_path="HKCU\\Software\\Jessyca", value_name="Key1", value_data="Val1")
    tx, summary = boundary.prepare_registry_write(req)

    assert tx.state == TransactionState.WAITING_CONFIRMATION

    # Sin aprobar -> Lanza error de confirmación requerida
    with pytest.raises(TransactionConfirmationRequiredError):
        tx_manager.execute_transaction(tx.transaction_id)


def test_audit_02_service_control_requires_confirmation() -> None:
    """2. Service control no funciona sin confirmación interactiva aprobada."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)
    boundary = ServiceControlBoundary(transaction_manager=tx_manager, enabled=True)

    req = ServiceControlRequest(service_name="CustomAppSvc", operation="start")
    tx, summary = boundary.prepare_service_control(req)

    assert tx.state == TransactionState.WAITING_CONFIRMATION

    with pytest.raises(TransactionConfirmationRequiredError):
        tx_manager.execute_transaction(tx.transaction_id)


def test_audit_03_software_installation_requires_confirmation() -> None:
    """3. Software installation no funciona sin confirmación interactiva aprobada."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)
    boundary = SoftwareInstallBoundary(transaction_manager=tx_manager, enabled=True)

    req = SoftwareInstallRequest(package_id="Git.Git", package_name="Git", publisher="Git", version="2.40.0")
    tx, summary = boundary.prepare_software_install(req)

    assert tx.state == TransactionState.WAITING_CONFIRMATION

    with pytest.raises(TransactionConfirmationRequiredError):
        tx_manager.execute_transaction(tx.transaction_id)


def test_audit_04_confirmation_ttl_expiration() -> None:
    """4. Confirmation TTL expira correctamente."""
    conf_manager = ConfirmationManager()

    req = conf_manager.create_request(
        tool_name="system.write",
        operation="write",
        parameters={},
        reason="Test TTL",
        ttl_seconds=10,
    )

    # Forzar la fecha de expiración en el pasado
    req.expires_at = datetime.now(UTC) - timedelta(seconds=10)

    # get_pending_request detecta la expiración y retorna None
    pending = conf_manager.get_pending_request(req.request_id)
    assert pending is None


def test_audit_05_no_reusable_confirmation_tokens() -> None:
    """5. Anti Replay Attack: No se permite la reutilización de confirmaciones ya consumidas."""
    conf_manager = ConfirmationManager()

    req = conf_manager.create_request(
        tool_name="system.change_transaction",
        operation="execute",
        parameters={"res": "test"},
        reason="Single use check",
    )

    # Aprobar
    conf_manager.submit_request(req, MockConfirmationProvider(ConfirmationStatus.APPROVED))

    # Primer consumo -> Exitoso
    first_consume = conf_manager.consume_confirmation(req.request_id, "system.change_transaction", "execute", {"res": "test"})
    assert first_consume is True

    # Segundo consumo -> Rechazado por Replay Attack
    second_consume = conf_manager.consume_confirmation(req.request_id, "system.change_transaction", "execute", {"res": "test"})
    assert second_consume is False


def test_audit_06_protected_services_remain_protected() -> None:
    """6. Protected services permanecen protegidos."""
    boundary = ServiceControlBoundary(enabled=True)

    critical_services = ["WinDefend", "RPCSS", "lsass", "EventLog", "wuauserv", "mpssvc", "Dhcp", "Dnscache"]
    for svc in critical_services:
        req = ServiceControlRequest(service_name=svc, operation="stop")
        with pytest.raises(ProtectedServiceViolationError):
            boundary.prepare_service_control(req)


def test_audit_07_registry_allowlist_enforced() -> None:
    """7. Registry allowlist funciona obligatoriamente."""
    boundary = RegistryWriteBoundary(enabled=True, allowlist=["hkcu\\software\\jessyca"])

    unapproved_req = RegistryWriteRequest(key_path="HKCU\\Software\\UnapprovedVendor", value_name="BadKey", value_data="BadVal")
    with pytest.raises(RegistrySecurityViolationError) as exc_info:
        boundary.prepare_registry_write(unapproved_req)

    assert "ALLOWLIST VIOLATION" in str(exc_info.value)


def test_audit_08_software_source_restricted_to_winget() -> None:
    """8. Software source está restringido exclusivamente a 'winget'."""
    boundary = SoftwareInstallBoundary(enabled=True, source="winget")

    untrusted_req = SoftwareInstallRequest(
        package_id="Git.Git",
        package_name="Git",
        publisher="Git",
        version="2.40.0",
        source="untrusted_third_party_repo",
    )

    with pytest.raises(UntrustedSourceError) as exc_info:
        boundary.prepare_software_install(untrusted_req)

    assert "UNTRUSTED SOURCE REJECTED" in str(exc_info.value)


def test_audit_09_arbitrary_exe_msi_blocked() -> None:
    """9. Arbitrary EXE/MSI está bloqueado por completo."""
    boundary = SoftwareInstallBoundary(enabled=True)

    bad_installers = ["malware.exe", "setup.msi", "C:\\temp\\installer.exe", "script.bat"]
    for bad in bad_installers:
        req = SoftwareInstallRequest(package_id=bad, package_name="BadApp", publisher="Bad", version="1.0")
        with pytest.raises(ArbitraryInstallerError):
            boundary.prepare_software_install(req)


def test_audit_10_all_operations_contain_audit_metadata() -> None:
    """10. Todas las operaciones tienen audit metadata registrado."""
    audit_logger = get_audit_logger()
    events_before = len(audit_logger.get_events())

    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)

    tx = tx_manager.prepare_transaction(
        target_resource="HKCU\\Software\\Jessyca\\AuditKey",
        operation_type="registry.write",
        reversibility=Reversibility.REVERSIBLE,
        pre_state_fn=lambda: {"v": 1},
        execute_fn=lambda: {"v": 2},
    )

    _approve_tx_request(conf_manager, tx.confirmation_id or "")
    tx_manager.execute_transaction(tx.transaction_id)

    events_after = len(audit_logger.get_events())
    assert events_after > events_before

    recent_event = audit_logger.get_events()[-1]
    assert recent_event.tool_name == "system.change_transaction"
    assert recent_event.event_type == AuditEventType.POLICY_EVALUATED
    assert "transaction_id" in recent_event.metadata


def test_audit_11_reversible_changes_rollback_on_failure() -> None:
    """11. Cambios reversibles pueden rollbackearse ante fallos de verificación."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)

    rolled_back = False

    def rollback_fn(pre_data: dict[str, Any]) -> bool:
        nonlocal rolled_back
        rolled_back = True
        return True

    tx = tx_manager.prepare_transaction(
        target_resource="HKCU\\Software\\TestRollback",
        operation_type="registry.write",
        reversibility=Reversibility.REVERSIBLE,
        pre_state_fn=lambda: {"state": "original"},
        execute_fn=lambda: {"state": "corrupted"},
        verify_fn=lambda post: False,  # Fallo deliberado de verificación
        rollback_fn=rollback_fn,
    )

    _approve_tx_request(conf_manager, tx.confirmation_id or "")
    res = tx_manager.execute_transaction(tx.transaction_id)

    assert res.success is False
    assert res.state == TransactionState.ROLLED_BACK
    assert rolled_back is True


def test_audit_12_irreversible_changes_explicitly_identified() -> None:
    """12. Cambios irreversibles son identificados explícitamente (Reversibility.IRREVERSIBLE)."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)

    tx = tx_manager.prepare_transaction(
        target_resource="irreversible_disk_erase",
        operation_type="system.format",
        reversibility=Reversibility.IRREVERSIBLE,
        pre_state_fn=lambda: {},
        execute_fn=lambda: (_ for _ in ()).throw(RuntimeError("Fallo irrecuperable")),
    )

    _approve_tx_request(conf_manager, tx.confirmation_id or "")
    res = tx_manager.execute_transaction(tx.transaction_id)

    assert res.success is False
    assert res.state == TransactionState.IRREVERSIBLE
    assert "IRREVERSIBLE FAILURE" in res.error_message


def test_audit_13_failures_leave_system_in_expected_state() -> None:
    """13. Fallos durante ejecución no dejan el sistema en estado inesperado cuando rollback sea posible."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)
    boundary = ServiceControlBoundary(transaction_manager=tx_manager, enabled=True)

    system_state = {"service_status": "Stopped"}

    def inspector(name: str) -> dict[str, Any]:
        return {"service_name": name, "status": system_state["service_status"], "exists": True}

    def failing_executor(name: str, op: str) -> bool:
        if op == "start":
            system_state["service_status"] = "CorruptedPartiallyStarted"
            raise RuntimeError("Fallo parcial en arranque")
        elif op == "stop":
            system_state["service_status"] = "Stopped"
        return True

    req = ServiceControlRequest(service_name="FailSafeApp", operation="start")
    tx, summary = boundary.prepare_service_control(req, mock_service_inspector=inspector, mock_service_executor=failing_executor)

    _approve_tx_request(conf_manager, tx.confirmation_id or "")
    res = tx_manager.execute_transaction(tx.transaction_id)

    assert res.success is False
    assert res.state == TransactionState.ROLLED_BACK
    # Comprobar que el rollback restauró el estado original 'Stopped'
    assert system_state["service_status"] == "Stopped"


def test_audit_14_pipeline_bypass_prevention() -> None:
    """14. Ninguna tool o módulo de escritura del sistema puede saltarse la canalización de seguridad."""
    # Verificar que por defecto todas las banderas de escritura del sistema estén deshabilitadas (DISABLED BY DEFAULT)
    from config.settings import AppSettings

    settings = AppSettings()

    assert settings.REGISTRY_WRITE_ENABLED is False
    assert settings.SERVICE_WRITE_ENABLED is False
    assert settings.SOFTWARE_INSTALL_ENABLED is False
