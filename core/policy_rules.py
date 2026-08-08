"""Motor de reglas de seguridad y políticas configurables multi-dimensión para Jessyca Windows MCP.

Permite definir reglas granulares filtrando por 6 dimensiones clave:
usuario, herramienta, categoría, riesgo, acción y patrón de ruta en los argumentos.
"""

from __future__ import annotations

import fnmatch
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger
from core.security import (
    RISK_HIERARCHY,
    PermissionAction,
    RiskLevel,
    ToolSecurityProfile,
)

logger = get_logger("jessyca.security.policy_rules")


@dataclass
class ConfigurablePolicyRule:
    """Regla declarativa de política de seguridad multi-dimensión."""

    name: str
    effect: PermissionAction
    rule_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    users: set[str] = field(default_factory=lambda: {"*"})
    tools: set[str] = field(default_factory=lambda: {"*"})
    categories: set[str] = field(default_factory=lambda: {"*"})
    min_risk_level: RiskLevel | None = None
    actions: set[str] = field(default_factory=lambda: {"*"})
    path_patterns: set[str] = field(default_factory=set)
    priority: int = 100  # Menor número representa mayor prioridad


class PolicyManager:
    """Gestor y evaluador desacoplado de reglas de políticas de seguridad multi-dimensión."""

    def __init__(self, rules: list[ConfigurablePolicyRule] | None = None) -> None:
        self._rules: list[ConfigurablePolicyRule] = sorted(
            rules or [], key=lambda r: r.priority
        )

    def add_rule(self, rule: ConfigurablePolicyRule) -> None:
        """Añade una regla de política y reordena la lista por prioridad."""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)
        logger.info(f"Regla de política agregada: '{rule.name}' [Efecto: {rule.effect.value}, Prioridad: {rule.priority}]")

    def remove_rule(self, rule_id: str) -> bool:
        """Elimina una regla por su ID de regla."""
        initial_len = len(self._rules)
        self._rules = [r for r in self._rules if r.rule_id != rule_id]
        removed = len(self._rules) < initial_len
        if removed:
            logger.info(f"Regla de política [{rule_id}] eliminada.")
        return removed

    def list_rules(self) -> list[ConfigurablePolicyRule]:
        """Devuelve la lista ordenada de reglas de políticas activas."""
        return list(self._rules)

    def evaluate_rules(
        self,
        profile: ToolSecurityProfile,
        user: str = "system",
        action: str = "execute",
        arguments: dict[str, Any] | None = None,
    ) -> PermissionAction | None:
        """Evalúa una invocación de herramienta contra todas las reglas activas.

        Args:
            profile: Perfil de seguridad de la herramienta.
            user: Nombre del usuario o rol invocador.
            action: Acción solicitada.
            arguments: Argumentos pasados a la herramienta.

        Returns:
            PermissionAction de la primera regla que coincida en las 6 dimensiones o None si ninguna coincide.
        """
        args = arguments or {}

        for rule in self._rules:
            if self._matches_rule(rule, profile, user, action, args):
                logger.info(
                    f"Coincidencia de política multi-dimensión: Regla '{rule.name}' aplicó efecto '{rule.effect.value}'."
                )
                return rule.effect

        return None

    def _matches_rule(
        self,
        rule: ConfigurablePolicyRule,
        profile: ToolSecurityProfile,
        user: str,
        action: str,
        arguments: dict[str, Any],
    ) -> bool:
        """Verifica si la llamada coincide exactamente con las 6 dimensiones de la regla."""
        u_clean = user.strip().lower()
        t_clean = profile.name.strip().lower()
        c_clean = profile.category.strip().lower()
        a_clean = action.strip().lower()

        # 1. Dimensión Usuario
        if "*" not in rule.users and not any(fnmatch.fnmatch(u_clean, target.lower()) for target in rule.users):
            return False

        # 2. Dimensión Herramienta
        if "*" not in rule.tools and not any(fnmatch.fnmatch(t_clean, target.lower()) for target in rule.tools):
            return False

        # 3. Dimensión Categoría
        if "*" not in rule.categories and not any(fnmatch.fnmatch(c_clean, target.lower()) for target in rule.categories):
            return False

        # 4. Dimensión Riesgo (Si se especifica min_risk_level, la regla coincide cuando el riesgo es >= min_risk_level)
        if rule.min_risk_level is not None:
            tool_score = RISK_HIERARCHY.get(profile.risk_level, 1)
            threshold_score = RISK_HIERARCHY.get(rule.min_risk_level, 1)
            if tool_score < threshold_score:
                return False

        # 5. Dimensión Acción
        if "*" not in rule.actions and not any(fnmatch.fnmatch(a_clean, target.lower()) for target in rule.actions):
            return False

        # 6. Dimensión Ruta
        if rule.path_patterns:
            args_str = str(arguments).lower().replace("\\\\", "\\").replace("/", "\\")
            matched_path = False
            for pattern in rule.path_patterns:
                pat_clean = pattern.lower().replace("/", "\\")
                if fnmatch.fnmatch(args_str, f"*{pat_clean}*") or pat_clean in args_str:
                    matched_path = True
                    break
            if not matched_path:
                return False

        return True
