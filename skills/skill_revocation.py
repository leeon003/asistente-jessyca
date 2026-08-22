"""Subsistema de Revocación de Skills y Firmantes (skill_revocation.py - Fase 34).

Permite revocar de manera inmediata y gobernada:
1. Una versión específica de una Skill (skill_id@version).
2. Todas las versiones de una Skill (skill_id).
3. Un firmante criptográfico (signer_id).

INVARIANTES DE SEGURIDAD:
- Una Skill revocada se deshabilita de inmediato en el catálogo local y se bloquea su ejecución.
- Ninguna Skill revocada puede ser instalada ni reactivada.
- Las revocaciones generan eventos formales en el AuditLogger.
- No se eliminan datos de usuario automáticamente sin una política explícita.
"""

from __future__ import annotations

import datetime
from typing import Any

from core.audit_logger import AuditEventType, AuditLogger, get_audit_logger
from core.logger import get_logger
from skills.skill_registry import SkillRegistry, get_skill_registry

logger = get_logger("jessyca.skills.revocation")


class SkillRevocationRegistry:
    """Registro central de revocaciones de Skills y Firmantes de JESSYCA."""

    _instance: SkillRevocationRegistry | None = None

    def __init__(
        self,
        audit_logger: AuditLogger | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self.audit_logger = audit_logger or get_audit_logger()
        self.skill_registry = skill_registry or get_skill_registry()

        # _revoked_skills: { "skill_id" o "skill_id@version": {"reason": str, "timestamp": str, "severity": str} }
        self._revoked_skills: dict[str, dict[str, Any]] = {}

        # _revoked_signers: { "signer_id": {"reason": str, "timestamp": str, "severity": str} }
        self._revoked_signers: dict[str, dict[str, Any]] = {}

    @classmethod
    def get_instance(cls) -> SkillRevocationRegistry:
        """Obtiene la instancia global del registro de revocaciones."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reinicia la instancia global para pruebas."""
        cls._instance = None

    def revoke_skill(
        self,
        skill_id: str,
        version: str | None = None,
        reason: str = "Vulnerabilidad de seguridad o revocación formal",
        severity: str = "CRITICAL",
    ) -> None:
        """Revoca formalmente una Skill o una versión específica de la misma."""
        revocation_key = f"{skill_id}@{version}" if version else skill_id
        timestamp = datetime.datetime.now(datetime.UTC).isoformat()

        self._revoked_skills[revocation_key] = {
            "skill_id": skill_id,
            "version": version,
            "reason": reason,
            "severity": severity,
            "timestamp": timestamp,
        }

        logger.warning(
            f"[SKILL REVOKED] Revocada formalmente '{revocation_key}' (Severidad: {severity}, Motivo: {reason})."
        )

        # Deshabilitar inmediatamente en el SkillRegistry local
        if self.skill_registry:
            if version:
                target = f"{skill_id}@{version}"
                self.skill_registry.disable_skill(target)
                logger.info(f"[SKILL REVOCATION APPLIED] '{target}' deshabilitada en SkillRegistry.")
            else:
                self.skill_registry.disable_skill(skill_id)
                # Deshabilitar todas las versiones registradas si existen
                if hasattr(self.skill_registry, "get_version_history"):
                    for v in self.skill_registry.get_version_history(skill_id):
                        self.skill_registry.disable_skill(f"{skill_id}@{v}")
                logger.info(f"[SKILL REVOCATION APPLIED] Todas las versiones de '{skill_id}' deshabilitadas en SkillRegistry.")

        # Registrar en AuditLogger
        try:
            from core.audit_logger import AuditEvent
            from core.security_architecture import SecurityLevel
            ev = AuditEvent(
                event_type=AuditEventType.SECURITY_ALERT,
                user="system",
                tool_name=f"revocation.{revocation_key}",
                operation="SKILL_REVOKED",
                security_level=SecurityLevel.CRITICAL if severity == "CRITICAL" else SecurityLevel.HIGH,
                success=True,
                reason=reason,
                metadata={
                    "skill_id": skill_id,
                    "version": version,
                    "severity": severity,
                    "timestamp": timestamp,
                },
            )
            self.audit_logger.log_audit_event(ev)
        except Exception as e:
            logger.error(f"[AUDIT LOG ERROR] Error registrando revocación de skill: {e}")

    def revoke_signer(
        self,
        signer_id: str,
        reason: str = "Clave comprometida o firmante revocado formalmente",
        severity: str = "CRITICAL",
    ) -> None:
        """Revoca formalmente a un firmante criptográfico."""
        timestamp = datetime.datetime.now(datetime.UTC).isoformat()

        self._revoked_signers[signer_id] = {
            "signer_id": signer_id,
            "reason": reason,
            "severity": severity,
            "timestamp": timestamp,
        }

        logger.warning(
            f"[SIGNER REVOKED] Firmante '{signer_id}' revocado formalmente (Severidad: {severity}, Motivo: {reason})."
        )

        # Registrar en AuditLogger
        try:
            from core.audit_logger import AuditEvent
            from core.security_architecture import SecurityLevel
            ev = AuditEvent(
                event_type=AuditEventType.SECURITY_ALERT,
                user="system",
                tool_name=f"revocation.signer.{signer_id}",
                operation="SIGNER_REVOKED",
                security_level=SecurityLevel.CRITICAL if severity == "CRITICAL" else SecurityLevel.HIGH,
                success=True,
                reason=reason,
                metadata={
                    "signer_id": signer_id,
                    "severity": severity,
                    "timestamp": timestamp,
                },
            )
            self.audit_logger.log_audit_event(ev)
        except Exception as e:
            logger.error(f"[AUDIT LOG ERROR] Error registrando revocación de firmante: {e}")

    def is_skill_revoked(self, skill_id: str, version: str | None = None) -> tuple[bool, str]:
        """Comprueba si una Skill o su versión están revocadas.

        :return: Tupla (is_revoked, reason).
        """
        # 1. Comprobar si toda la skill está revocada
        if skill_id in self._revoked_skills:
            return True, self._revoked_skills[skill_id]["reason"]

        # 2. Comprobar si la versión específica está revocada
        if version:
            specific_key = f"{skill_id}@{version}"
            if specific_key in self._revoked_skills:
                return True, self._revoked_skills[specific_key]["reason"]

        return False, ""

    def is_signer_revoked(self, signer_id: str | None) -> tuple[bool, str]:
        """Comprueba si un firmante criptográfico ha sido revocado.

        :return: Tupla (is_revoked, reason).
        """
        if not signer_id:
            return False, ""

        if signer_id in self._revoked_signers:
            return True, self._revoked_signers[signer_id]["reason"]

        return False, ""

    def get_revocation_list(self) -> dict[str, Any]:
        """Retorna una copia estructurada de la lista de revocaciones activas."""
        return {
            "revoked_skills": dict(self._revoked_skills),
            "revoked_signers": dict(self._revoked_signers),
        }

    def clear(self) -> None:
        """Limpia el registro de revocaciones (utilizado principalmente para tests)."""
        self._revoked_skills.clear()
        self._revoked_signers.clear()
