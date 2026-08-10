"""Pruebas unitarias y adversariales de RegistryWriteBoundary (Etapa 15.2).

REQUISITOS Y ATAQUES ADVERSARIALES PROBADOS:
1. Disabled by default: REGISTRY_WRITE_ENABLED=False por defecto lanza RegistryWriteDisabledError.
2. Allowlist explícita: Rutas fuera de REGISTRY_WRITE_ALLOWLIST son bloqueadas con RegistrySecurityViolationError.
3. Rechazo de persistencia Autorun (Run, RunOnce, Winlogon).
4. Rechazo de alteración de políticas de seguridad y Windows Defender.
5. Formato del resumen de impacto (Diff View) para confirmación del usuario.
6. Rollback transaccional ante fallo de verificación post-escritura.
7. Adversarial Fuzzing: Inyección de nulos, traversal (..) y sintaxis malformada.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.change_transaction import (
    ChangeTransactionManager,
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
    RegistryWriteDisabledError,
    RegistryWriteRequest,
)


def _approve_tx_confirmation(conf_manager: ConfirmationManager, request_id: str) -> None:
    req = conf_manager.get_pending_request(request_id)
    if req:
        conf_manager.submit_request(req, MockConfirmationProvider(ConfirmationStatus.APPROVED))


def test_registry_disabled_by_default() -> None:
    """1. Disabled by default: Verifica que la escritura en registro esté deshabilitada por defecto."""
    boundary = RegistryWriteBoundary()
    req = RegistryWriteRequest(
        key_path="HKCU\\Software\\Jessyca\\TestKey",
        value_name="Theme",
        value_data="Dark",
    )

    with pytest.raises(RegistryWriteDisabledError) as exc_info:
        boundary.prepare_registry_write(req)

    assert "REGISTRY_WRITE_ENABLED=False" in str(exc_info.value)


def test_allowlist_enforcement() -> None:
    """2. Allowlist explícita: Verifica que solo las rutas en allowlist sean procesadas."""
    boundary = RegistryWriteBoundary(enabled=True, allowlist=["hkcu\\software\\jessyca"])

    # A. Ruta en Allowlist -> Preparación exitosa
    req_valid = RegistryWriteRequest(
        key_path="HKCU\\Software\\Jessyca\\SubKey",
        value_name="Setting1",
        value_data="100",
    )
    tx, summary = boundary.prepare_registry_write(req_valid)
    assert tx.state == TransactionState.WAITING_CONFIRMATION

    # B. Ruta fuera de Allowlist -> Bloqueada
    req_invalid = RegistryWriteRequest(
        key_path="HKCU\\Software\\UnapprovedApp\\SubKey",
        value_name="Malicious",
        value_data="True",
    )
    with pytest.raises(RegistrySecurityViolationError) as exc_info:
        boundary.prepare_registry_write(req_invalid)

    assert "ALLOWLIST VIOLATION" in str(exc_info.value)


def test_forbidden_autorun_persistence_rejection() -> None:
    """3. Persistence rejection: Bloqueo de claves Autorun / Run / RunOnce."""
    boundary = RegistryWriteBoundary(
        enabled=True,
        allowlist=["hkcu\\software\\microsoft\\windows\\currentversion\\run"],
    )

    req_run = RegistryWriteRequest(
        key_path="HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
        value_name="EvilPersistence",
        value_data="C:\\malware.exe",
    )

    with pytest.raises(RegistrySecurityViolationError) as exc_info:
        boundary.prepare_registry_write(req_run)

    assert "PERSISTENCE ATTEMPT REJECTED" in str(exc_info.value)


def test_forbidden_security_policies_rejection() -> None:
    """4. Security policy rejection: Bloqueo de alteración de políticas de Windows Defender."""
    boundary = RegistryWriteBoundary(
        enabled=True,
        allowlist=["hklm\\software\\policies\\microsoft\\windows defender"],
    )

    req_policy = RegistryWriteRequest(
        key_path="HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows Defender",
        value_name="DisableAntiSpyware",
        value_data=1,
        value_type="REG_DWORD",
    )

    with pytest.raises(RegistrySecurityViolationError) as exc_info:
        boundary.prepare_registry_write(req_policy)

    assert "SECURITY VIOLATION" in str(exc_info.value) or "DEFENDER DEGRADATION" in str(exc_info.value)



def test_user_impact_summary_formatting() -> None:
    """5. Diff View: Verifica el formato del resumen de impacto para la confirmación del usuario."""
    boundary = RegistryWriteBoundary(enabled=True, allowlist=["hkcu\\software\\jessyca"])

    mock_db = {"hkcu\\software\\jessyca:Version": "1.0"}

    def reader(path: str, val_name: str) -> Any:
        return mock_db.get(f"{path}:{val_name}")

    req = RegistryWriteRequest(
        key_path="HKCU\\Software\\Jessyca",
        value_name="Version",
        value_data="2.0",
    )

    tx, summary = boundary.prepare_registry_write(req, mock_registry_reader=reader)

    assert summary["target_key"] == "hkcu\\software\\jessyca"
    assert summary["value_name"] == "Version"
    assert summary["old_value"] == "1.0"
    assert summary["new_value"] == "2.0"
    assert summary["operation"] == "set_value"


def test_transactional_rollback_on_verification_failure() -> None:
    """6. Transactional rollback: Verificación post-escritura fallida dispara rollback automático al valor anterior."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)
    boundary = RegistryWriteBoundary(
        transaction_manager=tx_manager,
        enabled=True,
        allowlist=["hkcu\\software\\jessyca"],
    )

    store: dict[str, Any] = {"hkcu\\software\\jessyca:Color": "Blue"}

    def reader(path: str, val_name: str) -> Any:
        return store.get(f"{path}:{val_name}")

    def corrupt_writer(path: str, val_name: str, data: Any, v_type: str) -> bool:
        # Escribe un valor corrupto distinto al solicitado
        store[f"{path}:{val_name}"] = "CorruptedYellow"
        return True

    req = RegistryWriteRequest(
        key_path="HKCU\\Software\\Jessyca",
        value_name="Color",
        value_data="Red",
    )

    tx, summary = boundary.prepare_registry_write(
        req,
        mock_registry_reader=reader,
        mock_registry_writer=corrupt_writer,
    )

    _approve_tx_confirmation(conf_manager, tx.confirmation_id or "")

    res = tx_manager.execute_transaction(tx.transaction_id)

    assert res.success is False
    assert res.state == TransactionState.ROLLED_BACK
    assert "Fallo en verificación" in res.error_message


def test_adversarial_path_fuzzing() -> None:
    """7. Adversarial fuzzing: Intención de path traversal y sintaxis malformada."""
    boundary = RegistryWriteBoundary(enabled=True, allowlist=["hkcu\\software\\jessyca"])

    malformed_paths = [
        "",
        "   ",
        "HKCU\\Software\\..\\..\\Windows",
        "HKCU\\Software\\\x00\\Bad",
    ]

    for bad_path in malformed_paths:
        req = RegistryWriteRequest(key_path=bad_path, value_name="Test", value_data="Data")
        with pytest.raises(RegistrySecurityViolationError):
            boundary.prepare_registry_write(req)
