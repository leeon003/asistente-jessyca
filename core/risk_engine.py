"""Risk Engine para Jessyca Windows MCP (Subetapa 04.2).

Motor de evaluación de riesgo independiente, determinista, extensible y desacoplado.
Su única responsabilidad es responder: "¿Qué nivel de riesgo representa esta operación?"
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, cast, runtime_checkable

from core.logger import get_logger
from core.security_architecture import (
    SecurityLevel,
    SecurityRequest,
    ToolSecurityMetadata,
)

logger = get_logger("jessyca.security.risk_engine")

# Mapas de conversión y jerarquía determinista de niveles de riesgo: READ_ONLY (1) < SAFE (2) < WARNING (3) < DANGEROUS (4) < CRITICAL (5)
SECURITY_RISK_HIERARCHY: dict[str, int] = {
    "READ_ONLY": 1,
    "SAFE": 2,
    "WARNING": 3,
    "DANGEROUS": 4,
    "CRITICAL": 5,
}

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


class RiskFactor(StrEnum):
    """Factores de riesgo estructurados que influyen en la evaluación."""

    DESTRUCTIVE_OPERATION = "DESTRUCTIVE_OPERATION"
    SYSTEM_CONFIGURATION = "SYSTEM_CONFIGURATION"
    ELEVATED_PRIVILEGES = "ELEVATED_PRIVILEGES"
    PROCESS_CONTROL = "PROCESS_CONTROL"
    FILE_MODIFICATION = "FILE_MODIFICATION"
    NETWORK_OPERATION = "NETWORK_OPERATION"
    CREDENTIAL_ACCESS = "CREDENTIAL_ACCESS"
    REGISTRY_MODIFICATION = "REGISTRY_MODIFICATION"
    BULK_OPERATION = "BULK_OPERATION"
    UNKNOWN_OPERATION = "UNKNOWN_OPERATION"


def normalize_to_security_level(level_val: Any) -> SecurityLevel:
    """Normaliza cualquier valor de riesgo (RiskLevel o SecurityLevel o str) a SecurityLevel."""
    if isinstance(level_val, SecurityLevel):
        return level_val
    val_str = str(getattr(level_val, "value", level_val)).upper().strip()
    if val_str == "READ_ONLY":
        return SecurityLevel.SAFE
    try:
        return SecurityLevel(val_str)
    except ValueError:
        return SecurityLevel.SAFE


@dataclass
class RiskAssessment:
    """Resultado formal del análisis de riesgo realizado por el RiskEngine."""

    risk_level: SecurityLevel | Any
    score: int = 2
    reason: str = ""
    matched_rules: list[str] = field(default_factory=list)
    risk_factors: set[RiskFactor] = field(default_factory=set)
    tool_name: str = ""
    operation: str = ""
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    evaluator_version: str = "0.4.2"
    requires_confirmation: bool = False

    @property
    def justification(self) -> str:
        """Alias retrocompatible de justificación explicativa."""
        rl_val = getattr(self.risk_level, "value", str(self.risk_level))
        return self.reason or f"Riesgo consolidado: {rl_val} (Score: {self.score})"


@runtime_checkable
class IRiskRule(Protocol):
    """Protocolo/Interfaz abstracta para las reglas modulares de inspección de riesgo."""

    @property
    def name(self) -> str:
        """Nombre de la regla de riesgo."""
        ...

    def evaluate(
        self, request: SecurityRequest
    ) -> Any:
        """Evalúa una solicitud devolviendo nivel de riesgo o tupla (nivel, factores, motivo)."""
        ...


class RiskRule(ABC):
    """Clase base abstracta para implementar reglas de riesgo."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @abstractmethod
    def evaluate(
        self, request: Any, arguments: dict[str, Any] | None = None
    ) -> Any:
        """Evalúa la solicitud o perfil de seguridad."""
        pass


class StaticMetadataRiskRule(RiskRule):
    """Regla que extrae el nivel de riesgo estático declarado en los metadatos de la herramienta."""

    def __init__(self) -> None:
        super().__init__("StaticMetadataRiskRule")

    def evaluate(
        self, request: Any, arguments: dict[str, Any] | None = None
    ) -> Any:
        if isinstance(request, SecurityRequest):
            meta = request.metadata
            factors: set[RiskFactor] = set()
            sec_level = normalize_to_security_level(meta.risk_level)

            if sec_level == SecurityLevel.CRITICAL:
                factors.add(RiskFactor.SYSTEM_CONFIGURATION)
            elif sec_level == SecurityLevel.DANGEROUS:
                factors.add(RiskFactor.DESTRUCTIVE_OPERATION)

            reason = f"Metadatos declarados para '{meta.tool_name}': {sec_level.value}."
            return sec_level, factors, reason
        else:
            profile = request
            return getattr(profile, "risk_level", SecurityLevel.SAFE)


class PrivilegeRiskRule(RiskRule):
    """Regla que inspecciona solicitudes de elevación UAC o privilegios de administrador."""

    def __init__(self) -> None:
        super().__init__("PrivilegeRiskRule")

    def evaluate(
        self, request: Any, arguments: dict[str, Any] | None = None
    ) -> Any:
        if isinstance(request, SecurityRequest):
            meta = request.metadata
            if meta.requires_elevation:
                return (
                    SecurityLevel.CRITICAL,
                    {RiskFactor.ELEVATED_PRIVILEGES, RiskFactor.SYSTEM_CONFIGURATION},
                    f"Herramienta '{meta.tool_name}' requiere elevación de privilegios de Administrador (UAC).",
                )
        return None, set(), None


class SystemPathRiskRule(RiskRule):
    """Regla que inspecciona argumentos en busca de rutas de sistema críticas o del Registro de Windows."""

    def __init__(self) -> None:
        super().__init__("SystemPathRiskRule")

    def evaluate(
        self, request: Any, arguments: dict[str, Any] | None = None
    ) -> Any:
        params = request.context.parameters if isinstance(request, SecurityRequest) else arguments
        if not params:
            if isinstance(request, SecurityRequest):
                return None, set(), None
            return None

        args_repr = str(params).lower().replace("\\\\", "\\").replace("/", "\\")
        factors: set[RiskFactor] = set()

        if "hkey_local_machine" in args_repr or "hkey_classes_root" in args_repr:
            factors.add(RiskFactor.REGISTRY_MODIFICATION)
            factors.add(RiskFactor.SYSTEM_CONFIGURATION)
            if isinstance(request, SecurityRequest):
                return (
                    SecurityLevel.CRITICAL,
                    factors,
                    "Acceso o modificación detectado en el Registro de Windows (HKLM/HKCR).",
                )
            from core.security import RiskLevel
            return RiskLevel.CRITICAL

        for path in WINDOWS_CRITICAL_PATHS:
            norm_path = path.replace("/", "\\")
            if norm_path in args_repr:
                factors.add(RiskFactor.SYSTEM_CONFIGURATION)
                if isinstance(request, SecurityRequest):
                    return (
                        SecurityLevel.CRITICAL,
                        factors,
                        f"Ruta crítica del sistema detectada en los argumentos: '{path}'.",
                    )
                from core.security import RiskLevel
                return RiskLevel.CRITICAL

        if isinstance(request, SecurityRequest):
            return None, set(), None
        return None


class FileOperationRiskRule(RiskRule):
    """Regla que clasifica operaciones del sistema de archivos seguras vs destructivas."""

    def __init__(self) -> None:
        super().__init__("FileOperationRiskRule")

    def evaluate(
        self, request: Any, arguments: dict[str, Any] | None = None
    ) -> Any:
        if isinstance(request, SecurityRequest):
            act = request.action.lower()
            tool = request.metadata.tool_name.lower()

            if "delete" in act or "remove" in act or "delete" in tool or "remove" in tool:
                return (
                    SecurityLevel.DANGEROUS,
                    {RiskFactor.DESTRUCTIVE_OPERATION, RiskFactor.FILE_MODIFICATION},
                    "Operación destructiva de eliminación de archivos/directorios.",
                )
            elif "write" in act or "modify" in act or "create" in act:
                return (
                    SecurityLevel.WARNING,
                    {RiskFactor.FILE_MODIFICATION},
                    "Operación de modificación/escritura de archivos.",
                )

        return None, set(), None


class ProcessControlRiskRule(RiskRule):
    """Regla que inspecciona el control y finalización de procesos del sistema."""

    def __init__(self) -> None:
        super().__init__("ProcessControlRiskRule")

    def evaluate(
        self, request: Any, arguments: dict[str, Any] | None = None
    ) -> Any:
        if isinstance(request, SecurityRequest):
            act = request.action.lower()
            tool = request.metadata.tool_name.lower()

            if "kill" in act or "terminate" in act or "kill" in tool or "terminate" in tool:
                return (
                    SecurityLevel.DANGEROUS,
                    {RiskFactor.PROCESS_CONTROL, RiskFactor.DESTRUCTIVE_OPERATION},
                    "Operación de finalización forzada de procesos de sistema.",
                )
            elif "start" in act or "launch" in act or "run" in act:
                return (
                    SecurityLevel.WARNING,
                    {RiskFactor.PROCESS_CONTROL},
                    "Operación de inicio de nuevos procesos.",
                )

        return None, set(), None


class BulkOperationRiskRule(RiskRule):
    """Regla que detecta operaciones masivas o recursivas potencialmente destructivas."""

    def __init__(self) -> None:
        super().__init__("BulkOperationRiskRule")

    def evaluate(
        self, request: Any, arguments: dict[str, Any] | None = None
    ) -> Any:
        params = request.context.parameters if isinstance(request, SecurityRequest) else arguments
        if not params:
            if isinstance(request, SecurityRequest):
                return None, set(), None
            return None

        args_str = str(params).lower()
        if "recursive" in args_str and ("true" in args_str or True in params.values()):
            if isinstance(request, SecurityRequest):
                return (
                    SecurityLevel.DANGEROUS,
                    {RiskFactor.BULK_OPERATION, RiskFactor.DESTRUCTIVE_OPERATION},
                    "Operación masiva/recursiva detectada en los argumentos.",
                )
            from core.security import RiskLevel
            return RiskLevel.DANGEROUS

        if isinstance(request, SecurityRequest):
            return None, set(), None
        return None


class UnknownOperationRiskRule(RiskRule):
    """Estrategia Fail-Safe: Asigna WARNING o DANGEROUS a operaciones desconocidas o metadatos vacíos."""

    def __init__(self) -> None:
        super().__init__("UnknownOperationRiskRule")

    def evaluate(
        self, request: Any, arguments: dict[str, Any] | None = None
    ) -> Any:
        if isinstance(request, SecurityRequest):
            act = request.action.strip()
            tool = request.metadata.tool_name.strip()

            if not act or act == "unknown" or not tool:
                return (
                    SecurityLevel.WARNING,
                    {RiskFactor.UNKNOWN_OPERATION},
                    "Estrategia Fail-Safe: Operación desconocida o no clasificada explícitamente.",
                )

        return None, set(), None


class RiskEngine:
    """Motor central de cálculo y evaluación dinámica de riesgos para Jessyca Windows MCP (Subetapa 04.2)."""

    def __init__(self, rules: list[IRiskRule | RiskRule] | None = None) -> None:
        if rules is None:
            self._rules: list[IRiskRule | RiskRule] = [
                StaticMetadataRiskRule(),
                PrivilegeRiskRule(),
                SystemPathRiskRule(),
                FileOperationRiskRule(),
                ProcessControlRiskRule(),
                BulkOperationRiskRule(),
                UnknownOperationRiskRule(),
            ]
        else:
            self._rules = list(rules)

    def add_rule(self, rule: IRiskRule | RiskRule) -> None:
        """Añade una regla personalizada al motor de riesgos."""
        self._rules.append(rule)
        logger.info(f"Nueva regla de riesgo registrada en RiskEngine: '{rule.name}'")

    def evaluate_risk(
        self,
        request_or_profile: Any,
        arguments: dict[str, Any] | None = None,
    ) -> RiskAssessment:
        """Calcula deterministamente el nivel de riesgo consolidado evaluando todas las reglas modulares.

        Soporta tanto `SecurityRequest` (Subetapa 04.2) como `ToolSecurityProfile` (compatibilidad previa).
        """
        is_sec_req = isinstance(request_or_profile, SecurityRequest)
        if is_sec_req:
            request = request_or_profile
            raw_profile = None
            raw_args = request.context.parameters
        else:
            raw_profile = request_or_profile
            raw_args = arguments or {}
            from core.security_architecture import SecurityContext
            sec_level = normalize_to_security_level(getattr(raw_profile, "risk_level", SecurityLevel.SAFE))

            meta = ToolSecurityMetadata(
                tool_name=getattr(raw_profile, "name", "unknown_tool"),
                category=getattr(raw_profile, "category", "general"),
                risk_level=sec_level,
                requires_confirmation=getattr(raw_profile, "requires_confirmation", False),
            )
            ctx = SecurityContext(
                user="system",
                tool_name=meta.tool_name,
                parameters=raw_args,
            )
            request = SecurityRequest(context=ctx, metadata=meta)

        max_score = 0
        final_risk: Any = SecurityLevel.SAFE
        matched_rules: list[str] = []
        all_factors: set[RiskFactor] = set()
        reasons: list[str] = []

        for rule in self._rules:
            try:
                res: Any = None
                if is_sec_req:
                    res = rule.evaluate(request)
                else:
                    try:
                        res = cast(Any, rule).evaluate(raw_profile, raw_args)
                    except (AttributeError, TypeError):
                        res = rule.evaluate(request)

                if res is not None:
                    res_risk = res
                    factors: set[RiskFactor] = set()
                    reason: str | None = None

                    if isinstance(res, tuple):
                        if len(res) == 3:
                            res_risk, factors, reason = res
                        elif len(res) == 2:
                            res_risk, factors = res

                    if res_risk is not None:
                        matched_rules.append(rule.name)
                        all_factors.update(factors)
                        if reason:
                            reasons.append(reason)

                        val_str = str(getattr(res_risk, "value", res_risk)).upper().strip()
                        score = SECURITY_RISK_HIERARCHY.get(val_str, 2)
                        if score > max_score:
                            max_score = score
                            final_risk = res_risk
            except Exception as e:
                logger.error(f"Error evaluando regla de riesgo '{rule.name}': {e}")

        if not is_sec_req:
            final_risk = normalize_to_security_level(final_risk)
            from core.security import RiskLevel
            try:
                final_risk = RiskLevel(final_risk.value)
            except (ValueError, AttributeError):
                pass

        requires_conf = (
            str(getattr(final_risk, "value", final_risk)).upper() in ("DANGEROUS", "CRITICAL")
            or request.metadata.requires_confirmation
        )
        final_val_str = str(getattr(final_risk, "value", final_risk)).upper()
        justification_str = f"Riesgo consolidado: {final_val_str} (Score: {max_score}). " + " ".join(reasons)

        logger.debug(
            f"RiskEngine evaluó '{request.metadata.tool_name}' -> Level: {final_val_str} Score: {max_score} Factors: {[f.value for f in all_factors]}"
        )

        return RiskAssessment(
            risk_level=final_risk,
            score=max_score,
            reason=justification_str.strip(),
            matched_rules=matched_rules,
            risk_factors=all_factors,
            tool_name=request.metadata.tool_name,
            operation=request.action,
            requires_confirmation=requires_conf,
        )
