"""Motor formal de actualización atómica, comparación y rollback de Skills (skill_updater.py - Fase 33).

Implementa el ciclo completo de actualización:
    DISCOVER UPDATE -> VALIDATE -> COMPARE -> SECURITY CHECK -> DEPENDENCY CHECK
         -> STAGE -> TEST -> APPROVE -> ACTIVATE -> VERIFY -> KEEP / ROLLBACK

Garantiza:
1. ATOMICIDAD ABSOLUTA: Nunca deja OLD VERSION = DISABLED y NEW VERSION = BROKEN.
2. ROLLBACK DETERMINISTA: Ante cualquier fallo post-activación o en verificación, restaura la versión known-good previa.
3. INMUTABILIDAD DE SEGURIDAD: Ninguna actualización puede debilitar ni eludir el SecurityPipeline ni EmergencyStop.
4. AUDITORÍA EXHAUSTIVA: Todos los eventos de actualización y rollback quedan registrados en AuditLogger.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.emergency_stop import EmergencyStopManager
from core.exceptions import MCPError
from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.isolated_loader import IsolatedSkillLoader
from skills.skill_compatibility import SkillCompatibilityChecker
from skills.skill_dependency import SkillDependencyValidator
from skills.skill_diff import SkillChangeReport, SkillDiffer
from skills.skill_integrity import SkillIntegrityVerifier
from skills.skill_models import (
    SkillManifest,
)
from skills.skill_package import SkillPackage
from skills.skill_registry import SkillRegistry, get_skill_registry
from skills.skill_security_analyzer import SkillSecurityAnalyzer
from skills.skill_signature import SignatureStatus, SkillSignatureVerifier
from skills.skill_validator import SkillValidator

logger = get_logger("jessyca.skills.updater")

DEFAULT_INSTALLED_SKILLS_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "data" / "installed_skills"


class SkillUpdateError(MCPError):
    """Error emitido ante fallo durante la actualización de una Skill."""

    pass


@dataclass(frozen=True)
class UpdateResult:
    """Resultado formal inmutable de una operación de actualización de Skill."""

    success: bool
    skill_id: str
    old_version: str | None
    new_version: str
    change_report: SkillChangeReport | None = None
    installed_path: str | None = None
    error_message: str | None = None
    warnings: tuple[str, ...] = ()
    rolled_back: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "skill_id": self.skill_id,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "change_report": self.change_report.to_dict() if self.change_report else None,
            "installed_path": self.installed_path,
            "error_message": self.error_message,
            "warnings": list(self.warnings),
            "rolled_back": self.rolled_back,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class RollbackResult:
    """Resultado formal inmutable de una operación de rollback de Skill."""

    success: bool
    skill_id: str
    from_version: str
    to_version: str
    error_message: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "skill_id": self.skill_id,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "error_message": self.error_message,
            "timestamp": self.timestamp,
        }


class SkillUpdater:
    """Orquestador formal de actualizaciones y rollbacks de Skills para JESSYCA."""

    def __init__(
        self,
        install_root: Path | str | None = None,
        registry: SkillRegistry | None = None,
        signature_verifier: SkillSignatureVerifier | None = None,
        dependency_validator: SkillDependencyValidator | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.install_root = Path(install_root or DEFAULT_INSTALLED_SKILLS_DIR).resolve()
        self.install_root.mkdir(parents=True, exist_ok=True)
        self.registry = registry or get_skill_registry()
        self.signature_verifier = signature_verifier or SkillSignatureVerifier()
        self.dependency_validator = dependency_validator or SkillDependencyValidator(self.registry)
        self.emergency_stop = emergency_stop or EmergencyStopManager.get_instance()
        self.audit_logger = get_audit_logger()

    # ── 1. FLUJO FORMAL DE ACTUALIZACIÓN (UPDATE) ──

    def update_skill(
        self,
        package_source: str | Path | SkillPackage,
        enforce_signed: bool = False,
        require_confirmation: bool = False,
        user_confirmed: bool = False,
        simulate_verify_failure: bool = False,
    ) -> UpdateResult:
        """Ejecuta el flujo transaccional de actualización con verificación y rollback atómico."""
        with self._lock:
            staging_dir: Path | None = None
            target_dir: Path | None = None
            skill_id = "unknown"
            old_version: str | None = None
            new_version = "0.0.0"
            warnings: list[str] = []
            change_report: SkillChangeReport | None = None

            # 0. INVARIANTE: PREVALENCIA DE PARADA DE EMERGENCIA
            if self.emergency_stop.is_stopped():
                err_msg = "Parada de emergencia activa en el sistema. Actualización de Skill rechazada."
                logger.critical(f"[UPDATE BLOCKED] {err_msg}")
                self._log_audit(
                    event_type=AuditEventType.SECURITY_ALERT,
                    skill_id=skill_id,
                    operation="SKILL_UPDATE_BLOCKED",
                    success=False,
                    reason=err_msg,
                )
                return UpdateResult(
                    success=False,
                    skill_id=skill_id,
                    old_version=old_version,
                    new_version=new_version,
                    error_message=err_msg,
                )

            try:
                # ── ETAPA 1: DISCOVER UPDATE ──
                if isinstance(package_source, SkillPackage):
                    package = package_source
                else:
                    path = Path(package_source)
                    if path.is_dir():
                        package = SkillPackage.from_directory(path)
                    else:
                        package = SkillPackage.from_archive(path)

                skill_id = package.skill_id
                new_version = package.version
                new_manifest: SkillManifest = package.manifest

                # Identificar versión activa previa
                installed_versions = self.registry.get_installed_versions()
                old_version = installed_versions.get(skill_id)

                old_def = self.registry.lookup_definition(skill_id) if old_version else None
                old_manifest = old_def.manifest if old_def else None

                target_folder_name = f"{skill_id}_{new_version.replace('.', '_')}"
                target_dir = self.install_root / target_folder_name

                # Crear sandbox de staging
                staging_temp_obj = tempfile.TemporaryDirectory(prefix=f"jessyca_update_stage_{skill_id}_")
                staging_dir = Path(staging_temp_obj.name)

                # ── ETAPA 2: VALIDATE (Manifiesto, Integridad SHA-256 y Firma) ──
                val_ok, val_err = SkillValidator.validate_manifest(
                    new_manifest, installed_skills=installed_versions
                )
                if not val_ok:
                    raise SkillUpdateError(f"Validación de manifiesto rechazada: {val_err}")

                package.extract_to(staging_dir)

                # 2.1 Integridad
                integ_res = SkillIntegrityVerifier.verify_package(package, staged_dir=staging_dir)
                if not integ_res.is_valid:
                    raise SkillUpdateError(f"Violación de integridad en paquete de actualización: {integ_res.reason}")

                # 2.2 Firma digital
                sig_res = self.signature_verifier.verify_package(package, staged_dir=staging_dir)
                if sig_res.status in (SignatureStatus.INVALID_SIGNATURE, SignatureStatus.REVOKED_SIGNER):
                    raise SkillUpdateError(f"Firma digital rechazada ({sig_res.status}): {sig_res.reason}")
                if enforce_signed and sig_res.status != SignatureStatus.SIGNED:
                    raise SkillUpdateError(f"Política de seguridad exige firma digital, pero el paquete es '{sig_res.status}'.")

                # ── ETAPA 3: COMPARE (Generar SkillChangeReport) ──
                comp_res = SkillCompatibilityChecker.check_compatibility(new_manifest)
                change_report = SkillDiffer.compare(
                    old_manifest=old_manifest,
                    new_manifest=new_manifest,
                    signature_status=sig_res.status,
                    integrity_valid=integ_res.is_valid,
                    compatibility_result=comp_res,
                )
                warnings.extend(change_report.warnings)

                if not comp_res.is_compatible:
                    raise SkillUpdateError(f"Incompatibilidad de entorno detectada: {comp_res.reason}")

                # ── ETAPA 4: SECURITY CHECK (AST y Anti-Tampering) ──
                sec_res = SkillSecurityAnalyzer.analyze_directory(staging_dir, manifest=new_manifest)
                if not sec_res.is_safe:
                    raise SkillUpdateError(
                        f"Análisis estático de seguridad detectó violaciones: {'; '.join(sec_res.violations)}"
                    )
                warnings.extend(sec_res.warnings)

                # ── ETAPA 5: DEPENDENCY CHECK ──
                dep_res = self.dependency_validator.validate_dependencies(new_manifest)
                if not dep_res.is_valid:
                    raise SkillUpdateError(f"Fallo en resolución de dependencias para actualización: {dep_res.reason}")

                # ── ETAPA 6: TEST / DRY-RUN EN STAGING ──
                entry_path = staging_dir / new_manifest.entrypoint
                if not entry_path.exists():
                    raise SkillUpdateError(f"Archivo de entrada '{new_manifest.entrypoint}' no encontrado en paquete.")

                # Instanciación de prueba en aislamiento
                try:
                    test_instance = IsolatedSkillLoader.load_skill_instance(
                        installed_dir=staging_dir,
                        manifest=new_manifest,
                    )
                    if test_instance is None:
                        raise SkillUpdateError("No se pudo instanciar la clase de la Skill en prueba.")
                except Exception as exc:
                    raise SkillUpdateError(f"Fallo en prueba de carga aislada (dry-run): {exc}") from exc

                # ── ETAPA 7: APPROVE (Control de Usuario por Riesgo y Breaking Changes) ──
                if change_report.requires_user_confirmation or require_confirmation:
                    if not user_confirmed:
                        raise SkillUpdateError(
                            f"La actualización de '{skill_id}' a v{new_version} requiere confirmación explícita del usuario "
                            f"(Nivel de riesgo: {new_manifest.risk_level}, Breaking: {change_report.is_breaking})."
                        )

                # ── ETAPA 8: ACTIVATE (Commit atómico y cambio de versión en Registro) ──
                if target_dir.exists():
                    shutil.rmtree(target_dir, ignore_errors=True)
                shutil.copytree(staging_dir, target_dir)

                prod_instance = IsolatedSkillLoader.load_skill_instance(
                    installed_dir=target_dir,
                    manifest=new_manifest,
                )

                reg_ok, reg_err = self.registry.register_skill(prod_instance, replace=True)
                if not reg_ok:
                    raise SkillUpdateError(f"Fallo al registrar nueva versión en SkillRegistry: {reg_err}")

                self.registry.set_active_version(skill_id, new_version)

                # ── ETAPA 9: VERIFY (Post-Activation Probe) ──
                if simulate_verify_failure:
                    raise SkillUpdateError("Fallo simulado en sonda de verificación post-activación.")

                # Sonda de verificación real
                active_skill = self.registry.lookup(skill_id)
                actual_version = getattr(active_skill, "version", getattr(getattr(active_skill, "definition", None), "version", None))
                if active_skill is None or actual_version != new_version:
                    raise SkillUpdateError(f"Sonda de verificación falló: la versión activa no es '{new_version}'.")

                # ── ETAPA 10: KEEP (Éxito completo) ──
                self.registry.record_known_good(skill_id, new_version)
                shutil.rmtree(staging_dir, ignore_errors=True)

                logger.info(
                    f"[UPDATE SUCCESS] Skill '{skill_id}' actualizada con éxito de v{old_version} a v{new_version}."
                )

                self._log_audit(
                    event_type=AuditEventType.EXECUTION_SUCCEEDED,
                    skill_id=skill_id,
                    operation="SKILL_UPDATED",
                    success=True,
                    reason=f"Actualización exitosa v{old_version} -> v{new_version}",
                    metadata=change_report.to_dict() if change_report else {},
                )

                return UpdateResult(
                    success=True,
                    skill_id=skill_id,
                    old_version=old_version,
                    new_version=new_version,
                    change_report=change_report,
                    installed_path=str(target_dir),
                    warnings=tuple(warnings),
                    rolled_back=False,
                )

            except Exception as exc:
                # ── ETAPA 11: ROLLBACK ATÓMICO ANTE CUALQUIER FALLO ──
                logger.error(
                    f"[UPDATE FAILED] Error actualizando '{skill_id}' a v{new_version}: {exc}. Iniciando rollback atómico..."
                )

                # Limpiar directorios de fallo
                if staging_dir and staging_dir.exists():
                    shutil.rmtree(staging_dir, ignore_errors=True)

                if target_dir and target_dir.exists():
                    shutil.rmtree(target_dir, ignore_errors=True)

                # Desregistrar versión fallida
                self.registry.unregister_skill(f"{skill_id}@{new_version}")

                # Restaurar a versión known-good previa
                restored_version = None
                if old_version:
                    latest_good = self.registry.get_latest_known_good(skill_id, exclude_version=new_version)
                    target_restore = latest_good or old_version
                    if self.registry.lookup(f"{skill_id}@{target_restore}"):
                        self.registry.set_active_version(skill_id, target_restore)
                        self.registry.enable_skill(f"{skill_id}@{target_restore}")
                        restored_version = target_restore
                        logger.info(
                            f"[ROLLBACK SUCCESS] Skill '{skill_id}' restaurada atómicamente a versión funcional v{restored_version}."
                        )

                self._log_audit(
                    event_type=AuditEventType.EXECUTION_FAILED,
                    skill_id=skill_id,
                    operation="SKILL_UPDATE_ROLLED_BACK",
                    success=False,
                    reason=f"Fallo durante actualización a v{new_version}: {exc}. Restaurada a v{restored_version}",
                )

                return UpdateResult(
                    success=False,
                    skill_id=skill_id,
                    old_version=old_version,
                    new_version=new_version,
                    change_report=change_report,
                    error_message=str(exc),
                    warnings=tuple(warnings),
                    rolled_back=(restored_version is not None),
                )

    # ── 2. ROLLBACK EXPLÍCITO A DEMANDA ──

    def rollback_skill(
        self,
        skill_id: str,
        target_version: str | None = None,
        reason: str = "Rollback explícito solicitado por usuario o sistema",
    ) -> RollbackResult:
        """Ejecuta un rollback explícito a la versión funcional indicada o a la última known-good."""
        with self._lock:
            if self.emergency_stop.is_stopped():
                err = "Parada de emergencia activa. Operación de rollback denegada."
                logger.critical(f"[ROLLBACK BLOCKED] {err}")
                return RollbackResult(
                    success=False,
                    skill_id=skill_id,
                    from_version="unknown",
                    to_version="none",
                    error_message=err,
                )

            current_active = self.registry.get_installed_versions().get(skill_id)
            if not current_active:
                err = f"Skill '{skill_id}' no se encuentra registrada ni activa en el sistema."
                logger.warning(f"[ROLLBACK FAILED] {err}")
                return RollbackResult(
                    success=False,
                    skill_id=skill_id,
                    from_version="none",
                    to_version="none",
                    error_message=err,
                )

            # Determinar versión destino del rollback
            restore_ver: str | None = None
            if target_version:
                restore_ver = target_version
            else:
                restore_ver = self.registry.get_latest_known_good(skill_id, exclude_version=current_active)

            if not restore_ver:
                err = f"No existe una versión funcional previa (known-good) disponible para la skill '{skill_id}'."
                logger.warning(f"[ROLLBACK FAILED] {err}")
                return RollbackResult(
                    success=False,
                    skill_id=skill_id,
                    from_version=current_active,
                    to_version="none",
                    error_message=err,
                )

            # Verificar que la versión destino esté registrada
            target_instance = self.registry.lookup(f"{skill_id}@{restore_ver}")
            if not target_instance:
                err = f"La versión objetivo '{skill_id}@{restore_ver}' no se encuentra disponible en el catálogo."
                logger.warning(f"[ROLLBACK FAILED] {err}")
                return RollbackResult(
                    success=False,
                    skill_id=skill_id,
                    from_version=current_active,
                    to_version=restore_ver,
                    error_message=err,
                )

            # Deshabilitar versión actual y activar versión restaurada
            self.registry.disable_skill(f"{skill_id}@{current_active}")
            self.registry.set_active_version(skill_id, restore_ver)
            self.registry.enable_skill(f"{skill_id}@{restore_ver}")

            logger.info(
                f"[EXPLICIT ROLLBACK SUCCESS] Skill '{skill_id}' revertida exitosamente de v{current_active} a v{restore_ver}. Motivo: {reason}"
            )

            self._log_audit(
                event_type=AuditEventType.EXECUTION_SUCCEEDED,
                skill_id=skill_id,
                operation="SKILL_ROLLBACK_EXECUTED",
                success=True,
                reason=f"Rollback exitoso de v{current_active} a v{restore_ver}. {reason}",
            )

            return RollbackResult(
                success=True,
                skill_id=skill_id,
                from_version=current_active,
                to_version=restore_ver,
            )

    # ── MÉTODOS AUXILIARES Y AUDITORÍA ──

    def _log_audit(
        self,
        event_type: AuditEventType,
        skill_id: str,
        operation: str,
        success: bool,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            event = AuditEvent(
                event_type=event_type,
                user="system",
                tool_name=f"skill_updater.{skill_id}",
                operation=operation,
                security_level=SecurityLevel.SAFE if success else SecurityLevel.HIGH,
                success=success,
                reason=reason,
                metadata=metadata or {},
            )
            self.audit_logger.log_audit_event(event)
        except Exception as e:
            logger.warning(f"Error emitiendo evento de auditoría en SkillUpdater: {e}")
