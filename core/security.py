"""Módulo central del Security Manager para Jessyca Windows MCP.

Proporciona evaluación de riesgos, control de acceso basado en listas blancas y negras,
modelos de permisos jerárquicos con comodines (<dominio>.<acción>), políticas de seguridad
configurables, decisiones de consentimiento (ALLOW, DENY, ASK, ALLOW_ONCE, ALWAYS_ALLOW),
verificación UAC/Admin en Windows y registro auditable de seguridad.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from core.logger import get_logger
from utils.platform import check_windows_compatibility, is_admin

if TYPE_CHECKING:
    from core.policy_rules import PolicyManager
    from core.risk_engine import RiskEngine

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


class PermissionAction(StrEnum):
    """Acciones formales de respuesta y consentimiento de permisos."""

    ALLOW = "ALLOW"                 # Permitir ejecución inmediata
    DENY = "DENY"                   # Denegar ejecución
    ASK = "ASK"                     # Solicitar confirmación interactiva al usuario
    ALLOW_ONCE = "ALLOW_ONCE"       # Permitir temporalmente para una sola llamada (un solo uso)
    ALWAYS_ALLOW = "ALWAYS_ALLOW"   # Permitir siempre y añadir permanentemente a la lista autorizada


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
    action: PermissionAction = PermissionAction.ALLOW
    requires_user_confirmation: bool = False
    confirmation_request: Any | None = None

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
    action: PermissionAction = PermissionAction.ALLOW
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
        risk_engine: RiskEngine | None = None,
        policy_manager: PolicyManager | None = None,
    ) -> None:
        self._policy = policy or SecurityPolicy()
        self._blacklist: set[str] = set()
        self._whitelist: set[str] = set()
        self._dynamically_blocked: set[str] = set()
        self._granted_permissions: set[str] = set()
        self._one_time_grants: set[str] = set()
        self._audit_log: list[AuditRecord] = []
        self._strict_whitelist_mode: bool = strict_whitelist_mode
        self._risk_engine = risk_engine
        self._policy_manager = policy_manager

    @property
    def risk_engine(self) -> RiskEngine:
        """Obtiene o crea la instancia de RiskEngine."""
        if self._risk_engine is None:
            from core.risk_engine import RiskEngine
            self._risk_engine = RiskEngine()
        return self._risk_engine

    @property
    def policy_manager(self) -> PolicyManager | None:
        """Obtiene el gestor de políticas multi-dimensión."""
        return self._policy_manager

    def set_policy_manager(self, policy_manager: PolicyManager) -> None:
        """Establece el gestor de políticas multi-dimensión."""
        self._policy_manager = policy_manager

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

    def grant_one_time_permission(self, tool_name: str) -> None:
        """Otorga un permiso de un solo uso (ALLOW_ONCE) a una herramienta."""
        name = tool_name.strip()
        self._one_time_grants.add(name)
        logger.info(f"Permiso temporal de un solo uso (ALLOW_ONCE) otorgado a '{name}'.")

    def process_user_action(
        self,
        profile: ToolSecurityProfile,
        action: PermissionAction,
        user: str = "user",
    ) -> SecurityDecision:
        """Procesa una respuesta explícita de consentimiento o acción del usuario.

        Args:
            profile: Perfil de la herramienta.
            action: Acción seleccionada (ALLOW, DENY, ASK, ALLOW_ONCE, ALWAYS_ALLOW).
            user: Nombre del usuario o agente.

        Returns:
            SecurityDecision según la acción seleccionada.
        """
        tool_name = profile.name.strip()

        if action == PermissionAction.DENY:
            logger.warning(f"Acción DENY seleccionada para '{tool_name}'.")
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.BLOCKED_BY_BLACKLIST,
                reason=f"Ejecución de '{tool_name}' denegada por acción del usuario (DENY).",
                action=PermissionAction.DENY,
            )
        elif action == PermissionAction.ASK:
            logger.info(f"Acción ASK seleccionada para '{tool_name}'.")
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.REQUIRES_CONFIRMATION,
                reason=f"Ejecución de '{tool_name}' requiere confirmación interactiva (ASK).",
                action=PermissionAction.ASK,
                requires_user_confirmation=True,
            )
        elif action == PermissionAction.ALLOW_ONCE:
            self.grant_one_time_permission(tool_name)
            decision = SecurityDecision(
                is_allowed=True,
                status=SecurityStatus.ALLOWED,
                reason=f"Ejecución de '{tool_name}' autorizada por esta única ocasión (ALLOW_ONCE).",
                action=PermissionAction.ALLOW_ONCE,
            )
        elif action == PermissionAction.ALWAYS_ALLOW:
            self.add_to_whitelist(tool_name)
            for perm in profile.required_permissions:
                self.grant_permission(perm)
            decision = SecurityDecision(
                is_allowed=True,
                status=SecurityStatus.ALLOWED,
                reason=f"Ejecución de '{tool_name}' autorizada permanentemente (ALWAYS_ALLOW).",
                action=PermissionAction.ALWAYS_ALLOW,
            )
        else:  # PermissionAction.ALLOW
            decision = SecurityDecision(
                is_allowed=True,
                status=SecurityStatus.ALLOWED,
                reason=f"Ejecución de '{tool_name}' autorizada (ALLOW).",
                action=PermissionAction.ALLOW,
            )

        self._log_audit(profile, decision, user=user)
        return decision

    def evaluate(
        self,
        profile: ToolSecurityProfile,
        user: str = "system",
        arguments: dict[str, Any] | None = None,
        action: str = "execute",
    ) -> SecurityDecision:
        """Evalúa si una herramienta puede ejecutarse según las políticas, permisos y RiskEngine."""
        tool_name = profile.name.strip()
        category = profile.category.strip().lower()
        args = arguments or {}

        # 0. Comprobar Permiso Temporal de Un Solo Uso (ALLOW_ONCE)
        if tool_name in self._one_time_grants:
            self._one_time_grants.remove(tool_name)
            decision = SecurityDecision(
                is_allowed=True,
                status=SecurityStatus.ALLOWED,
                reason=f"Ejecución permitida para '{tool_name}' por permiso temporal consumido (ALLOW_ONCE).",
                action=PermissionAction.ALLOW_ONCE,
            )
            self._log_audit(profile, decision, user)
            return decision

        # 0.1 Comprobar Reglas del PolicyManager (Multi-Dimensión: usuario, herramienta, categoría, riesgo, acción, ruta)
        if self._policy_manager is not None:
            rule_effect = self._policy_manager.evaluate_rules(profile, user, action, args)
            if rule_effect is not None:
                if rule_effect == PermissionAction.DENY:
                    decision = SecurityDecision(
                        is_allowed=False,
                        status=SecurityStatus.BLOCKED_BY_DOMAIN_POLICY,
                        reason=f"Ejecución de '{tool_name}' denegada por regla de política multi-dimensión.",
                        action=PermissionAction.DENY,
                    )
                    self._log_audit(profile, decision, user)
                    return decision
                elif rule_effect == PermissionAction.ASK:
                    decision = SecurityDecision(
                        is_allowed=False,
                        status=SecurityStatus.REQUIRES_CONFIRMATION,
                        reason=f"Ejecución de '{tool_name}' exige confirmación por regla de política multi-dimensión.",
                        action=PermissionAction.ASK,
                        requires_user_confirmation=True,
                    )
                    self._log_audit(profile, decision, user)
                    return decision
                elif rule_effect in (PermissionAction.ALLOW, PermissionAction.ALLOW_ONCE, PermissionAction.ALWAYS_ALLOW):
                    return self.process_user_action(profile, rule_effect, user=user)

        # 1. Comprobar Lista Negra
        if tool_name in self._blacklist:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.BLOCKED_BY_BLACKLIST,
                reason=f"Herramienta '{tool_name}' está explícitamente en la Lista Negra.",
                action=PermissionAction.DENY,
            )
            self._log_audit(profile, decision, user)
            return decision

        # 2. Comprobar Bloqueo Dinámico
        if tool_name in self._dynamically_blocked:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.BLOCKED_DYNAMICALLY,
                reason=f"Herramienta '{tool_name}' ha sido bloqueada dinámicamente.",
                action=PermissionAction.DENY,
            )
            self._log_audit(profile, decision, user)
            return decision

        # 3. Comprobar Modo Estricto de Lista Blanca
        if self._strict_whitelist_mode and tool_name not in self._whitelist:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.BLOCKED_NOT_IN_WHITELIST,
                reason=f"Herramienta '{tool_name}' no está en la Lista Blanca (Modo Estricto Activo).",
                action=PermissionAction.DENY,
            )
            self._log_audit(profile, decision, user)
            return decision

        # 4. Comprobar Políticas de Dominios Excluidos/Permitidos
        if category in self._policy.blocked_domains:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.BLOCKED_BY_DOMAIN_POLICY,
                reason=f"El dominio/categoría '{category}' está bloqueado por la política de seguridad.",
                action=PermissionAction.DENY,
            )
            self._log_audit(profile, decision, user)
            return decision

        if self._policy.allowed_domains and category not in self._policy.allowed_domains:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.BLOCKED_BY_DOMAIN_POLICY,
                reason=f"El dominio/categoría '{category}' no está en los dominios permitidos por la política.",
                action=PermissionAction.DENY,
            )
            self._log_audit(profile, decision, user)
            return decision

        # 5. Evaluación Dinámica con RiskEngine
        risk_assessment = self.risk_engine.evaluate_risk(profile, args)
        computed_risk = risk_assessment.risk_level

        # 6. Comprobar Nivel de Riesgo Máximo Permitido por Política
        tool_risk_score = RISK_HIERARCHY.get(computed_risk, 2)
        max_risk_score = RISK_HIERARCHY.get(self._policy.max_allowed_risk, 5)

        if tool_risk_score > max_risk_score:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.BLOCKED_BY_POLICY_MAX_RISK,
                reason=f"El riesgo calculado '{computed_risk.value}' excede el máximo permitido por la política ('{self._policy.max_allowed_risk.value}'). {risk_assessment.justification}",
                action=PermissionAction.DENY,
            )
            self._log_audit(profile, decision, user)
            return decision

        # 7. Comprobar Requerimiento de Administrador UAC para Riesgo CRITICAL
        if (
            computed_risk == RiskLevel.CRITICAL
            and self._policy.require_admin_for_critical
        ):
            compat = check_windows_compatibility()
            if compat.is_windows and not is_admin():
                decision = SecurityDecision(
                    is_allowed=False,
                    status=SecurityStatus.DENIED_REQUIRES_ADMIN,
                    reason=f"Herramienta crítica '{tool_name}' requiere privilegios de Administrador (UAC) en Windows.",
                    action=PermissionAction.DENY,
                )
                self._log_audit(profile, decision, user)
                return decision

        # 8. Comprobar Permisos Requeridos (Jerárquicos y Comodines)
        missing_perms = [
            p for p in profile.required_permissions
            if not check_hierarchical_permission(self._granted_permissions, p)
        ]
        if missing_perms:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.DENIED_MISSING_PERMISSIONS,
                reason=f"Faltan permisos requeridos: {missing_perms}",
                action=PermissionAction.DENY,
            )
            self._log_audit(profile, decision, user)
            return decision

        # 9. Comprobar Solicitud de Confirmación del Usuario por Nivel de Riesgo
        requires_conf = risk_assessment.requires_confirmation

        if requires_conf:
            decision = SecurityDecision(
                is_allowed=False,
                status=SecurityStatus.REQUIRES_CONFIRMATION,
                reason=f"Herramienta '{tool_name}' [Riesgo Calculado: {computed_risk.value}] requiere confirmación.",
                action=PermissionAction.ASK,
                requires_user_confirmation=True,
            )
            self._log_audit(profile, decision, user)
            return decision

        # 10. Autorizado con Éxito
        decision = SecurityDecision(
            is_allowed=True,
            status=SecurityStatus.ALLOWED,
            reason=f"Ejecución permitida para '{tool_name}' [Riesgo: {computed_risk.value}].",
            action=PermissionAction.ALLOW,
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
        action = PermissionAction.ALLOW if approved else PermissionAction.DENY
        return self.process_user_action(profile, action, user="user")

    def _log_audit(self, profile: ToolSecurityProfile, decision: SecurityDecision, user: str) -> None:
        """Registra un evento de evaluación en el historial inmutable de auditoría."""
        record = AuditRecord(
            tool_name=profile.name,
            status=decision.status,
            risk_level=profile.risk_level,
            allowed=decision.is_allowed,
            user=user,
            reason=decision.reason,
            action=decision.action,
        )
        self._audit_log.append(record)

        # Registrar también en el AuditLogger global estructurado
        from core.audit_logger import get_audit_logger
        res_str = "SUCCESS" if decision.is_allowed else decision.status.value
        get_audit_logger().log_event(
            usuario=user,
            accion="evaluate",
            herramienta=profile.name,
            riesgo=profile.risk_level,
            resultado=res_str,
            duracion_ms=0.0,
            autorizacion=decision.action,
            details={"reason": decision.reason},
        )
        logger.debug(f"Auditoría registrada [{decision.status.value} / {decision.action.value}] Tool: {profile.name} User: {user}")

    def get_audit_log(self) -> list[AuditRecord]:
        """Obtiene una copia inmutable del historial de auditoría de seguridad."""
        return list(self._audit_log)
