"""Servicio de Marketplace y Distribución Segura de Skills (skill_marketplace.py - Fase 34).

Orquesta de forma gobernada:
1. Búsqueda y descubrimiento de Skills.
2. Consulta e inspección previa de metadatos, permisos, dependencias y riesgos.
3. Validación estricta contra el Registro de Revocaciones (Skill y Firmante).
4. Descarga segura de paquetes (.skpkg) delegando la instalación formal a SkillInstaller y SkillUpdater.
5. Reporte de seguridad y anomalías con sanitización automática de secretos.

INVARIANTES DE SEGURIDAD INVIOLABLES:
- El Marketplace NUNCA ejecuta código directamente (NO download-and-execute).
- El Marketplace entrega el paquete descargado a SkillInstaller para que aplique todas las validaciones locales:
  Integridad SHA-256, Firma Criptográfica, Compatibilidad SemVer, Sandbox AST, Dependencias y Confirmación de Usuario.
- El Marketplace NO puede eludir SecurityPipeline, RiskEngine, PermissionManager ni EmergencyStopManager.
"""

from __future__ import annotations

import datetime
import tempfile
from pathlib import Path
from typing import Any

from core.audit_logger import AuditEventType, AuditLogger, get_audit_logger
from core.emergency_stop import EmergencyStopManager
from core.logger import get_logger
from skills.skill_installer import (
    InstallationResult,
    SkillInstaller,
    TransactionState,
    UninstallResult,
)
from skills.skill_repository import (
    BaseSkillRepository,
    RepositoryError,
)
from skills.skill_repository_models import (
    RepositorySkillEntry,
    SkillReport,
    TrustStatus,
)
from skills.skill_revocation import (
    SkillRevocationRegistry,
)
from skills.skill_updater import (
    RollbackResult,
    SkillUpdater,
    UpdateResult,
)

logger = get_logger("jessyca.skills.marketplace")


class SkillMarketplaceError(Exception):
    """Excepción base para operaciones del Marketplace."""


class SkillMarketplaceService:
    """Cliente y servicio central del Marketplace de Skills de JESSYCA."""

    def __init__(
        self,
        repository: BaseSkillRepository,
        installer: SkillInstaller,
        updater: SkillUpdater | None = None,
        revocation_registry: SkillRevocationRegistry | None = None,
        audit_logger: AuditLogger | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.repository = repository
        self.installer = installer
        self.updater = updater or getattr(installer, "updater", None)
        self.revocation_registry = revocation_registry or SkillRevocationRegistry.get_instance()
        self.audit_logger = audit_logger or get_audit_logger()
        self.emergency_stop = emergency_stop or EmergencyStopManager.get_instance()

        # Registro interno de reportes recibidos
        self._submitted_reports: list[SkillReport] = []

    def _log_audit(
        self,
        event_type: AuditEventType,
        operation: str,
        success: bool,
        tool_name: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            from core.audit_logger import AuditEvent
            from core.security_architecture import SecurityLevel
            event = AuditEvent(
                event_type=event_type,
                user="system",
                tool_name=tool_name,
                operation=operation,
                security_level=SecurityLevel.SAFE if success else SecurityLevel.HIGH,
                success=success,
                reason=reason,
                metadata=metadata or {},
            )
            self.audit_logger.log_audit_event(event)
        except Exception as e:
            logger.error(f"[AUDIT LOG ERROR] No se pudo registrar evento de auditoría en Marketplace: {e}")

    def search_skills(
        self,
        query: str = "",
        category: str | None = None,
        tags: tuple[str, ...] | None = None,
        limit: int = 20,
    ) -> list[RepositorySkillEntry]:
        """Busca Skills en el catálogo del repositorio."""
        try:
            results = self.repository.search(query=query, category=category, tags=tags, limit=limit)
            self._log_audit(
                event_type=AuditEventType.POLICY_EVALUATED,
                operation="MARKETPLACE_SEARCH",
                success=True,
                tool_name="marketplace.search",
                reason=f"Búsqueda ejecutada (Query: '{query}', Resultados: {len(results)})",
                metadata={"query": query, "count": len(results)},
            )
            return results
        except RepositoryError as exc:
            self._log_audit(
                event_type=AuditEventType.POLICY_EVALUATED,
                operation="MARKETPLACE_SEARCH_FAILED",
                success=False,
                tool_name="marketplace.search",
                reason=str(exc),
            )
            raise

    def get_skill_details(self, skill_id: str, version: str | None = None) -> RepositorySkillEntry | None:
        """Obtiene los metadatos completos y estado de confianza de una Skill."""
        meta = self.repository.get_metadata(skill_id, version)
        if meta is None:
            return None

        # Comprobar si la Skill está en el registro de revocaciones local
        is_revoked, rev_reason = self.revocation_registry.is_skill_revoked(skill_id, meta.version)
        if is_revoked:
            # Crear una nueva entrada marcando el TrustStatus como REVOKED
            meta = RepositorySkillEntry(
                id=meta.id,
                name=meta.name,
                version=meta.version,
                description=meta.description,
                author=meta.author,
                category=meta.category,
                capabilities=meta.capabilities,
                required_tools=meta.required_tools,
                required_agents=meta.required_agents,
                required_models=meta.required_models,
                permissions=meta.permissions,
                risk_level=meta.risk_level,
                dependencies=meta.dependencies,
                framework_version=meta.framework_version,
                min_system_version=meta.min_system_version,
                max_system_version=meta.max_system_version,
                min_framework_version=meta.min_framework_version,
                max_framework_version=meta.max_framework_version,
                signer_id=meta.signer_id,
                signature_hex=meta.signature_hex,
                package_sha256=meta.package_sha256,
                download_url=meta.download_url,
                release_date=meta.release_date,
                changelog=meta.changelog,
                trust_status=TrustStatus.REVOKED,
                reputation=meta.reputation,
                tags=meta.tags,
            )

        return meta

    def get_skill_versions(self, skill_id: str) -> list[str]:
        """Obtiene la lista de versiones disponibles de una Skill."""
        return self.repository.get_versions(skill_id)

    def install_from_marketplace(
        self,
        skill_id: str,
        version: str | None = None,
        user_confirmed: bool = False,
        enforce_signed: bool = False,
    ) -> InstallationResult | UpdateResult:
        """Descarga e instala o actualiza una Skill desde el Marketplace.

        INVARIANTE CRÍTICO:
        1. Comprueba Parada de Emergencia.
        2. Verifica que la Skill ni su firmante estén revocados.
        3. Descarga el paquete .skpkg a un archivo temporal.
        4. Entrega el paquete a SkillInstaller / SkillUpdater para ejecutar todas las validaciones locales.
        """
        # 1. Parada de Emergencia
        if self.emergency_stop.is_stopped():
            err_msg = "Parada de emergencia activa. Operación en Marketplace bloqueada."
            logger.error(f"[MARKETPLACE BLOCKED] {err_msg}")
            self._log_audit(
                event_type=AuditEventType.EXECUTION_DENIED,
                operation="MARKETPLACE_INSTALL_ABORTED",
                success=False,
                tool_name=f"marketplace.install.{skill_id}",
                reason=err_msg,
            )
            return InstallationResult(
                success=False,
                skill_id=skill_id,
                version=version or "0.0.0",
                status=TransactionState.FAILED,
                error_message=err_msg,
            )

        # 2. Comprobar Revocación previa de la Skill
        is_revoked, rev_reason = self.revocation_registry.is_skill_revoked(skill_id, version)
        if is_revoked:
            err_msg = f"Instalación bloqueada: La Skill '{skill_id}' ha sido REVOCADA ({rev_reason})."
            logger.error(f"[MARKETPLACE BLOCKED] {err_msg}")
            self._log_audit(
                event_type=AuditEventType.SECURITY_ALERT,
                operation="MARKETPLACE_INSTALL_REVOKED_SKILL_REJECTED",
                success=False,
                tool_name=f"marketplace.install.{skill_id}",
                reason=err_msg,
            )
            return InstallationResult(
                success=False,
                skill_id=skill_id,
                version=version or "0.0.0",
                status=TransactionState.FAILED,
                error_message=err_msg,
            )

        # 3. Comprobar metadatos y firmante
        meta = self.repository.get_metadata(skill_id, version)
        if meta and meta.signer_id:
            is_sig_revoked, sig_rev_reason = self.revocation_registry.is_signer_revoked(meta.signer_id)
            if is_sig_revoked:
                err_msg = f"Instalación bloqueada: El firmante '{meta.signer_id}' ha sido REVOCADO ({sig_rev_reason})."
                logger.error(f"[MARKETPLACE BLOCKED] {err_msg}")
                self._log_audit(
                    event_type=AuditEventType.SECURITY_ALERT,
                    operation="MARKETPLACE_INSTALL_REVOKED_SIGNER_REJECTED",
                    success=False,
                    tool_name=f"marketplace.install.{skill_id}",
                    reason=err_msg,
                )
                return InstallationResult(
                    success=False,
                    skill_id=skill_id,
                    version=version or "0.0.0",
                    status=TransactionState.FAILED,
                    error_message=err_msg,
                )

        # 4. Descargar paquete a directorio temporal
        temp_dl_dir = Path(tempfile.mkdtemp(prefix="jessyca_marketplace_dl_"))
        try:
            package = self.repository.download_package(
                skill_id=skill_id,
                version=version,
                destination_dir=temp_dl_dir,
            )

            # Comprobar revocación sobre la versión concreta del paquete descargado
            pkg_ver = package.manifest.version
            is_rev_pkg, rev_pkg_reason = self.revocation_registry.is_skill_revoked(skill_id, pkg_ver)
            if is_rev_pkg:
                err_msg = f"Instalación bloqueada: La versión descargada '{skill_id}@{pkg_ver}' está REVOCADA ({rev_pkg_reason})."
                logger.error(f"[MARKETPLACE BLOCKED] {err_msg}")
                return InstallationResult(
                    success=False,
                    skill_id=skill_id,
                    version=pkg_ver,
                    status=TransactionState.FAILED,
                    error_message=err_msg,
                )

            # 5. Determinar si es una instalación nueva o una actualización
            is_installed = self.installer.registry.lookup(skill_id) is not None

            res: InstallationResult | UpdateResult
            if is_installed:
                logger.info(f"[MARKETPLACE] Skill '{skill_id}' ya instalada. Ejecutando flujo de actualización (Fase 33)...")
                res = self.installer.update_package(
                    package,
                    user_confirmed=user_confirmed,
                    enforce_signed=enforce_signed,
                )
            else:
                logger.info(f"[MARKETPLACE] Instalando nueva Skill '{skill_id}' vía SkillInstaller (Fase 32)...")
                res = self.installer.install_package(
                    package,
                    enforce_signed=enforce_signed,
                )

            self._log_audit(
                event_type=AuditEventType.EXECUTION_SUCCEEDED if res.success else AuditEventType.EXECUTION_FAILED,
                operation="MARKETPLACE_INSTALL_COMPLETED",
                success=res.success,
                tool_name=f"marketplace.install.{skill_id}",
                reason=f"Resultado: success={res.success}",
                metadata={"skill_id": skill_id, "is_update": is_installed},
            )
            return res

        except Exception as exc:
            err_msg = f"Fallo al obtener e instalar paquete desde Marketplace: {exc}"
            logger.error(f"[MARKETPLACE ERROR] {err_msg}")
            self._log_audit(
                event_type=AuditEventType.EXECUTION_FAILED,
                operation="MARKETPLACE_INSTALL_ERROR",
                success=False,
                tool_name=f"marketplace.install.{skill_id}",
                reason=err_msg,
            )
            return InstallationResult(
                success=False,
                skill_id=skill_id,
                version=version or "0.0.0",
                status=TransactionState.FAILED,
                error_message=err_msg,
            )
        finally:
            import shutil
            shutil.rmtree(temp_dl_dir, ignore_errors=True)

    def rollback_skill(self, skill_id: str, target_version: str | None = None, reason: str = "") -> RollbackResult:
        """Ejecuta un rollback gobernado de una Skill instalada."""
        return self.installer.rollback_skill(skill_id, target_version=target_version, reason=reason)

    def uninstall_skill(self, skill_id: str, version: str | None = None) -> UninstallResult:
        """Desinstala una versión o la Skill completa."""
        return self.installer.uninstall_skill(skill_id, version=version)

    def submit_report(self, report: SkillReport) -> dict[str, Any]:
        """Registra un reporte formal de seguridad o anomalía."""
        timestamp = datetime.datetime.now(datetime.UTC).isoformat()
        final_report = SkillReport(
            skill_id=report.skill_id,
            version=report.version,
            report_type=report.report_type,
            reporter_id=report.reporter_id,
            description=report.description,
            details=report.details,
            timestamp=timestamp,
        )

        self._submitted_reports.append(final_report)
        logger.warning(
            f"[MARKETPLACE REPORT] Reporte recibido para '{final_report.skill_id}@{final_report.version}' "
            f"(Tipo: {final_report.report_type})."
        )

        self._log_audit(
            event_type=AuditEventType.SECURITY_ALERT,
            operation="MARKETPLACE_REPORT_SUBMITTED",
            success=True,
            tool_name=f"marketplace.report.{final_report.skill_id}",
            reason=f"Reporte de tipo {final_report.report_type}",
            metadata=final_report.to_dict(),
        )

        return {
            "success": True,
            "report_id": f"REP-{len(self._submitted_reports)}",
            "report": final_report.to_dict(),
        }

    def get_submitted_reports(self) -> list[SkillReport]:
        """Obtiene la lista de reportes registrados en la sesión."""
        return list(self._submitted_reports)
