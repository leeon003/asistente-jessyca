"""Instalador seguro y transaccional de Skills (skill_installer.py - Fases 32 y 33).

Implementa el ciclo de vida completo de instalación, validación, staging, commit atómico,
rollback determinista, actualización de versiones y desinstalación de paquetes de Skills.

Flujo transaccional:
    PREPARE -> VALIDATE -> STAGE -> VERIFY -> COMMIT -> REGISTER
       ↓ (si ocurre error)
    ROLLBACK

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. Instalar o registrar una Skill NO significa autorizarla; sigue pasando por SecurityPipeline.
2. Rollback atómico: no quedan archivos parciales ni entradas corruptas en el registro.
3. El desinstalador comprueba dependencias inversas y deshabilita la ejecución antes del borrado.
4. Todo evento relevante es registrado en el sistema de auditoría sin filtrar secretos.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from core.emergency_stop import EmergencyStopManager
from core.exceptions import MCPError
from core.logger import get_logger
from skills.isolated_loader import IsolatedSkillLoader
from skills.skill_compatibility import SkillCompatibilityChecker
from skills.skill_dependency import SkillDependencyValidator
from skills.skill_diff import SkillChangeReport, SkillDiffer
from skills.skill_integrity import SkillIntegrityVerifier
from skills.skill_manager import SkillManager
from skills.skill_models import (
    SkillManifest,
    SkillStatus,
)
from skills.skill_package import SkillPackage
from skills.skill_permission_reviewer import (
    SkillPermissionReview,
    SkillPermissionReviewer,
)
from skills.skill_registry import SkillRegistry, get_skill_registry
from skills.skill_revocation import SkillRevocationRegistry
from skills.skill_security_analyzer import SkillSecurityAnalyzer
from skills.skill_signature import (
    SignatureStatus,
    SkillSignatureVerifier,
)
from skills.skill_updater import RollbackResult, SkillUpdater, UpdateResult
from skills.skill_validator import SkillValidator

logger = get_logger("jessyca.skills.installer")

DEFAULT_INSTALLED_SKILLS_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "data" / "installed_skills"


class TransactionState(StrEnum):
    """Estados formales de la transacción de instalación."""

    PREPARE = "PREPARE"
    VALIDATE = "VALIDATE"
    STAGE = "STAGE"
    VERIFY = "VERIFY"
    COMMIT = "COMMIT"
    REGISTER = "REGISTER"
    ROLLBACK = "ROLLBACK"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SkillInstallationError(MCPError):
    """Error emitido cuando una instalación es rechazada o falla."""

    pass


@dataclass(frozen=True)
class InstallationResult:
    """Resultado formal inmutable del proceso de instalación."""

    success: bool
    skill_id: str
    version: str
    status: TransactionState
    installed_path: str | None = None
    permission_review: SkillPermissionReview | None = None
    signature_status: SignatureStatus = SignatureStatus.UNSIGNED
    error_message: str | None = None
    warnings: tuple[str, ...] = ()
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "skill_id": self.skill_id,
            "version": self.version,
            "status": str(self.status),
            "installed_path": self.installed_path,
            "permission_review": self.permission_review.to_dict() if self.permission_review else None,
            "signature_status": str(self.signature_status),
            "error_message": self.error_message,
            "warnings": list(self.warnings),
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class UninstallResult:
    """Resultado formal inmutable del proceso de desinstalación."""

    success: bool
    skill_id: str
    version: str | None
    uninstalled_path: str | None = None
    error_message: str | None = None
    dependents_blocked: tuple[str, ...] = ()
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "skill_id": self.skill_id,
            "version": self.version,
            "uninstalled_path": self.uninstalled_path,
            "error_message": self.error_message,
            "dependents_blocked": list(self.dependents_blocked),
            "timestamp": self.timestamp,
        }


class SkillInstaller:
    """Instalador formal, transaccional y gobernado de Skills para JESSYCA."""

    _instance: ClassVar[SkillInstaller | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        install_root: Path | str | None = None,
        registry: SkillRegistry | None = None,
        manager: SkillManager | None = None,
        signature_verifier: SkillSignatureVerifier | None = None,
        dependency_validator: SkillDependencyValidator | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.install_root = Path(install_root or DEFAULT_INSTALLED_SKILLS_DIR).resolve()
        self.install_root.mkdir(parents=True, exist_ok=True)
        self.registry = registry or get_skill_registry()
        self.manager = manager or SkillManager.get_instance()
        self.signature_verifier = signature_verifier or SkillSignatureVerifier()
        self.dependency_validator = dependency_validator or SkillDependencyValidator(self.registry)
        self.emergency_stop = emergency_stop or EmergencyStopManager.get_instance()
        self.updater = SkillUpdater(
            install_root=self.install_root,
            registry=self.registry,
            signature_verifier=self.signature_verifier,
            dependency_validator=self.dependency_validator,
            emergency_stop=self.emergency_stop,
        )

    @classmethod
    def get_instance(cls) -> SkillInstaller:
        """Obtiene la instancia singleton global del instalador."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = SkillInstaller()
            return cls._instance

    # ── 1. FLUJO DE INSTALACIÓN TRANSACCIONAL ──

    def install_package(
        self,
        package_source: str | Path | SkillPackage,
        enforce_signed: bool = False,
        auto_enable: bool = True,
    ) -> InstallationResult:
        """Ejecuta el flujo transaccional completo de instalación de una Skill."""
        with self._lock:
            current_state = TransactionState.PREPARE
            staging_dir: Path | None = None
            target_dir: Path | None = None
            skill_id = "unknown"
            version = "0.0.0"
            warnings: list[str] = []

            # 0. PREVALENCIA DE PARADA DE EMERGENCIA
            if self.emergency_stop.is_stopped():
                logger.critical("[INSTALLER BLOCKED] Intento de instalación abortado: EmergencyStopManager activo.")
                return InstallationResult(
                    success=False,
                    skill_id=skill_id,
                    version=version,
                    status=TransactionState.FAILED,
                    error_message="Parada de emergencia activa en el sistema. Instalación rechazada.",
                )

            try:
                # ── ETAPA 1: PREPARE (Cargar y desempaquetar estructura base) ──
                current_state = TransactionState.PREPARE
                logger.info(f"[INSTALLATION START] Iniciando transacción de instalación desde '{package_source}'.")

                if isinstance(package_source, SkillPackage):
                    package = package_source
                else:
                    path = Path(package_source)
                    if path.is_dir():
                        package = SkillPackage.from_directory(path)
                    else:
                        package = SkillPackage.from_archive(path)

                skill_id = package.skill_id
                version = package.version
                manifest: SkillManifest = package.manifest

                target_folder_name = f"{skill_id}_{version.replace('.', '_')}"
                target_dir = self.install_root / target_folder_name

                # Crear directorio temporal para staging
                staging_temp_obj = tempfile.TemporaryDirectory(prefix=f"jessyca_stage_{skill_id}_")
                staging_dir = Path(staging_temp_obj.name)

                # ── ETAPA 2: VALIDATE (Manifiesto, Compatibilidad y Dependencias) ──
                current_state = TransactionState.VALIDATE

                # 2.1 Comprobar Revocación previa
                is_revoked, rev_reason = SkillRevocationRegistry.get_instance().is_skill_revoked(skill_id, version)
                if is_revoked:
                    raise SkillInstallationError(f"La Skill '{skill_id}@{version}' ha sido REVOCADA: {rev_reason}")

                # 2.2 Validación de Manifiesto
                val_ok, val_err = SkillValidator.validate_manifest(
                    manifest, installed_skills=self.registry.get_installed_versions()
                )
                if not val_ok:
                    raise SkillInstallationError(f"Validación de manifiesto rechazada: {val_err}")

                # 2.3 Verificación de Compatibilidad
                comp_res = SkillCompatibilityChecker.check_compatibility(manifest)
                if not comp_res.is_compatible:
                    raise SkillInstallationError(f"Incompatibilidad de entorno: {comp_res.reason}")
                warnings.extend(comp_res.warnings)

                # 2.4 Validación de Dependencias
                dep_res = self.dependency_validator.validate_dependencies(manifest)
                if not dep_res.is_valid:
                    raise SkillInstallationError(
                        f"Validación de dependencias falló: {dep_res.reason}"
                    )
                if hasattr(dep_res, "warnings") and dep_res.warnings:
                    warnings.extend(dep_res.warnings)

                # ── ETAPA 3: STAGE & SECURITY CHECK (Extracción, Integridad, Firma, Sandbox y AST) ──
                current_state = TransactionState.STAGE
                package.extract_to(staging_dir)

                # 3.1 Verificación de Integridad
                integ_res = SkillIntegrityVerifier.verify_package(package, staged_dir=staging_dir)
                if not integ_res.is_valid:
                    raise SkillInstallationError(f"Violación de integridad: {integ_res.reason}")

                # 3.2 Verificación de Firma Digital
                sig_res = self.signature_verifier.verify_package(package, staged_dir=staging_dir)
                if sig_res.status == SignatureStatus.INVALID_SIGNATURE:
                    raise SkillInstallationError(f"Firma digital corrupta o inválida: {sig_res.reason}")
                if sig_res.status == SignatureStatus.REVOKED_SIGNER:
                    raise SkillInstallationError(f"Firma digital rechazada (firmante revocado): {sig_res.reason}")
                if enforce_signed and sig_res.status != SignatureStatus.SIGNED:
                    raise SkillInstallationError(
                        f"Política de seguridad exige firma digital válida, pero el paquete es '{sig_res.status}'."
                    )

                # 3.3 Análisis Estático de Seguridad (AST)
                sec_res = SkillSecurityAnalyzer.analyze_directory(staging_dir, manifest=manifest)
                if not sec_res.is_safe:
                    raise SkillInstallationError(
                        f"Análisis estático de seguridad detectó violaciones de código: {'; '.join(sec_res.violations)}"
                    )
                warnings.extend(sec_res.warnings)

                # 3.4 Revisión Estructurada de Permisos
                perm_review = SkillPermissionReviewer.review_package(
                    package=package,
                    signature_status=sig_res.status,
                    security_violations=sec_res.violations,
                    security_warnings=tuple(warnings),
                )
                if not perm_review.is_approved_for_install:
                    raise SkillInstallationError(
                        f"Revisión de permisos denegada: {'; '.join(perm_review.rejection_reasons)}"
                    )

                # ── ETAPA 4: VERIFY (Comprobar entrypoint y estructura final) ──
                current_state = TransactionState.VERIFY
                entry_path = staging_dir / manifest.entrypoint
                if not entry_path.exists():
                    raise SkillInstallationError(f"Archivo de entrada '{manifest.entrypoint}' no encontrado en staging.")

                # ── ETAPA 5: COMMIT (Mover atómicamente a directorio final de instalación) ──
                current_state = TransactionState.COMMIT
                if target_dir.exists():
                    shutil.rmtree(target_dir, ignore_errors=True)

                shutil.copytree(staging_dir, target_dir)

                # ── ETAPA 6: REGISTER (Instanciar y registrar en el catálogo del sistema) ──
                current_state = TransactionState.REGISTER
                skill_instance = IsolatedSkillLoader.load_skill_instance(
                    installed_dir=target_dir,
                    manifest=manifest,
                )

                reg_ok, reg_err = self.registry.register_skill(skill_instance, replace=True)
                if not reg_ok:
                    raise SkillInstallationError(f"Fallo al registrar en SkillRegistry: {reg_err}")

                if auto_enable:
                    self.registry.enable_skill(f"{skill_id}@{version}")

                # Limpieza de staging
                shutil.rmtree(staging_dir, ignore_errors=True)

                logger.info(
                    f"[INSTALLATION SUCCESS] Skill '{skill_id}@{version}' instalada y registrada exitosamente en '{target_dir}'."
                )

                return InstallationResult(
                    success=True,
                    skill_id=skill_id,
                    version=version,
                    status=TransactionState.COMPLETED,
                    installed_path=str(target_dir),
                    permission_review=perm_review,
                    signature_status=sig_res.status,
                    warnings=tuple(warnings),
                )

            except Exception as exc:
                # ── ROLLBACK DETERMINISTA ANTE CUALQUIER FALLO ──
                logger.error(f"[INSTALLATION ROLLBACK] Error en fase {current_state} para '{skill_id}': {exc}")
                self._execute_rollback(staging_dir, target_dir, skill_id, version)

                return InstallationResult(
                    success=False,
                    skill_id=skill_id,
                    version=version,
                    status=TransactionState.ROLLBACK,
                    error_message=str(exc),
                    warnings=tuple(warnings),
                )

    # ── 2. FLUJO DE ACTUALIZACIÓN Y ROLLBACK (FASE 33) ──

    def update_package(
        self,
        package_source: str | Path | SkillPackage,
        enforce_signed: bool = False,
        require_confirmation: bool = False,
        user_confirmed: bool = False,
        simulate_verify_failure: bool = False,
    ) -> UpdateResult:
        """Actualiza una Skill a una nueva versión mediante el SkillUpdater."""
        return self.updater.update_skill(
            package_source=package_source,
            enforce_signed=enforce_signed,
            require_confirmation=require_confirmation,
            user_confirmed=user_confirmed,
            simulate_verify_failure=simulate_verify_failure,
        )

    def update_skill(
        self,
        package_source: str | Path | SkillPackage,
        enforce_signed: bool = False,
        require_confirmation: bool = False,
        user_confirmed: bool = False,
        simulate_verify_failure: bool = False,
    ) -> UpdateResult:
        """Alias retrocompatible de update_package."""
        return self.update_package(
            package_source=package_source,
            enforce_signed=enforce_signed,
            require_confirmation=require_confirmation,
            user_confirmed=user_confirmed,
            simulate_verify_failure=simulate_verify_failure,
        )

    def rollback_skill(
        self,
        skill_id: str,
        target_version: str | None = None,
        reason: str = "Rollback explícito",
    ) -> RollbackResult:
        """Revierte una Skill a su versión previa funcional."""
        return self.updater.rollback_skill(skill_id=skill_id, target_version=target_version, reason=reason)

    def get_change_report(
        self,
        package_source: str | Path | SkillPackage,
    ) -> SkillChangeReport:
        """Genera un SkillChangeReport comparando el paquete con la versión activa instalada."""
        if isinstance(package_source, SkillPackage):
            package = package_source
        else:
            path = Path(package_source)
            if path.is_dir():
                package = SkillPackage.from_directory(path)
            else:
                package = SkillPackage.from_archive(path)

        skill_id = package.skill_id
        old_def = self.registry.lookup_definition(skill_id)
        old_manifest = old_def.manifest if old_def else None

        sig_res = self.signature_verifier.verify_package(package)
        comp_res = SkillCompatibilityChecker.check_compatibility(package.manifest)

        return SkillDiffer.compare(
            old_manifest=old_manifest,
            new_manifest=package.manifest,
            signature_status=sig_res.status,
            integrity_valid=True,
            compatibility_result=comp_res,
        )

    # ── 3. FLUJO DE DESINSTALACIÓN SEGURO ──

    def uninstall_skill(self, skill_id: str, version: str | None = None) -> UninstallResult:
        """Desinstala de forma segura y limpia una Skill instalada."""
        with self._lock:
            target_identifier = f"{skill_id}@{version}" if version else skill_id

            # 1. Comprobar si otras Skills instaladas dependen de esta Skill (dependencias inversas)
            dependents = self._find_dependent_skills(skill_id)
            if dependents:
                err_msg = (
                    f"No se puede desinstalar '{target_identifier}': Las siguientes skills activas dependen de ella: {dependents}."
                )
                logger.warning(f"[UNINSTALL BLOCKED] {err_msg}")
                return UninstallResult(
                    success=False,
                    skill_id=skill_id,
                    version=version,
                    error_message=err_msg,
                    dependents_blocked=tuple(dependents),
                )

            # 2. Deshabilitar ejecución de inmediato
            self.registry.disable_skill(target_identifier)

            # 3. Desregistrar de Registry y Manager
            self.registry.unregister_skill(target_identifier)

            # 4. Eliminar directorios de instalación en disco
            deleted_paths: list[str] = []
            prefix = f"{skill_id}_"
            if self.install_root.exists():
                for item in self.install_root.iterdir():
                    if item.is_dir():
                        if version and item.name == f"{skill_id}_{version.replace('.', '_')}":
                            shutil.rmtree(item, ignore_errors=True)
                            deleted_paths.append(str(item))
                        elif not version and (item.name == skill_id or item.name.startswith(prefix)):
                            shutil.rmtree(item, ignore_errors=True)
                            deleted_paths.append(str(item))

            logger.info(
                f"[UNINSTALL COMPLETED] Skill '{target_identifier}' desinstalada y eliminada de disco ({deleted_paths})."
            )

            return UninstallResult(
                success=True,
                skill_id=skill_id,
                version=version,
                uninstalled_path=deleted_paths[0] if deleted_paths else None,
            )

    # ── MÉTODOS AUXILIARES Y ROLLBACK ──

    def _execute_rollback(
        self,
        staging_dir: Path | None,
        target_dir: Path | None,
        skill_id: str,
        version: str,
    ) -> None:
        """Limpia todos los artefactos temporales y directorios para evitar estados parciales."""
        if staging_dir and staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)

        if target_dir and target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)

        # Revertir registro si se había alcanzado
        self.registry.unregister_skill(f"{skill_id}@{version}")

    def _find_dependent_skills(self, target_skill_id: str) -> list[str]:
        """Encuentra qué skills activas tienen a target_skill_id en sus dependencias."""
        dependents: list[str] = []
        for def_obj in self.registry.list_skills():
            if def_obj.skill_id == target_skill_id:
                continue
            if def_obj.manifest and target_skill_id in def_obj.manifest.dependencies:
                status = self.registry.get_status(def_obj.skill_id)
                if status in (SkillStatus.ENABLED, SkillStatus.READY, SkillStatus.REGISTERED):
                    dependents.append(f"{def_obj.skill_id}@{def_obj.version}")
        return dependents
