"""Security Policy Engine para Jessyca Windows MCP (Subetapa 04.5).

Capa declarativa de políticas de seguridad independientes del LLM, voz, TTS/STT,
UI o APIs de Windows. Define qué operaciones son permitidas, denegadas o requieren
confirmación/elevación con reglas deterministas, prioridades y protección DENY OVERRIDE.
"""

from __future__ import annotations

import fnmatch
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.logger import get_logger
from core.risk_engine import (
    SECURITY_RISK_HIERARCHY,
    RiskAssessment,
    normalize_to_security_level,
)
from core.security_architecture import (
    SecurityContext,
    SecurityDecisionType,
    SecurityLevel,
    ToolSecurityMetadata,
)
from core.types import JSONDict

logger = get_logger("jessyca.security.policy")


class PolicySource(StrEnum):
    """Origen legítimo de la política de seguridad.

    CRITICAL SECURITY PRINCIPLE:
    No incluye fuentes dinámicas como LLM, USER_PROMPT o ASSISTANT.
    El LLM no posee autoridad para definir o modificar políticas.
    """

    DEFAULT = "DEFAULT"
    SYSTEM = "SYSTEM"
    ADMINISTRATOR = "ADMINISTRATOR"
    CONFIGURATION = "CONFIGURATION"


class InvalidPolicyError(ValueError):
    """Excepción lanzada cuando una política no cumple con los criterios de validación de estructura o seguridad."""

    pass


@dataclass(frozen=True)
class PolicyRuleCondition:
    """Condiciones adicionales de coincidencia declarativas para una regla de política."""

    path_patterns: list[str] = field(default_factory=list)
    users: list[str] = field(default_factory=lambda: ["*"])
    environments: list[str] = field(default_factory=lambda: ["*"])
    parameters: JSONDict = field(default_factory=dict)


@dataclass
class PolicyRule:
    """Regla declarativa individual de política de seguridad."""

    name: str
    decision: SecurityDecisionType
    rule_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    enabled: bool = True
    priority: int = 100  # Mayor número representa mayor prioridad determinista
    tool_name: str = "*"
    operation: str = "*"
    risk_level: SecurityLevel | None = None
    requires_confirmation: bool | None = None
    requires_elevation: bool | None = None
    conditions: PolicyRuleCondition = field(default_factory=PolicyRuleCondition)

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise InvalidPolicyError("El nombre de la regla 'name' no puede estar vacío.")
        if self.priority < 0:
            raise InvalidPolicyError(f"La prioridad de la regla '{self.name}' debe ser no negativa.")


@dataclass
class SecurityPolicy:
    """Contenedor principal e inmutable de una política de seguridad declarativa."""

    policy_id: str = "default-system-policy"
    name: str = "Jessyca Default Security Policy"
    description: str = "Política predeterminada conservadora de seguridad con estrategia Fail-Safe"
    version: str = "1.0.0"
    source: PolicySource = PolicySource.SYSTEM
    max_allowed_risk: SecurityLevel = SecurityLevel.DANGEROUS
    rules: list[PolicyRule] = field(default_factory=list)
    default_decision: SecurityDecisionType = SecurityDecisionType.DENY
    is_immutable: bool = True

    def __post_init__(self) -> None:
        if not self.policy_id or not self.policy_id.strip():
            raise InvalidPolicyError("El campo 'policy_id' no puede estar vacío.")
        if not self.version or not self.version.strip():
            raise InvalidPolicyError("El campo 'version' no puede estar vacío.")
        # Ordenar reglas deterministamente por prioridad descendente
        object.__setattr__(self, "rules", sorted(self.rules, key=lambda r: r.priority, reverse=True))
        object.__setattr__(self, "_initialized", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_initialized", False) and getattr(self, "is_immutable", False):
            raise InvalidPolicyError(f"SecurityPolicy '{self.policy_id}' es inmutable y no permite modificación.")
        super().__setattr__(name, value)


@dataclass
class PolicyDecision:
    """Resultado formal estructurado de la evaluación de una Security Policy."""

    decision_type: SecurityDecisionType
    is_allowed: bool
    reason: str = ""
    matched_rule_id: str | None = None
    matched_rule_name: str | None = None
    priority: int = 0
    policy_id: str = ""
    policy_version: str = "1.0.0"
    policy_source: PolicySource = PolicySource.SYSTEM
    requires_user_confirmation: bool = False
    requires_elevation: bool = False
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __bool__(self) -> bool:
        return self.is_allowed


class PolicyRuleBase:
    """Abstracción base extensible para la evaluación de coincidencias de reglas (IPolicyRule)."""

    def __init__(self, rule: PolicyRule) -> None:
        self.rule = rule

    @property
    def priority(self) -> int:
        return self.rule.priority

    def matches(
        self,
        context: SecurityContext,
        metadata: ToolSecurityMetadata,
        risk_assessment: RiskAssessment,
    ) -> bool:
        """Verifica si la regla coincide con la solicitud actual."""
        if not self.rule.enabled:
            return False

        # 1. Herramienta (tool_name)
        t_clean = metadata.tool_name.strip().lower()
        r_tool = self.rule.tool_name.strip().lower()
        if r_tool != "*" and not fnmatch.fnmatch(t_clean, r_tool):
            return False

        # 2. Operación (operation)
        param_op = str(context.parameters.get("operation", "")).strip().lower()
        risk_op = (risk_assessment.operation or "").strip().lower()
        actual_op = param_op or risk_op or "execute"
        r_op = self.rule.operation.strip().lower()
        if r_op != "*" and not fnmatch.fnmatch(actual_op, r_op):
            return False

        # 3. Riesgo (risk_level)
        if self.rule.risk_level is not None:
            eval_risk = normalize_to_security_level(risk_assessment.risk_level)
            rule_risk = self.rule.risk_level
            eval_score = SECURITY_RISK_HIERARCHY.get(eval_risk.value, 2)
            rule_score = SECURITY_RISK_HIERARCHY.get(rule_risk.value, 2)
            if eval_score < rule_score:
                return False

        # 3.5 Elevación de privilegios (requires_elevation)
        if self.rule.requires_elevation is not None and self.rule.requires_elevation != metadata.requires_elevation:
            return False

        # 4. Condición de usuario (users)
        cond = self.rule.conditions
        if cond.users and "*" not in cond.users:
            u_clean = context.user.strip().lower()
            if not any(fnmatch.fnmatch(u_clean, u.strip().lower()) for u in cond.users):
                return False

        # 5. Condición de entorno (environments)
        if cond.environments and "*" not in cond.environments:
            e_clean = context.environment.strip().lower()
            if not any(fnmatch.fnmatch(e_clean, env.strip().lower()) for env in cond.environments):
                return False

        # 6. Patrones de ruta (path_patterns)
        if cond.path_patterns:
            args_repr = str(context.parameters).lower().replace("\\\\", "\\").replace("/", "\\")
            matched_path = False
            for pat in cond.path_patterns:
                pat_norm = pat.lower().replace("/", "\\")
                if pat_norm in args_repr or fnmatch.fnmatch(args_repr, f"*{pat_norm}*"):
                    matched_path = True
                    break
            if not matched_path:
                return False

        return True


class ToolPolicyRule(PolicyRuleBase):
    """Regla especializada en filtrado por nombre de herramienta."""

    pass


class OperationPolicyRule(PolicyRuleBase):
    """Regla especializada en filtrado por tipo de operación."""

    pass


class RiskPolicyRule(PolicyRuleBase):
    """Regla especializada en nivel de riesgo de la operación."""

    pass


class PathPolicyRule(PolicyRuleBase):
    """Regla especializada en restricciones de rutas y recursos."""

    pass


class PrivilegePolicyRule(PolicyRuleBase):
    """Regla especializada en elevación de privilegios UAC."""

    pass


class GenericPolicyRule(PolicyRuleBase):
    """Regla genérica multi-dimensión."""

    pass


def validate_security_policy(policy: SecurityPolicy) -> bool:
    """Valida la integridad estructural, consistencia y seguridad de una Security Policy.

    Lanza InvalidPolicyError si se detecta cualquier falla de consistencia.
    """
    if not isinstance(policy, SecurityPolicy):
        raise InvalidPolicyError("La política especificada no es una instancia válida de SecurityPolicy.")
    if not policy.policy_id or not policy.policy_id.strip():
        raise InvalidPolicyError("La Security Policy debe poseer un 'policy_id' válido.")
    if not policy.version or not policy.version.strip():
        raise InvalidPolicyError("La Security Policy debe poseer una versión válida.")

    seen_ids: set[str] = set()
    for rule in policy.rules:
        if not isinstance(rule, PolicyRule):
            raise InvalidPolicyError(f"Elemento inválido en lista de reglas de política: {type(rule)}")
        if rule.rule_id in seen_ids:
            raise InvalidPolicyError(f"Se detectó un 'rule_id' duplicado en la política: '{rule.rule_id}'")
        seen_ids.add(rule.rule_id)
        if not rule.name or not rule.name.strip():
            raise InvalidPolicyError("Todas las reglas de la política deben poseer un 'name' no vacío.")
        if rule.priority < 0:
            raise InvalidPolicyError(f"Regla '{rule.name}' posee una prioridad negativa inválida: {rule.priority}")

    return True


def create_default_security_policy() -> SecurityPolicy:
    """Crea la política de seguridad predeterminada conservadora del sistema.

    Reglas predeterminadas conservadoras:
    - SAFE      -> ALLOW
    - WARNING   -> REQUIRE_CONFIRMATION
    - DANGEROUS -> REQUIRE_CONFIRMATION
    - CRITICAL  -> DENY
    - UNKNOWN   -> DENY (Fail-Safe)
    """
    rules = [
        PolicyRule(
            rule_id="sys-rule-critical-001",
            name="Critical Operations Protection",
            description="Deniega por defecto operaciones clasificadas como CRITICAL",
            priority=1000,
            risk_level=SecurityLevel.CRITICAL,
            decision=SecurityDecisionType.DENY,
        ),
        PolicyRule(
            rule_id="sys-rule-elevation-002",
            name="Privilege Elevation Requirement",
            description="Exige autorización de elevación para operaciones con metadatos UAC",
            priority=900,
            requires_elevation=True,
            decision=SecurityDecisionType.REQUIRE_ELEVATED_AUTHORIZATION,
        ),
        PolicyRule(
            rule_id="sys-rule-dangerous-003",
            name="Dangerous Operations Confirmation",
            description="Exige confirmación interactiva para operaciones de alto riesgo DANGEROUS",
            priority=500,
            risk_level=SecurityLevel.DANGEROUS,
            decision=SecurityDecisionType.REQUIRE_CONFIRMATION,
            requires_confirmation=True,
        ),
        PolicyRule(
            rule_id="sys-rule-warning-004",
            name="Warning Operations Confirmation",
            description="Exige confirmación para operaciones WARNING en política conservadora",
            priority=100,
            risk_level=SecurityLevel.WARNING,
            decision=SecurityDecisionType.REQUIRE_CONFIRMATION,
            requires_confirmation=True,
        ),
        PolicyRule(
            rule_id="sys-rule-safe-005",
            name="Safe Operations Allow",
            description="Permite operaciones de bajo riesgo SAFE",
            priority=10,
            risk_level=SecurityLevel.SAFE,
            decision=SecurityDecisionType.ALLOW,
        ),
    ]

    return SecurityPolicy(
        policy_id="sys-default-v1",
        name="Jessyca Default System Security Policy",
        description="Política por defecto conservadora de seguridad para Jessyca Windows MCP",
        version="1.0.0",
        source=PolicySource.SYSTEM,
        max_allowed_risk=SecurityLevel.DANGEROUS,
        rules=rules,
        default_decision=SecurityDecisionType.DENY,
        is_immutable=True,
    )


class SecurityPolicyEvaluator:
    """Evaluador determinista de Security Policy para Jessyca Windows MCP (Subetapa 04.5).

    Aplica:
    1. Estrategia Fail-Safe ante políticas o solicitudes nulas/inválidas.
    2. Protección contra Sobrescritura Accidental de DENY: Si cualquier regla coincidente deniega
       la operación, prevalece DENY sin importar la prioridad de reglas ALLOW.
    3. Límite Absoluto de max_allowed_risk: Ninguna operación que exceda max_allowed_risk puede resultar ALLOW.
    4. Protección contra Escalamiento de Privilegios: Operaciones CRITICAL o que requieren elevación UAC
       jamás retornan ALLOW.
    5. Evaluación por Prioridad Descendente para reglas autorizadas.
    6. Fallback a decisión por defecto de política (Fail-Safe DENY) si ninguna regla coincide.
    """

    def __init__(self, default_policy: SecurityPolicy | None = None) -> None:
        self._default_policy = default_policy or create_default_security_policy()

    def evaluate_policy(
        self,
        context: SecurityContext | None,
        metadata: ToolSecurityMetadata | None,
        risk_assessment: RiskAssessment | None,
        policy: SecurityPolicy | None = None,
    ) -> PolicyDecision:
        """Evalúa deterministamente una solicitud contra la Security Policy activa."""
        active_policy = policy or self._default_policy

        # 1. Estrategia Fail-Safe: Validación de estructura de la política
        try:
            validate_security_policy(active_policy)
        except InvalidPolicyError as e:
            logger.error(f"Fail-Safe Activado: Política de seguridad inválida -> DENY ({e})")
            return PolicyDecision(
                decision_type=SecurityDecisionType.DENY,
                is_allowed=False,
                reason=f"Fail-Safe: La política de seguridad es inválida ({e}). Operación denegada.",
                policy_id=getattr(active_policy, "policy_id", "invalid"),
                policy_version=getattr(active_policy, "version", "unknown"),
                policy_source=getattr(active_policy, "source", PolicySource.SYSTEM),
            )

        # Fail-Safe si context, metadata o risk_assessment son nulos
        if context is None or metadata is None or risk_assessment is None:
            logger.warning("Fail-Safe Activado: Solicitud incompleta (context, metadata o risk_assessment nulo) -> DENY")
            return PolicyDecision(
                decision_type=SecurityDecisionType.DENY,
                is_allowed=False,
                reason="Fail-Safe: La solicitud carece de contexto, metadatos o análisis de riesgo válido.",
                policy_id=active_policy.policy_id,
                policy_version=active_policy.version,
                policy_source=active_policy.source,
            )

        eval_risk = normalize_to_security_level(risk_assessment.risk_level)
        eval_score = SECURITY_RISK_HIERARCHY.get(eval_risk.value, 2)
        max_allowed_score = SECURITY_RISK_HIERARCHY.get(active_policy.max_allowed_risk.value, 4)

        # 2. Recopilar TODAS las reglas que coinciden
        all_matched_rules: list[PolicyRule] = []
        for rule in active_policy.rules:
            handler = PolicyRuleBase(rule)
            if handler.matches(context, metadata, risk_assessment):
                all_matched_rules.append(rule)

        # 3. Protección contra Sobrescritura Accidental de DENY:
        # Si CUALQUIER regla coincidente deniega la operación, DENY prevalece siempre
        deny_matches = [r for r in all_matched_rules if r.decision == SecurityDecisionType.DENY]
        if deny_matches:
            deny_rule = deny_matches[0]
            logger.info(f"Protección DENY Overriding aplicada por regla [{deny_rule.name}]")
            return PolicyDecision(
                decision_type=SecurityDecisionType.DENY,
                is_allowed=False,
                reason=f"Protección contra sobrescritura: La regla DENY '{deny_rule.name}' prevalece sobre cualquier regla ALLOW.",
                matched_rule_id=deny_rule.rule_id,
                matched_rule_name=deny_rule.name,
                priority=deny_rule.priority,
                policy_id=active_policy.policy_id,
                policy_version=active_policy.version,
                policy_source=active_policy.source,
            )

        # 4. Protección de Escalamiento de Privilegios UAC:
        requires_elev = metadata.requires_elevation or any(r.requires_elevation is True for r in all_matched_rules)
        if metadata.requires_elevation or any(r.decision == SecurityDecisionType.REQUIRE_ELEVATED_AUTHORIZATION for r in all_matched_rules):
            logger.info("Operación exige elevación de privilegios UAC -> REQUIRE_ELEVATED_AUTHORIZATION")
            return PolicyDecision(
                decision_type=SecurityDecisionType.REQUIRE_ELEVATED_AUTHORIZATION,
                is_allowed=False,
                reason="Protección de elevación: La operación exige elevación autorizada de privilegios (UAC/Admin).",
                policy_id=active_policy.policy_id,
                policy_version=active_policy.version,
                policy_source=active_policy.source,
                requires_elevation=True,
            )

        # 5. Límite Absoluto de max_allowed_risk:
        # Si el riesgo de la operación excede max_allowed_risk, no puede resultar ALLOW
        if eval_score > max_allowed_score:
            logger.info(
                f"Límite absoluto max_allowed_risk superado: [{eval_risk.value} > {active_policy.max_allowed_risk.value}] -> DENY"
            )
            return PolicyDecision(
                decision_type=SecurityDecisionType.DENY,
                is_allowed=False,
                reason=f"Límite absoluto de política: El riesgo '{eval_risk.value}' excede el máximo permitido '{active_policy.max_allowed_risk.value}'. Operación denegada.",
                policy_id=active_policy.policy_id,
                policy_version=active_policy.version,
                policy_source=active_policy.source,
                requires_elevation=requires_elev,
            )

        if eval_risk == SecurityLevel.CRITICAL:
            logger.info("Operación de riesgo CRITICAL bloqueada por política -> DENY")
            return PolicyDecision(
                decision_type=SecurityDecisionType.DENY,
                is_allowed=False,
                reason="Protección crítica: Operaciones de riesgo CRITICAL están bloqueadas por política de seguridad.",
                policy_id=active_policy.policy_id,
                policy_version=active_policy.version,
                policy_source=active_policy.source,
                requires_elevation=requires_elev,
            )

        # 6. Selección por Prioridad Descendente entre reglas autorizadas/confirmables
        if all_matched_rules:
            # Seleccionar la regla con mayor número de prioridad
            selected_rule = max(all_matched_rules, key=lambda r: r.priority)
            if requires_elev:
                is_allowed = False
                decision_type = SecurityDecisionType.REQUIRE_ELEVATED_AUTHORIZATION
            else:
                decision_type = selected_rule.decision
                is_allowed = selected_rule.decision == SecurityDecisionType.ALLOW

            requires_conf = (
                selected_rule.decision == SecurityDecisionType.REQUIRE_CONFIRMATION
                or (selected_rule.requires_confirmation is True)
                or metadata.requires_confirmation
            )

            logger.info(
                f"Regla de política seleccionada [{selected_rule.name}] -> Decision: {decision_type.value} (Prioridad: {selected_rule.priority})"
            )

            return PolicyDecision(
                decision_type=decision_type,
                is_allowed=is_allowed,
                reason=f"Regla de política '{selected_rule.name}' aplicó la decisión {decision_type.value}.",
                matched_rule_id=selected_rule.rule_id,
                matched_rule_name=selected_rule.name,
                priority=selected_rule.priority,
                policy_id=active_policy.policy_id,
                policy_version=active_policy.version,
                policy_source=active_policy.source,
                requires_user_confirmation=requires_conf,
                requires_elevation=requires_elev,
            )

        # 7. Fallback a la decisión predeterminada de la política (Fail-Safe DENY)
        logger.info(f"Ninguna regla coincidente -> Decisión por defecto de política: {active_policy.default_decision.value}")
        is_default_allowed = active_policy.default_decision == SecurityDecisionType.ALLOW
        return PolicyDecision(
            decision_type=active_policy.default_decision,
            is_allowed=is_default_allowed,
            reason=f"Ninguna regla específica coincidió. Aplicando decisión por defecto de política '{active_policy.default_decision.value}'.",
            policy_id=active_policy.policy_id,
            policy_version=active_policy.version,
            policy_source=active_policy.source,
        )


class DefaultPolicyProvider:
    """Proveedor por defecto desacoplado para obtener la Security Policy activa (IPolicyProvider)."""

    def __init__(self, policy: SecurityPolicy | None = None) -> None:
        self._policy = policy or create_default_security_policy()

    def get_policy(self) -> SecurityPolicy:
        """Obtiene la Security Policy declarada."""
        return self._policy
