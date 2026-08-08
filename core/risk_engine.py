"""Risk Engine para Jessyca Windows MCP.

Motor de evaluación dinámica del nivel de riesgo (RiskLevel) para herramientas MCP,
considerando metadatos declarativos estáticos y parámetros de entrada en tiempo de ejecución.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger
from core.security import RISK_HIERARCHY, RiskLevel, ToolSecurityProfile

logger = get_logger("jessyca.security.risk_engine")

# Definición de rutas y claves de registro críticas de Windows
WINDOWS_CRITICAL_PATHS: set[str] = {
    "c:/windows",
    "c:\\windows",
    "c:/windows/system32",
    "c:\\windows\\system32",
    "c:/windows/syswow64",
    "c:\\windows\\syswow64",
    "hkey_local_machine",
    "hkey_classes_root",
}


@dataclass
class RiskAssessment:
    """Resultado formal del análisis de riesgo realizado por el RiskEngine."""

    risk_level: RiskLevel
    score: int
    matched_rules: list[str] = field(default_factory=list)
    justification: str = ""
    requires_confirmation: bool = False


class RiskRule(ABC):
    """Clase base abstracta para reglas de inspección y cálculo de riesgo."""

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def evaluate(self, profile: ToolSecurityProfile, arguments: dict[str, Any] | None = None) -> RiskLevel | None:
        """Evalúa una herramienta y sus argumentos devolviendo un RiskLevel o None si no aplica."""
        pass


class StaticMetadataRiskRule(RiskRule):
    """Regla base que extrae el nivel de riesgo estático declarado en la herramienta."""

    def __init__(self) -> None:
        super().__init__("StaticMetadataRiskRule")

    def evaluate(self, profile: ToolSecurityProfile, arguments: dict[str, Any] | None = None) -> RiskLevel | None:
        return profile.risk_level


class SystemPathRiskRule(RiskRule):
    """Regla que inspecciona argumentos en busca de rutas críticas o registro de Windows."""

    def __init__(self) -> None:
        super().__init__("SystemPathRiskRule")

    def evaluate(self, profile: ToolSecurityProfile, arguments: dict[str, Any] | None = None) -> RiskLevel | None:
        if not arguments:
            return None

        # Normalizar barras e inspeccionar cadena de argumentos
        args_repr = str(arguments).lower().replace("\\\\", "\\").replace("/", "\\")
        for path in WINDOWS_CRITICAL_PATHS:
            norm_path = path.replace("/", "\\")
            if norm_path in args_repr:
                logger.warning(f"SystemPathRiskRule activada: Ruta crítica '{path}' detectada en argumentos.")
                return RiskLevel.CRITICAL

        return None


class BulkOperationRiskRule(RiskRule):
    """Regla que detecta operaciones masivas o recursivas potencialmente destructivas."""

    def __init__(self) -> None:
        super().__init__("BulkOperationRiskRule")

    def evaluate(self, profile: ToolSecurityProfile, arguments: dict[str, Any] | None = None) -> RiskLevel | None:
        if not arguments:
            return None

        args_str = str(arguments).lower()
        if "recursive" in args_str and ("true" in args_str or True in arguments.values()):
            if profile.risk_level in (RiskLevel.WARNING, RiskLevel.SAFE):
                logger.warning("BulkOperationRiskRule activada: Operación recursiva eleva riesgo a DANGEROUS.")
                return RiskLevel.DANGEROUS

        return None


class RiskEngine:
    """Motor central de cálculo y evaluación dinámica de riesgos."""

    def __init__(self, rules: list[RiskRule] | None = None) -> None:
        if rules is None:
            self._rules: list[RiskRule] = [
                StaticMetadataRiskRule(),
                SystemPathRiskRule(),
                BulkOperationRiskRule(),
            ]
        else:
            self._rules = rules

    def add_rule(self, rule: RiskRule) -> None:
        """Añade una regla personalizada al motor de riesgos."""
        self._rules.append(rule)
        logger.info(f"Nueva regla de riesgo registrada: '{rule.name}'")

    def evaluate_risk(
        self,
        profile: ToolSecurityProfile,
        arguments: dict[str, Any] | None = None,
    ) -> RiskAssessment:
        """Calcula el nivel de riesgo consolidado evaluando todas las reglas activas.

        Args:
            profile: Perfil de la herramienta a evaluar.
            arguments: Diccionario de argumentos en tiempo de ejecución.

        Returns:
            RiskAssessment con el RiskLevel final, score y reglas activadas.
        """
        args = arguments or {}
        max_score = 0
        final_risk = profile.risk_level
        matched_rules: list[str] = []

        for rule in self._rules:
            try:
                res_risk = rule.evaluate(profile, args)
                if res_risk is not None:
                    score = RISK_HIERARCHY.get(res_risk, 1)
                    matched_rules.append(rule.name)
                    if score > max_score:
                        max_score = score
                        final_risk = res_risk
            except Exception as e:
                logger.error(f"Error evaluando regla de riesgo '{rule.name}': {e}")

        requires_conf = final_risk in (RiskLevel.DANGEROUS, RiskLevel.CRITICAL) or profile.requires_confirmation
        justification = (
            f"Riesgo consolidado: {final_risk.value} (Score: {max_score}). Reglas activadas: {matched_rules}"
        )

        return RiskAssessment(
            risk_level=final_risk,
            score=max_score,
            matched_rules=matched_rules,
            justification=justification,
            requires_confirmation=requires_conf,
        )
