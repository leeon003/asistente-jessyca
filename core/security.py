"""Módulo central del Security Manager para Jessyca Windows MCP.

Proporciona evaluación de riesgos, control de acceso basado en listas blancas y negras,
modelos de permisos jerárquicos con comodines (<dominio>.<acción>), políticas de seguridad
configurables, verificación UAC/Admin en Windows y registro auditable de seguridad.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.logger import get_logger
from utils.platform import check_windows_compatibility, is_admin

logger = get_logger("jessyca.security")


class RiskLevel(StrEnum):
    """Niveles de riesgo para las herramientas MCP."""

    READ_ONLY = "READ_ONLY"   # Solo lectura, sin efectos secundarios
    SAFE = "SAFE"             # Operaciones seguras con efectos secundarios mínimos o reversibles
    WARNING = "WARNING"       # Modificaciones no críticas que requieren precaución
    DANGEROUS = "DANGEROUS"   # Cambios significativos en sistema, archivos o procesos
    CRITICAL = "CRITICAL"     # Operaciones de alto riesgo (permisos UAC/Admin, borrado masivo)


RISK_HIERARCHY: dict[RiskLevel, int] = {
    RiskLevel.READ_ONLY: 1,
    RiskLevel.SAFE: 2,
    RiskLevel.WARNING: 3,
    RiskLevel.DANGEROUS: 4,
    RiskLevel.CRITICAL: 5,
}


class SecurityStatus(StrEnum):
    """Estados del resultado de una evaluación de seguridad."""

    ALLOWED = "ALLOWED"
    BLOCKED_BY_BLACKLIST = "BLOCKED_BY_BLACKLIST"
    BLOCKED_NOT_IN_WHITELIST = "BLOCKED_NOT_IN_WHITELIST"
    BLOCKED_DYNAMICALLY = "BLOCKED_DYNAMICALLY"
    BLOCKED_BY_POLICY_MAX_RISK = "BLOCKED_BY_POLICY_MAX_RISK"
    BLOCKED_BY_DOMAIN_POLICY = "BLOCKED_BY_DOMAIN_POLICY"
    DENIED_MISSING_PERMISSIONS = "DENIED_MISSING_PERMISSIONS"
    DENIED_REQUIRES_ADMIN = "DENIED_REQUIRES_ADMIN"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"


@dataclass
class ToolSecurityProfile:
    """Perfil de seguridad declarado por cada herramienta MCP."""

    name: str
    category: str
    risk_level: RiskLevel = RiskLevel.SAFE
    required_permissions: list[str] = field(default_factory=list)
    requires_confirmation: bool = False


@dataclass
class SecurityPolicy:
    """Política de seguridad configurable para el control de autorización global."""

    max_allowed_risk: RiskLevel = RiskLevel.CRITICAL
    require_admin_for_critical: bool = True
    allowed_domains: set[str] = field(default_factory=set)
    blocked_domains: set[str] = field(default_factory=set)


@dataclass
class SecurityDecision:
    """Resultado de la evaluación de seguridad de una herramienta."""

    is_allowed: bool
    status: SecurityStatus
    reason: str
    requires_user_confirmation: bool = False

    def __bool__(self) -> bool:
        return self.is_allowed


@dataclass
class AuditRecord:
    """Registro inmutable de auditoría para cada evaluación e intento de ejecución."""

    tool_name: str
    status: SecurityStatus
    risk_level: RiskLevel
    allowed: bool
    user: str
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = field(default_factory=dict)


def check_hierarchical_permission(granted_permissions: set[str], required_permission: str) -> bool:
    """Verifica si un permiso requerido (ej. 'filesystem.read') está autorizado por permisos otorgados.

    Soporta comodines como '*' (global) y 'filesystem.*' (dominio).
    """
    req = required_permission.strip().lower()
    if "*" in granted_permissions or req in granted_permissions:
        return True

    if "." in req:
        domain = req.split(".")[0]
        domain_wildcard = f"{domain}.*"
        if domain_wildcard in granted_permissions:
            return True

    return False


class SecurityManager:
    """Gestor de seguridad independiente y desacoplado para el control de autorización de herramientas MCP."""

    def __init__(
        self,
        policy: SecurityPolicy | None = None,
        strict_whitelist_mode: bool = False,
    ) -> None:
        self._policy = policy or SecurityPolicy()
        self._blacklist: set[str] = set()
        self._whitelist: set[str] = set()
        self._dynamically_blocked: set[str] = set()
        self._granted_permissions: set[str] = set()
        self._audit_log: list[AuditRecord] = []
        self._strict_whitelist_mode: bool = strict_whitelist_mode

    def set_policy(self, policy: SecurityPolicy) -> None:
        """Establece o actualiza la política global de seguridad."""
        self._policy = policy
        logger.info(f"Nueva política de seguridad establecida [Max Risk: {policy.max_allowed_risk.value}].")

    def add_to_blacklist(self, tool_name: str) -> None:
        """Añade una herramienta a la lista negra (bloqueo permanente)."""
        name = tool_name.strip()
        self._blacklist.add(name)
        logger.warning(f"Herramienta '{name}' añadida a la Lista Negra de seguridad.")

    def remove_from_blacklist(self, tool_name: str) -> None:
        """Remueve una herramienta de la lista negra."""
        name = tool_name.strip()
        self._blacklist.discard(name)
        logger.info(f"Herramienta '{name}' removida de la Lista Negra.")

    def add_to_whitelist(self, tool_name: str) -> None:
        """Añade una herramienta a la lista blanca autorizada."""
        name = tool_name.strip()
        self._whitelist.add(name)
        logger.info(f"Herramienta '{name}' añadida a la Lista Blanca de seguridad.")

    def set_strict_whitelist_mode(self, enabled: bool) -> None:
        """Habilita o deshabilita el modo estricto de lista blanca (solo ejecuta lo listado)."""
        self._strict_whitelist_mode = enabled
        status_str = "activado" if enabled else "desactivado"
        logger.info(f"Modo estricto de Lista Blanca {status_str}.")

    def block_tool(self, tool_name: str) -> None:
        """Bloquea dinámicamente una herramienta en tiempo de ejecución."""
        name = tool_name.strip()
        self._dynamically_blocked.add(name)
        logger.warning(f"Herramienta '{name}' bloqueada dinámicamente.")

    def unblock_tool(self, tool_name: str) -> None:
        """Desbloquea una herramienta previamente bloqueada dinámicamente."""
        name = tool_name.strip()
        self._dynamically_blocked.discard(name)
        logger.info(f"Herramienta '{name}' desbloqueada dinámicamente.")

    def grant_permission(self, permission: str) -> None:
        """Otorga un permiso al entorno actual (soporta 'filesystem.read', 'filesystem.*', '*')."""
        perm = permission.strip().lower()
        self._granted_permissions.add(perm)
        logger.info(f"Permiso '{perm}' otorgado al sistema.")

    def revoke_permission(self, permission: str) -> None:
        """Revoca un permiso previamente otorgado."""
        perm = permission.strip().lower()
        self._granted_permissions.discard(perm)
        logger.info(f"Permiso '{perm}' revocado del sistema.")

    def evaluate(self, profile: ToolSecurityProfile, user: str = "system") -> SecurityDecision:
        """Evalúa si una herramienta puede ejecutarse según las políticas y permisos activos.

        Args:
            profile: Perfil de seguridad declarado por la herramienta.
            user: Nombre del usuario o agente invocador.

        Returns:
            SecurityDecision con el resultado y justificación.
        """
        tool_name = profile.name.strip()
        category = profile.category.strip().lower()

        # 1. Comprobar Lista Negra
        if tool_name in self._blacklist:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.BLOCKED_BY_BLACKLIST,
                reason=f"Herramienta '{tool_name}' está explícitamente en la Lista Negra.",
            )
            self._log_audit(profile, decision, user)
            return decision

        # 2. Comprobar Bloqueo Dinámico
        if tool_name in self._dynamically_blocked:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.BLOCKED_DYNAMICALLY,
                reason=f"Herramienta '{tool_name}' ha sido bloqueada dinámicamente.",
            )
            self._log_audit(profile, decision, user)
            return decision

        # 3. Comprobar Modo Estricto de Lista Blanca
        if self._strict_whitelist_mode and tool_name not in self._whitelist:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.BLOCKED_NOT_IN_WHITELIST,
                reason=f"Herramienta '{tool_name}' no está en la Lista Blanca (Modo Estricto Activo).",
            )
            self._log_audit(profile, decision, user)
            return decision

        # 4. Comprobar Políticas de Dominios Excluidos/Permitidos
        if category in self._policy.blocked_domains:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.BLOCKED_BY_DOMAIN_POLICY,
                reason=f"El dominio/categoría '{category}' está bloqueado por la política de seguridad.",
            )
            self._log_audit(profile, decision, user)
            return decision

        if self._policy.allowed_domains and category not in self._policy.allowed_domains:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.BLOCKED_BY_DOMAIN_POLICY,
                reason=f"El dominio/categoría '{category}' no está en los dominios permitidos por la política.",
            )
            self._log_audit(profile, decision, user)
            return decision

        # 5. Comprobar Nivel de Riesgo Máximo Permitido por Política
        tool_risk_score = RISK_HIERARCHY.get(profile.risk_level, 2)
        max_risk_score = RISK_HIERARCHY.get(self._policy.max_allowed_risk, 5)

        if tool_risk_score > max_risk_score:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.BLOCKED_BY_POLICY_MAX_RISK,
                reason=f"El riesgo '{profile.risk_level.value}' excede el máximo permitido por la política ('{self._policy.max_allowed_risk.value}').",
            )
            self._log_audit(profile, decision, user)
            return decision

        # 6. Comprobar Requerimiento de Administrador UAC para Riesgo CRITICAL
        if (
            profile.risk_level == RiskLevel.CRITICAL
            and self._policy.require_admin_for_critical
        ):
            compat = check_windows_compatibility()
            if compat.is_windows and not is_admin():
                decision = SecurityDecision(
                    is_allowed=False,
                    status=SecurityStatus.DENIED_REQUIRES_ADMIN,
                    reason=f"Herramienta crítica '{tool_name}' requiere privilegios de Administrador (UAC) en Windows.",
                )
                self._log_audit(profile, decision, user)
                return decision

        # 7. Comprobar Permisos Requeridos (Jerárquicos y Comodines)
        missing_perms = [
            p for p in profile.required_permissions
            if not check_hierarchical_permission(self._granted_permissions, p)
        ]
        if missing_perms:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.DENIED_MISSING_PERMISSIONS,
                reason=f"Faltan permisos requeridos: {missing_perms}",
            )
            self._log_audit(profile, decision, user)
            return decision

        # 8. Comprobar Solicitud de Confirmación del Usuario por Nivel de Riesgo
        requires_conf = profile.requires_confirmation or profile.risk_level in (
            RiskLevel.DANGEROUS,
            RiskLevel.CRITICAL,
        )

        if requires_conf:
            decision = SecurityDecision(
                is_allowed=False,  # Requiere confirmación previa del usuario
                status=SecurityStatus.REQUIRES_CONFIRMATION,
                reason=f"Herramienta '{tool_name}' [Riesgo: {profile.risk_level.value}] requiere confirmación.",
                requires_user_confirmation=True,
            )
            self._log_audit(profile, decision, user)
            return decision

        # 9. Autorizado con Éxito
        decision = SecurityDecision(
            is_allowed=True,
            status=SecurityStatus.ALLOWED,
            reason=f"Ejecución permitida para '{tool_name}'.",
        )
        self._log_audit(profile, decision, user)
        return decision

    def confirm_execution(
        self,
        profile: ToolSecurityProfile,
        user_confirmed: bool = True,
        user_approved: bool | None = None,
    ) -> SecurityDecision:
        """Procesa la respuesta de confirmación del usuario para herramientas de alto riesgo."""
        approved = user_approved if user_approved is not None else user_confirmed
        if not approved:
            logger.warning(f"Ejecución de '{profile.name}' CANCELADA por el usuario.")
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.REQUIRES_CONFIRMATION,
                reason=f"Ejecución de '{profile.name}' rechazada por el usuario.",
            )
        else:
            logger.info(f"Ejecución de '{profile.name}' CONFIRMADA explícitamente por el usuario.")
            decision = SecurityDecision(
                is_allowed=True,
                status=SecurityStatus.ALLOWED,
                reason=f"Ejecución de '{profile.name}' autorizada por confirmación del usuario.",
            )

        self._log_audit(profile, decision, user="user")
        return decision

    def _log_audit(self, profile: ToolSecurityProfile, decision: SecurityDecision, user: str) -> None:
        """Registra un evento de evaluación en el historial inmutable de auditoría."""
        record = AuditRecord(
            tool_name=profile.name,
            status=decision.status,
            risk_level=profile.risk_level,
            allowed=decision.is_allowed,
            user=user,
            reason=decision.reason,
        )
        self._audit_log.append(record)
        logger.debug(f"Auditoría registrada [{decision.status.value}] Tool: {profile.name} User: {user}")

    def get_audit_log(self) -> list[AuditRecord]:
        """Obtiene una copia inmutable del historial de auditoría de seguridad."""
        return list(self._audit_log)
