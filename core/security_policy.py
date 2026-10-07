"""Security Policy Engine para Jessyca Windows MCP (Subetapa 04.5).

Capa declarativa de políticas de seguridad independientes del LLM, voz, TTS/STT,
UI o APIs de Windows. Define qué operaciones son permitidas, denegadas o requieren
confirmación/elevación con reglas deterministas, prioridades y protección DENY OVERRIDE.
"""

from __future__ import annotations

import fnmatch
import json
import uuid
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
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


class InvalidPolicyError(FrozenInstanceError, ValueError):
    """Excepción lanzada cuando una política no cumple con los criterios de validación de estructura o inmutabilidad."""

    pass


def _deep_freeze_value(val: Any) -> Any:
    """Congela recursivamente cualquier estructura de datos (dict, list, set, frozenset) a inmutable."""
    if isinstance(val, (Mapping, MappingProxyType)):
        return MappingProxyType({k: _deep_freeze_value(v) for k, v in val.items()})
    elif isinstance(val, (list, tuple, set, frozenset)):
        return tuple(_deep_freeze_value(x) for x in val)
    return val


def _deep_freeze_mapping(data: Any) -> MappingProxyType[Any, Any]:
    """Congela recursivamente un mapping a MappingProxyType inmutable."""
    if isinstance(data, (Mapping, MappingProxyType)):
        return MappingProxyType({k: _deep_freeze_value(v) for k, v in data.items()})
    return MappingProxyType({})


def _deep_unfreeze_value(val: Any) -> Any:
    """Descongela recursivamente valores inmutables para serialización estándar."""
    if isinstance(val, (Mapping, MappingProxyType)):
        return {k: _deep_unfreeze_value(v) for k, v in val.items()}
    elif isinstance(val, (list, tuple, set, frozenset)):
        return [_deep_unfreeze_value(x) for x in val]
    return val


@dataclass(frozen=True)
class PolicyRuleCondition:
    """Condiciones adicionales de coincidencia declarativas e inmutables para una regla de política."""

    path_patterns: tuple[str, ...] = field(default_factory=tuple)
    users: tuple[str, ...] = field(default_factory=lambda: ("*",))
    environments: tuple[str, ...] = field(default_factory=lambda: ("*",))
    parameters: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        raw_patterns = self.path_patterns
        if not isinstance(raw_patterns, (list, tuple, set, frozenset)):
            raw_patterns = [raw_patterns] if raw_patterns else []
        object.__setattr__(self, "path_patterns", tuple(str(p) for p in raw_patterns))

        raw_users = self.users
        if not isinstance(raw_users, (list, tuple, set, frozenset)):
            raw_users = [raw_users] if raw_users else ["*"]
        object.__setattr__(self, "users", tuple(str(u) for u in raw_users))

        raw_env = self.environments
        if not isinstance(raw_env, (list, tuple, set, frozenset)):
            raw_env = [raw_env] if raw_env else ["*"]
        object.__setattr__(self, "environments", tuple(str(e) for e in raw_env))

        object.__setattr__(self, "parameters", _deep_freeze_mapping(self.parameters))

    def to_dict(self) -> dict[str, Any]:
        """Serializa la condición a un diccionario estándar."""
        return {
            "path_patterns": list(self.path_patterns),
            "users": list(self.users),
            "environments": list(self.environments),
            "parameters": _deep_unfreeze_value(self.parameters),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyRuleCondition:
        """Construye una condición inmutable desde un diccionario."""
        return cls(
            path_patterns=data.get("path_patterns", ()),
            users=data.get("users", ("*",)),
            environments=data.get("environments", ("*",)),
            parameters=data.get("parameters", {}),
        )


@dataclass(frozen=True)
class PolicyRule:
    """Regla declarativa individual e inmutable de política de seguridad."""

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
        if isinstance(self.conditions, dict):
            object.__setattr__(self, "conditions", PolicyRuleCondition.from_dict(self.conditions))
        elif not isinstance(self.conditions, PolicyRuleCondition):
            raise InvalidPolicyError(f"Condición inválida para regla '{self.name}': {type(self.conditions)}")

    def to_dict(self) -> dict[str, Any]:
        """Serializa la regla a un diccionario estándar."""
        return {
            "name": self.name,
            "decision": self.decision.value if isinstance(self.decision, SecurityDecisionType) else str(self.decision),
            "rule_id": self.rule_id,
            "description": self.description,
            "enabled": self.enabled,
            "priority": self.priority,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "risk_level": self.risk_level.value if isinstance(self.risk_level, SecurityLevel) else (self.risk_level if self.risk_level is not None else None),
            "requires_confirmation": self.requires_confirmation,
            "requires_elevation": self.requires_elevation,
            "conditions": self.conditions.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyRule:
        """Construye una regla inmutable desde un diccionario."""
        decision = data["decision"]
        if isinstance(decision, str):
            decision = SecurityDecisionType(decision)
        risk_level = data.get("risk_level")
        if isinstance(risk_level, str):
            risk_level = SecurityLevel(risk_level)
        cond = data.get("conditions", {})
        if isinstance(cond, dict):
            cond = PolicyRuleCondition.from_dict(cond)
        return cls(
            name=data["name"],
            decision=decision,
            rule_id=data.get("rule_id", str(uuid.uuid4())),
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 100),
            tool_name=data.get("tool_name", "*"),
            operation=data.get("operation", "*"),
            risk_level=risk_level,
            requires_confirmation=data.get("requires_confirmation"),
            requires_elevation=data.get("requires_elevation"),
            conditions=cond,
        )


@dataclass
class SecurityPolicy:
    """Contenedor principal profundamente inmutable de una política de seguridad declarativa."""

    policy_id: str = "default-system-policy"
    name: str = "Jessyca Default Security Policy"
    description: str = "Política predeterminada conservadora de seguridad con estrategia Fail-Safe"
    version: str = "1.0.0"
    source: PolicySource = PolicySource.SYSTEM
    max_allowed_risk: SecurityLevel = SecurityLevel.DANGEROUS
    rules: tuple[PolicyRule, ...] = field(default_factory=tuple)
    default_decision: SecurityDecisionType = SecurityDecisionType.DENY
    is_immutable: bool = True

    def __post_init__(self) -> None:
        if not self.policy_id or not self.policy_id.strip():
            raise InvalidPolicyError("El campo 'policy_id' no puede estar vacío.")
        if not self.version or not self.version.strip():
            raise InvalidPolicyError("El campo 'version' no puede estar vacío.")

        # Defensive copying y congelación profunda de todas las reglas
        frozen_rules: list[PolicyRule] = []
        raw_rules = self.rules if isinstance(self.rules, (list, tuple, set, frozenset)) else [self.rules]
        for r in raw_rules:
            if isinstance(r, PolicyRule):
                frozen_rules.append(r)
            elif isinstance(r, dict):
                frozen_rules.append(PolicyRule.from_dict(r))
            else:
                raise InvalidPolicyError(f"Elemento inválido en lista de reglas de política: {type(r)}")

        # Ordenar reglas deterministamente por prioridad descendente en tupla inmutable
        object.__setattr__(
            self,
            "rules",
            tuple(sorted(frozen_rules, key=lambda r: r.priority, reverse=True)),
        )
        object.__setattr__(self, "_initialized", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_initialized", False):
            raise InvalidPolicyError(f"SecurityPolicy '{self.policy_id}' es inmutable y no permite modificación de atributos.")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if getattr(self, "_initialized", False):
            raise InvalidPolicyError(f"SecurityPolicy '{self.policy_id}' es inmutable y no permite eliminación de atributos.")
        super().__delattr__(name)

    def to_dict(self) -> dict[str, Any]:
        """Serializa la política completa a un diccionario estándar."""
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "source": self.source.value if isinstance(self.source, PolicySource) else str(self.source),
            "max_allowed_risk": self.max_allowed_risk.value if isinstance(self.max_allowed_risk, SecurityLevel) else str(self.max_allowed_risk),
            "rules": [r.to_dict() for r in self.rules],
            "default_decision": self.default_decision.value if isinstance(self.default_decision, SecurityDecisionType) else str(self.default_decision),
            "is_immutable": self.is_immutable,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SecurityPolicy:
        """Construye un snapshot inmutable de SecurityPolicy desde un diccionario."""
        source = data.get("source", PolicySource.SYSTEM)
        if isinstance(source, str):
            source = PolicySource(source)
        max_risk = data.get("max_allowed_risk", SecurityLevel.DANGEROUS)
        if isinstance(max_risk, str):
            max_risk = SecurityLevel(max_risk)
        default_dec = data.get("default_decision", SecurityDecisionType.DENY)
        if isinstance(default_dec, str):
            default_dec = SecurityDecisionType(default_dec)
        rules_data = data.get("rules", [])
        rules = [PolicyRule.from_dict(r) if isinstance(r, dict) else r for r in rules_data]
        return cls(
            policy_id=data["policy_id"],
            name=data.get("name", "Jessyca Security Policy"),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            source=source,
            max_allowed_risk=max_risk,
            rules=rules,
            default_decision=default_dec,
            is_immutable=data.get("is_immutable", True),
        )

    def to_json(self, indent: int = 2) -> str:
        """Serializa la política a JSON."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> SecurityPolicy:
        """Construye una SecurityPolicy desde JSON."""
        return cls.from_dict(json.loads(json_str))


class PolicyRuleBuilder:
    """Builder administrativo mutable para configurar y publicar PolicyRule inmutables."""

    def __init__(
        self,
        name: str = "",
        decision: SecurityDecisionType = SecurityDecisionType.DENY,
        rule_id: str | None = None,
        description: str = "",
        enabled: bool = True,
        priority: int = 100,
        tool_name: str = "*",
        operation: str = "*",
        risk_level: SecurityLevel | None = None,
        requires_confirmation: bool | None = None,
        requires_elevation: bool | None = None,
        path_patterns: list[str] | None = None,
        users: list[str] | None = None,
        environments: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.decision = decision
        self.rule_id = rule_id or str(uuid.uuid4())
        self.description = description
        self.enabled = enabled
        self.priority = priority
        self.tool_name = tool_name
        self.operation = operation
        self.risk_level = risk_level
        self.requires_confirmation = requires_confirmation
        self.requires_elevation = requires_elevation
        self.path_patterns: list[str] = list(path_patterns or [])
        self.users: list[str] = list(users or ["*"])
        self.environments: list[str] = list(environments or ["*"])
        self.parameters: dict[str, Any] = dict(parameters or {})

    @classmethod
    def from_rule(cls, rule: PolicyRule) -> PolicyRuleBuilder:
        return cls(
            name=rule.name,
            decision=rule.decision,
            rule_id=rule.rule_id,
            description=rule.description,
            enabled=rule.enabled,
            priority=rule.priority,
            tool_name=rule.tool_name,
            operation=rule.operation,
            risk_level=rule.risk_level,
            requires_confirmation=rule.requires_confirmation,
            requires_elevation=rule.requires_elevation,
            path_patterns=list(rule.conditions.path_patterns),
            users=list(rule.conditions.users),
            environments=list(rule.conditions.environments),
            parameters=_deep_unfreeze_value(rule.conditions.parameters),
        )

    def build(self) -> PolicyRule:
        """Construye y publica una regla inmutable PolicyRule."""
        cond = PolicyRuleCondition(
            path_patterns=self.path_patterns,
            users=self.users,
            environments=self.environments,
            parameters=self.parameters,
        )
        return PolicyRule(
            name=self.name,
            decision=self.decision,
            rule_id=self.rule_id,
            description=self.description,
            enabled=self.enabled,
            priority=self.priority,
            tool_name=self.tool_name,
            operation=self.operation,
            risk_level=self.risk_level,
            requires_confirmation=self.requires_confirmation,
            requires_elevation=self.requires_elevation,
            conditions=cond,
        )


class SecurityPolicyBuilder:
    """Builder administrativo mutable para configurar y publicar snapshots inmutables de SecurityPolicy."""

    def __init__(
        self,
        policy_id: str = "custom-policy",
        name: str = "Custom Security Policy",
        description: str = "",
        version: str = "1.0.0",
        source: PolicySource = PolicySource.ADMINISTRATOR,
        max_allowed_risk: SecurityLevel = SecurityLevel.DANGEROUS,
        default_decision: SecurityDecisionType = SecurityDecisionType.DENY,
    ) -> None:
        self.policy_id = policy_id
        self.name = name
        self.description = description
        self.version = version
        self.source = source
        self.max_allowed_risk = max_allowed_risk
        self.default_decision = default_decision
        self._rules: list[PolicyRule | PolicyRuleBuilder] = []

    @classmethod
    def from_policy(cls, policy: SecurityPolicy) -> SecurityPolicyBuilder:
        """Crea un builder mutable a partir de una política inmutable existente."""
        builder = cls(
            policy_id=policy.policy_id,
            name=policy.name,
            description=policy.description,
            version=policy.version,
            source=policy.source,
            max_allowed_risk=policy.max_allowed_risk,
            default_decision=policy.default_decision,
        )
        builder._rules = [PolicyRuleBuilder.from_rule(r) for r in policy.rules]
        return builder

    def add_rule(self, rule: PolicyRule | PolicyRuleBuilder) -> SecurityPolicyBuilder:
        self._rules.append(rule)
        return self

    def remove_rule(self, rule_id: str) -> bool:
        init_len = len(self._rules)
        self._rules = [r for r in self._rules if (r.rule_id if hasattr(r, "rule_id") else r.get("rule_id")) != rule_id]
        return len(self._rules) < init_len

    def clear_rules(self) -> None:
        self._rules.clear()

    def build(self) -> SecurityPolicy:
        """Construye, valida y retorna un snapshot profundamente inmutable de SecurityPolicy."""
        built_rules: list[PolicyRule] = []
        for r in self._rules:
            if isinstance(r, PolicyRuleBuilder):
                built_rules.append(r.build())
            elif isinstance(r, PolicyRule):
                built_rules.append(r)
            elif isinstance(r, dict):
                built_rules.append(PolicyRule.from_dict(r))
            else:
                raise InvalidPolicyError(f"Tipo de regla inválido en builder: {type(r)}")

        policy = SecurityPolicy(
            policy_id=self.policy_id,
            name=self.name,
            description=self.description,
            version=self.version,
            source=self.source,
            max_allowed_risk=self.max_allowed_risk,
            rules=built_rules,
            default_decision=self.default_decision,
            is_immutable=True,
        )
        validate_security_policy(policy)
        return policy


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
        self._policy: SecurityPolicy = policy or create_default_security_policy()

    def get_policy(self) -> SecurityPolicy:
        """Obtiene el snapshot de la Security Policy activa inmutable."""
        return self._policy

    def update_policy(self, new_policy: SecurityPolicy) -> None:
        """Ruta administrativa para sustituir la política activa por una nueva versión completa validada."""
        validate_security_policy(new_policy)
        logger.info(
            f"Política activa actualizada administrativamente: [{new_policy.policy_id} v{new_policy.version}] "
            f"(reglas: {len(new_policy.rules)}, fuente: {new_policy.source.value})"
        )
        self._policy = new_policy

