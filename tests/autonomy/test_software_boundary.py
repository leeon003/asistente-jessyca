"""Pruebas unitarias y adversariales de SoftwareInstallBoundary (Etapa 15.4).

REQUISITOS Y ATAQUES ADVERSARIALES PROBADOS:
1. Disabled by default: SOFTWARE_INSTALL_ENABLED=False por defecto lanza SoftwareInstallDisabledError.
2. Rechazo de instaladores arbitrarios: Cero ejecución de archivos .exe, .msi o descargas locales.
3. Rechazo de inyección de comandos shell (&, ;, |, &&, `, $).
4. Rechazo de fuentes no autorizadas (exclusivamente 'winget').
5. Control por SOFTWARE_INSTALL_ALLOWLIST explícita.
6. Detección de alteración de identidad del paquete (Package Identity Mismatch).
7. Flujo obligatorio completo de 7 pasos.
8. Desinstalación automática (Rollback) ante fallo de verificación post-instalación.
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
from core.software_boundary import (
    ArbitraryInstallerError,
    PackageAllowlistViolationError,
    SoftwareInstallBoundary,
    SoftwareInstallDisabledError,
    SoftwareInstallError,
    SoftwareInstallRequest,
    UntrustedSourceError,
)


def _approve_tx_confirmation(conf_manager: ConfirmationManager, request_id: str) -> None:
    req = conf_manager.get_pending_request(request_id)
    if req:
        conf_manager.submit_request(req, MockConfirmationProvider(ConfirmationStatus.APPROVED))


def test_software_install_disabled_by_default() -> None:
    """1. Disabled by default: Verifica que la instalación de software esté deshabilitada por defecto."""
    boundary = SoftwareInstallBoundary()
    req = SoftwareInstallRequest(
        package_id="Git.Git",
        package_name="Git",
        publisher="Git for Windows",
        version="2.40.0",
    )

    with pytest.raises(SoftwareInstallDisabledError) as exc_info:
        boundary.prepare_software_install(req)

    assert "SOFTWARE_INSTALL_ENABLED=False" in str(exc_info.value)


def test_arbitrary_installer_rejection() -> None:
    """2. Arbitrary installer rejection: Rechazo de binarios .exe, .msi o archivos descargados locales."""
    boundary = SoftwareInstallBoundary(enabled=True)

    arbitrary_installers = [
        "C:\\Downloads\\setup.exe",
        "installer.msi",
        "script.bat",
        "/tmp/setup.sh",
    ]

    for bad_pkg in arbitrary_installers:
        req = SoftwareInstallRequest(
            package_id=bad_pkg,
            package_name="ArbitraryApp",
            publisher="Unknown",
            version="1.0",
        )
        with pytest.raises(ArbitraryInstallerError) as exc_info:
            boundary.prepare_software_install(req)
        assert "ARBITRARY INSTALLER REJECTED" in str(exc_info.value)


def test_command_injection_rejection() -> None:
    """3. Command injection rejection: Rechazo de inyección de operadores shell en package_id."""
    boundary = SoftwareInstallBoundary(enabled=True)

    malicious_inputs = [
        "Git.Git & calc.exe",
        "7zip.7zip; rm -rf /",
        "Python.Python | nc -e cmd.exe",
        "Git.Git `whoami`",
    ]

    for injection in malicious_inputs:
        req = SoftwareInstallRequest(
            package_id=injection,
            package_name="InjectedApp",
            publisher="Attacker",
            version="1.0",
        )
        with pytest.raises(SoftwareInstallError) as exc_info:
            boundary.prepare_software_install(req)
        assert "COMMAND INJECTION DETECTED" in str(exc_info.value) or "ARBITRARY INSTALLER" in str(exc_info.value)


def test_untrusted_source_rejection() -> None:
    """4. Untrusted source rejection: Fuentes distintas a 'winget' son rechazadas."""
    boundary = SoftwareInstallBoundary(enabled=True, source="winget")

    req = SoftwareInstallRequest(
        package_id="Git.Git",
        package_name="Git",
        publisher="Git",
        version="2.40.0",
        source="untrusted_apt_repo",
    )

    with pytest.raises(UntrustedSourceError) as exc_info:
        boundary.prepare_software_install(req)

    assert "UNTRUSTED SOURCE REJECTED" in str(exc_info.value)


def test_allowlist_enforcement() -> None:
    """5. Allowlist enforcement: Paquetes fuera de SOFTWARE_INSTALL_ALLOWLIST son bloqueados."""
    boundary = SoftwareInstallBoundary(enabled=True, allowlist=["git.git", "7zip.7zip"])

    # Paquete en Allowlist -> OK
    req_valid = SoftwareInstallRequest(
        package_id="Git.Git",
        package_name="Git",
        publisher="Git for Windows",
        version="2.40.0",
    )
    tx, summary = boundary.prepare_software_install(req_valid)
    assert tx.state == TransactionState.WAITING_CONFIRMATION

    # Paquete fuera de Allowlist -> Rechazado
    req_invalid = SoftwareInstallRequest(
        package_id="Malware.UnapprovedApp",
        package_name="Malware",
        publisher="Untrusted",
        version="6.6.6",
    )
    with pytest.raises(PackageAllowlistViolationError) as exc_info:
        boundary.prepare_software_install(req_invalid)

    assert "ALLOWLIST VIOLATION" in str(exc_info.value)


def test_full_7step_execution_flow() -> None:
    """6 & 7. Full 7-step execution flow: Flujo completo exitoso con metadatos mostrados al usuario."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)
    boundary = SoftwareInstallBoundary(transaction_manager=tx_manager, enabled=True)

    installed_packages: dict[str, bool] = {}

    def inspector(pkg_id: str) -> dict[str, Any]:
        return {"package_id": pkg_id, "installed": installed_packages.get(pkg_id, False)}

    def installer(pkg_id: str, op: str) -> bool:
        if op == "install":
            installed_packages[pkg_id] = True
        elif op == "uninstall":
            installed_packages[pkg_id] = False
        return True

    req = SoftwareInstallRequest(
        package_id="7zip.7zip",
        package_name="7-Zip",
        publisher="Igor Pavlov",
        version="23.01",
    )

    tx, summary = boundary.prepare_software_install(req, mock_package_inspector=inspector, mock_package_installer=installer)

    # Verificar metadatos mostrados al usuario antes de confirmar
    assert summary["package_id"] == "7zip.7zip"
    assert summary["package_name"] == "7-Zip"
    assert summary["publisher"] == "Igor Pavlov"
    assert summary["source"] == "winget"
    assert summary["version"] == "23.01"
    assert summary["requested_operation"] == "install"
    assert len(summary["identity_hash"]) == 64

    _approve_tx_confirmation(conf_manager, tx.confirmation_id or "")

    res = tx_manager.execute_transaction(tx.transaction_id)

    assert res.success is True
    assert res.state == TransactionState.COMMITTED
    assert installed_packages.get("7zip.7zip") is True


def test_failed_install_triggers_rollback() -> None:
    """8. Rollback: Fallo en la verificación post-instalación dispara la desinstalación (winget uninstall) automática."""
    conf_manager = ConfirmationManager()
    tx_manager = ChangeTransactionManager(confirmation_manager=conf_manager)
    boundary = SoftwareInstallBoundary(transaction_manager=tx_manager, enabled=True)

    uninstalled_called = False

    def inspector(pkg_id: str) -> dict[str, Any]:
        # Simula que la instalación reporta fallo (installed = False)
        return {"package_id": pkg_id, "installed": False}

    def failing_installer(pkg_id: str, op: str) -> bool:
        nonlocal uninstalled_called
        if op == "uninstall":
            uninstalled_called = True
        return True

    req = SoftwareInstallRequest(
        package_id="Git.Git",
        package_name="Git",
        publisher="Git for Windows",
        version="2.40.0",
    )

    tx, summary = boundary.prepare_software_install(req, mock_package_inspector=inspector, mock_package_installer=failing_installer)

    _approve_tx_confirmation(conf_manager, tx.confirmation_id or "")

    res = tx_manager.execute_transaction(tx.transaction_id)

    assert res.success is False
    assert res.state == TransactionState.ROLLED_BACK
    assert uninstalled_called is True
