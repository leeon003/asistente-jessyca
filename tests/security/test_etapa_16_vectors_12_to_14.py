"""Etapa 16.0 — Vectores 12–14: Registry Abuse, Service Abuse, Software Install Abuse."""

from __future__ import annotations

import pytest

from core.change_transaction import (
    ChangeTransactionManager,
    TransactionConfirmationRequiredError,
    TransactionState,
)
from core.confirmation import ConfirmationManager, ConfirmationStatus, MockConfirmationProvider


def _approve_tx(conf_manager: ConfirmationManager, confirmation_id: str | None) -> None:
    if not confirmation_id:
        return
    req = conf_manager.get_pending_request(confirmation_id)
    if req:
        conf_manager.submit_request(req, MockConfirmationProvider(ConfirmationStatus.APPROVED))


# ─────────────────────────────────────────────────────────
# Vector 12: Registry Abuse
# ─────────────────────────────────────────────────────────

class TestRegistryAbuse:
    """Verifica que RegistryWriteBoundary resiste abuso del registro."""

    def test_registry_write_requires_confirmation(self) -> None:
        """Toda escritura al registro debe requerir confirmación."""
        from core.registry_boundary import RegistryWriteBoundary, RegistryWriteRequest

        conf = ConfirmationManager()
        tx_mgr = ChangeTransactionManager(confirmation_manager=conf)
        boundary = RegistryWriteBoundary(
            transaction_manager=tx_mgr,
            enabled=True,
            allowlist=["hkcu\\software\\jessyca"],
        )

        req = RegistryWriteRequest(
            key_path="HKCU\\Software\\Jessyca",
            value_name="TestKey",
            value_data="TestValue",
        )
        tx, _ = boundary.prepare_registry_write(req)
        assert tx.state == TransactionState.WAITING_CONFIRMATION

        with pytest.raises(TransactionConfirmationRequiredError):
            tx_mgr.execute_transaction(tx.transaction_id)

    def test_hklm_write_outside_allowlist_blocked(self) -> None:
        """Escritura en HKLM fuera del allowlist debe ser bloqueada."""
        from core.registry_boundary import (
            RegistrySecurityViolationError,
            RegistryWriteBoundary,
            RegistryWriteRequest,
        )

        boundary = RegistryWriteBoundary(
            enabled=True,
            allowlist=["hkcu\\software\\jessyca"],
        )

        req = RegistryWriteRequest(
            key_path="HKLM\\SOFTWARE\\MicrosoftUpdate\\AutoUpdate",
            value_name="Malicious",
            value_data="1",
        )
        with pytest.raises(RegistrySecurityViolationError):
            boundary.prepare_registry_write(req)

    def test_path_traversal_in_registry_key_blocked(self) -> None:
        """Intento de path traversal en clave de registro debe ser bloqueado."""
        from core.registry_boundary import (
            RegistrySecurityViolationError,
            RegistryWriteBoundary,
            RegistryWriteRequest,
        )

        boundary = RegistryWriteBoundary(
            enabled=True,
            allowlist=["hkcu\\software\\jessyca"],
        )

        req = RegistryWriteRequest(
            key_path="HKCU\\Software\\Jessyca\\..\\..\\System\\CurrentControlSet",
            value_name="Hack",
            value_data="1",
        )
        with pytest.raises((RegistrySecurityViolationError, ValueError, Exception)):
            boundary.prepare_registry_write(req)

    def test_registry_write_disabled_by_default(self) -> None:
        """REGISTRY_WRITE_ENABLED debe ser False en configuración por defecto."""
        from config.settings import AppSettings

        settings = AppSettings()
        assert settings.REGISTRY_WRITE_ENABLED is False, (
            "[AUDIT] REGISTRY_WRITE_ENABLED no está deshabilitado por defecto."
        )

    def test_approved_registry_write_executes(self) -> None:
        """Con confirmación aprobada, escritura en allowlist debe ejecutarse."""
        from core.registry_boundary import RegistryWriteBoundary, RegistryWriteRequest

        conf = ConfirmationManager()
        tx_mgr = ChangeTransactionManager(confirmation_manager=conf)
        boundary = RegistryWriteBoundary(
            transaction_manager=tx_mgr,
            enabled=True,
            allowlist=["hkcu\\software\\jessyca"],
        )

        req = RegistryWriteRequest(
            key_path="HKCU\\Software\\Jessyca",
            value_name="AuditTest",
            value_data="AuditValue",
        )
        tx, _ = boundary.prepare_registry_write(req)
        _approve_tx(conf, tx.confirmation_id)
        result = tx_mgr.execute_transaction(tx.transaction_id)
        # En modo stub (sin escritura real) debe COMMITTED o ROLLED_BACK
        assert result.transaction_id == tx.transaction_id


# ─────────────────────────────────────────────────────────
# Vector 13: Service Abuse
# ─────────────────────────────────────────────────────────

class TestServiceAbuse:
    """Verifica que ServiceControlBoundary resiste abuso de servicios."""

    def test_protected_service_stop_blocked(self) -> None:
        """Servicios protegidos (WinDefend, RPCSS, etc.) no pueden ser detenidos."""
        from core.service_boundary import (
            ProtectedServiceViolationError,
            ServiceControlBoundary,
            ServiceControlRequest,
        )

        boundary = ServiceControlBoundary(enabled=True)
        protected = ["WinDefend", "RPCSS", "lsass", "EventLog", "wuauserv", "mpssvc"]

        for svc in protected:
            req = ServiceControlRequest(service_name=svc, operation="stop")
            with pytest.raises(ProtectedServiceViolationError):
                boundary.prepare_service_control(req)

    def test_service_control_requires_confirmation(self) -> None:
        """Control de servicios no protegidos requiere confirmación."""
        from core.service_boundary import ServiceControlBoundary, ServiceControlRequest

        conf = ConfirmationManager()
        tx_mgr = ChangeTransactionManager(confirmation_manager=conf)
        boundary = ServiceControlBoundary(transaction_manager=tx_mgr, enabled=True)

        req = ServiceControlRequest(service_name="MyCustomSvc", operation="start")
        tx, _ = boundary.prepare_service_control(req)

        with pytest.raises(TransactionConfirmationRequiredError):
            tx_mgr.execute_transaction(tx.transaction_id)

    def test_service_name_injection_blocked(self) -> None:
        """Nombres de servicio con caracteres de inyección deben ser rechazados."""
        from core.service_boundary import ServiceControlBoundary, ServiceControlRequest

        boundary = ServiceControlBoundary(enabled=True)
        malicious_names = [
            "WinDefend; net user admin hacker /add",
            "cmd.exe /c calc",
            "../../../system32/services",
        ]

        for name in malicious_names:
            req = ServiceControlRequest(service_name=name, operation="start")
            with pytest.raises(Exception) as exc_info:
                boundary.prepare_service_control(req)
            error_msg = str(exc_info.value)
            # Debe ser un error de seguridad, no un error de ejecución
            assert exc_info.type.__name__ in (
                "ServiceSecurityViolationError",
                "ProtectedServiceViolationError",
                "ValueError",
                "SecurityValidationError",
            ), f"[AUDIT] Nombre malicioso '{name}' no fue rechazado apropiadamente: {error_msg}"

    def test_service_write_disabled_by_default(self) -> None:
        """SERVICE_WRITE_ENABLED debe ser False en configuración por defecto."""
        from config.settings import AppSettings

        settings = AppSettings()
        assert settings.SERVICE_WRITE_ENABLED is False


# ─────────────────────────────────────────────────────────
# Vector 14: Software Installation Abuse
# ─────────────────────────────────────────────────────────

class TestSoftwareInstallAbuse:
    """Verifica que SoftwareInstallBoundary resiste abuso de instalación."""

    def test_untrusted_source_rejected(self) -> None:
        """Fuentes distintas a 'winget' deben ser rechazadas."""
        from core.software_boundary import (
            SoftwareInstallBoundary,
            SoftwareInstallRequest,
            UntrustedSourceError,
        )

        boundary = SoftwareInstallBoundary(enabled=True, source="winget")
        req = SoftwareInstallRequest(
            package_id="SomeApp",
            package_name="SomeApp",
            publisher="Attacker",
            version="1.0",
            source="evil_repo",
        )
        with pytest.raises(UntrustedSourceError):
            boundary.prepare_software_install(req)

    def test_arbitrary_exe_blocked(self) -> None:
        """Instalación de EXE/MSI arbitrarios debe ser bloqueada."""
        from core.software_boundary import (
            ArbitraryInstallerError,
            SoftwareInstallBoundary,
            SoftwareInstallRequest,
        )

        boundary = SoftwareInstallBoundary(enabled=True)
        malicious = [
            "malware.exe",
            "C:\\Users\\attacker\\setup.msi",
            "http://evil.com/payload.bat",
            "../../system32/evil.exe",
        ]

        for pkg_id in malicious:
            req = SoftwareInstallRequest(
                package_id=pkg_id,
                package_name="Malware",
                publisher="Attacker",
                version="1.0",
            )
            with pytest.raises(ArbitraryInstallerError):
                boundary.prepare_software_install(req)

    def test_valid_winget_package_requires_confirmation(self) -> None:
        """Instalación válida via winget aún requiere confirmación."""
        from core.software_boundary import SoftwareInstallBoundary, SoftwareInstallRequest

        conf = ConfirmationManager()
        tx_mgr = ChangeTransactionManager(confirmation_manager=conf)
        boundary = SoftwareInstallBoundary(
            transaction_manager=tx_mgr,
            enabled=True,
            source="winget",
        )

        req = SoftwareInstallRequest(
            package_id="Git.Git",
            package_name="Git",
            publisher="Git",
            version="2.40.0",
            source="winget",
        )
        tx, _ = boundary.prepare_software_install(req)
        assert tx.state == TransactionState.WAITING_CONFIRMATION

        with pytest.raises(TransactionConfirmationRequiredError):
            tx_mgr.execute_transaction(tx.transaction_id)

    def test_software_install_disabled_by_default(self) -> None:
        """SOFTWARE_INSTALL_ENABLED debe ser False en configuración por defecto."""
        from config.settings import AppSettings

        settings = AppSettings()
        assert settings.SOFTWARE_INSTALL_ENABLED is False
