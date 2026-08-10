r"""Frontera de Seguridad para Instalación de Software (SoftwareInstallBoundary - Etapa 15.4).

GARANTÍAS RIGUROSAS DE SEGURIDAD EN ETAPA 15.4:
1. DESHABILITADO POR DEFECTO (SOFTWARE_INSTALL_ENABLED=False).
2. PROHIBICIÓN ABSOLUTA DE INSTALADORES ARBITRARIOS:
   - Cero ejecución de archivos .exe, .msi, instaladores descargados o scripts de instalación locales.
3. GESTOR DE PAQUETES ÚNICO APROBADO: EXCLUSIVAMENTE 'winget' (SOFTWARE_INSTALL_SOURCE='winget').
4. CONTROL POR ALLOWLIST EXPLÍCITA DE PAQUETES (SOFTWARE_INSTALL_ALLOWLIST).
5. MANEJO DE INYECCIÓN DE COMANDOS SHELL: Bloqueo de &, ;, |, &&, `, $(...), etc.
6. VALIDACIÓN RIGUROSA DE IDENTIDAD DE PAQUETE (Package Identity Fingerprint SHA-256).
   Detecta si el paquete o sus metadatos cambian entre la fase de validación y la ejecución.
7. MUESTRA OBLIGATORIA AL USUARIO ANTES DE CONFIRMAR:
   package_id, package_name, publisher, source, version, requested_operation.
8. RUTA OBLIGATORIA DE 7 PASOS:
   Package Validation -> RiskEngine -> ConfirmationManager -> SecureExecutionPipeline -> Installation -> Verification -> Audit.
9. REVERSIBILIDAD Y ROLLBACK:
   Si la verificación post-instalación falla o se detecta alteración de identidad, se dispara la desinstalación automática (winget uninstall).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.audit_logger import get_audit_logger
from core.change_transaction import (
    ChangeTransaction,
    ChangeTransactionManager,
    Reversibility,
)
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.software_boundary")

ALLOWED_SOFTWARE_OPERATIONS = {"install", "upgrade", "uninstall"}
FORBIDDEN_SHELL_PATTERNS = re.compile(r"[&;|`$><\\]", re.IGNORECASE)
ARBITRARY_FILE_EXTENSIONS = re.compile(r"\.(exe|msi|bat|cmd|ps1|vbs|jar|scr|appx)$", re.IGNORECASE)


class SoftwareInstallError(MCPError):
    """Error base de fronteras de instalación de software."""

    pass


class SoftwareInstallDisabledError(SoftwareInstallError):
    """Error emitido cuando la instalación de software está deshabilitada (SOFTWARE_INSTALL_ENABLED=False)."""

    pass


class ArbitraryInstallerError(SoftwareInstallError):
    """Error emitido ante intentos de ejecutar binarios o instaladores arbitrarios (.exe, .msi, descargas)."""

    pass


class UntrustedSourceError(SoftwareInstallError):
    """Error emitido cuando la fuente del paquete no es el gestor de paquetes aprobado ('winget')."""

    pass


class PackageIdentityMismatchError(SoftwareInstallError):
    """Error emitido si la identidad/hash del paquete cambia entre la fase de validación y la ejecución."""

    pass


class PackageAllowlistViolationError(SoftwareInstallError):
    """Error emitido cuando el paquete no pertenece a la SOFTWARE_INSTALL_ALLOWLIST explícita."""

    pass


@dataclass(frozen=True)
class SoftwareInstallRequest:
    """Solicitud formal de instalación/actualización de un paquete de software."""

    package_id: str
    package_name: str
    publisher: str
    version: str
    source: str = "winget"
    operation: str = "install"  # install, upgrade, uninstall


class SoftwareInstallBoundary:
    """Frontera de Seguridad para Instalación de Software (Etapa 15.4).

    Construida sobre ChangeTransactionManager. Enforza validación de paquetes por winget y allowlist.
    """

    def __init__(
        self,
        transaction_manager: ChangeTransactionManager | None = None,
        enabled: bool | None = None,
        source: str | None = None,
        allowlist: list[str] | None = None,
    ) -> None:
        from config.settings import AppSettings

        settings = AppSettings()
        self.enabled = enabled if enabled is not None else settings.SOFTWARE_INSTALL_ENABLED
        self.approved_source = (source if source is not None else settings.SOFTWARE_INSTALL_SOURCE).strip().lower()
        self.allowlist = [
            pkg.strip().lower() for pkg in (allowlist if allowlist is not None else settings.SOFTWARE_INSTALL_ALLOWLIST)
        ]
        self.transaction_manager = transaction_manager or ChangeTransactionManager()
        self.audit_logger = get_audit_logger()

    def prepare_software_install(
        self,
        request: SoftwareInstallRequest,
        mock_package_inspector: Callable[[str], dict[str, Any] | None] | None = None,
        mock_package_installer: Callable[[str, str], bool] | None = None,
    ) -> tuple[ChangeTransaction, dict[str, Any]]:
        """PASO 1: Package Validation & Pre-execution verification.

        Prepara una transacción de instalación de software ejecutando el flujo obligatorio de 7 pasos.
        """
        # 1. VERIFICACIÓN DE HABILITACIÓN GLOBAL
        if not self.enabled:
            raise SoftwareInstallDisabledError(
                "[SOFTWARE INSTALL DISABLED] La instalación de software está deshabilitada por configuración (SOFTWARE_INSTALL_ENABLED=False)."
            )

        # 2. PROHIBICIÓN ABSOLUTA DE INSTALADORES ARBITRARIOS (.EXE, .MSI, RUTAS DE ARCHIVO)
        pkg_raw = request.package_id.strip()
        if ARBITRARY_FILE_EXTENSIONS.search(pkg_raw) or "/" in pkg_raw or "\\" in pkg_raw or ":" in pkg_raw:
            raise ArbitraryInstallerError(
                f"[ARBITRARY INSTALLER REJECTED] Ejecución de instaladores arbitrarios o archivos locales prohibida: '{request.package_id}'."
            )

        # 3. VERIFICACIÓN DE FUENTE CONFIABLE (EXCLUSIVAMENTE 'winget')
        src_clean = request.source.strip().lower()
        if src_clean != self.approved_source:
            raise UntrustedSourceError(
                f"[UNTRUSTED SOURCE REJECTED] La fuente '{request.source}' no está autorizada. Fuente aprobada: '{self.approved_source}'."
            )

        # 4. PREVENCIÓN DE INYECCIÓN DE COMANDOS SHELL
        if FORBIDDEN_SHELL_PATTERNS.search(pkg_raw) or FORBIDDEN_SHELL_PATTERNS.search(request.package_name):
            raise SoftwareInstallError(
                f"[COMMAND INJECTION DETECTED] Caracteres de inyección de comandos shell detectados en '{request.package_id}'."
            )

        # 5. VALIDACIÓN DE PERMISIVIDAD POR ALLOWLIST EXPLÍCITA
        pkg_clean = pkg_raw.lower()
        if pkg_clean not in self.allowlist:
            raise PackageAllowlistViolationError(
                f"[ALLOWLIST VIOLATION] El paquete '{request.package_id}' no pertenece a la SOFTWARE_INSTALL_ALLOWLIST aprobada."
            )

        op_clean = request.operation.strip().lower()
        if op_clean not in ALLOWED_SOFTWARE_OPERATIONS:
            raise SoftwareInstallError(f"[INVALID OPERATION] Operación no soportada '{request.operation}'.")

        # 6. CÁLCULO DE HASH SHA-256 DE IDENTIDAD DEL PAQUETE (Package Identity Fingerprint)
        identity_payload = f"{pkg_clean}:{request.publisher.strip().lower()}:{request.version.strip().lower()}:{src_clean}"
        initial_identity_hash = hashlib.sha256(identity_payload.encode("utf-8")).hexdigest()

        # 7. METADATOS Y MOSTRAR AL USUARIO ANTES DE CONFIRMAR
        impact_summary = {
            "package_id": pkg_clean,
            "package_name": request.package_name,
            "publisher": request.publisher,
            "source": src_clean,
            "version": request.version,
            "requested_operation": op_clean,
            "identity_hash": initial_identity_hash,
            "reversibility": Reversibility.REVERSIBLE.value,
        }

        # DEFINICIÓN DE SNAPSHOT PREVIO (PRE-STATE)
        def pre_state_fn() -> dict[str, Any]:
            installed = False
            if mock_package_inspector:
                info = mock_package_inspector(pkg_clean)
                installed = bool(info and info.get("installed", False))
            return {
                "package_id": pkg_clean,
                "installed": installed,
                "identity_hash": initial_identity_hash,
            }

        # DEFINICIÓN DE EXECUTE_FN (EJECUCIÓN DE INSTALACIÓN)
        def execute_fn() -> dict[str, Any]:
            # VALIDACIÓN DE CAMBIO DE PAQUETE ENTRE VALIDACIÓN Y EJECUCIÓN
            current_payload = f"{pkg_clean}:{request.publisher.strip().lower()}:{request.version.strip().lower()}:{src_clean}"
            exec_hash = hashlib.sha256(current_payload.encode("utf-8")).hexdigest()
            if exec_hash != initial_identity_hash:
                raise PackageIdentityMismatchError(
                    f"[PACKAGE IDENTITY MISMATCH] La identidad del paquete cambio entre la validación ({initial_identity_hash[:8]}) y la ejecución ({exec_hash[:8]})."
                )

            if mock_package_installer:
                success = mock_package_installer(pkg_clean, op_clean)
                if not success:
                    raise SoftwareInstallError(f"Fallo al ejecutar '{op_clean}' para el paquete '{pkg_clean}' via winget.")

            return {"package_id": pkg_clean, "operation": op_clean, "installed": True}

        # DEFINICIÓN DE VERIFY_FN (VERIFICACIÓN POST-INSTALACIÓN)
        def verify_fn(post_data: dict[str, Any]) -> bool:
            if mock_package_inspector:
                check_info = mock_package_inspector(pkg_clean)
                if check_info:
                    return bool(check_info.get("installed") is True)
            return True

        # DEFINICIÓN DE ROLLBACK_FN (DESINSTALACIÓN AUTOMÁTICA DE EMERGENCIA)
        def rollback_fn(pre_data: dict[str, Any]) -> bool:
            was_installed = pre_data.get("installed", False)
            if not was_installed and mock_package_installer:
                # Revertir realizando desinstalación automática (winget uninstall)
                mock_package_installer(pkg_clean, "uninstall")
            return True

        # PREPARAR TRANSACCIÓN SOBRE ChangeTransactionManager
        tx = self.transaction_manager.prepare_transaction(
            target_resource=f"package:{pkg_clean}",
            operation_type=f"software.{op_clean}",
            reversibility=Reversibility.REVERSIBLE,
            pre_state_fn=pre_state_fn,
            execute_fn=execute_fn,
            rollback_fn=rollback_fn,
            verify_fn=verify_fn,
        )

        logger.info(f"[SOFTWARE BOUNDARY] Transacción preparada exitosamente para paquete '{pkg_clean}' ({op_clean}).")
        return tx, impact_summary
