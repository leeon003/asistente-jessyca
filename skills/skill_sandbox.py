"""Sandbox de aislamiento de seguridad para Skills (skill_sandbox.py - Fase 28.2).

Implementa el aislamiento riguroso de Skills:
1. Frontera de herramientas declaradas: Prohibición de invocar tools no declaradas.
2. Contención de privilegios: Bloqueo de subprocess arbitrario, PowerShell sin límites y rutas críticas.
3. Prevalencia de Parada de Emergencia: Interrupción inmediata.
4. Límite de delegación recursiva (MAX_DELEGATION_DEPTH = 3).
5. Sanitización de secretos (Zero-Leakage) y defensa contra Prompt Injection en Untrusted Data.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.command_output import SecretRedactor
from core.emergency_stop import EmergencyStopManager
from core.exceptions import MCPError
from core.logger import get_logger
from core.permission_manager import (
    PermissionDecision,
    PermissionManager,
)
from core.risk_engine import (
    WINDOWS_CRITICAL_PATHS,
    RiskEngine,
)
from core.security_architecture import (
    SecurityContext,
    SecurityLevel,
    SecurityRequest,
    ToolSecurityMetadata,
)
from skills.base_skill import BaseSkill

logger = get_logger("jessyca.skills.sandbox")

MAX_SKILL_DELEGATION_DEPTH: int = 3

PROMPT_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?prior\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(DAN|unrestricted|in\s+godmode)", re.IGNORECASE),
    re.compile(r"\[INST\].*?\[/INST\]", re.DOTALL | re.IGNORECASE),
    re.compile(r"<system>.*?</system>", re.DOTALL | re.IGNORECASE),
]

FORBIDDEN_DIRECT_TOOLS: set[str] = {
    "cmd.raw_exec",
    "powershell.raw_exec",
    "system.elevate_admin",
    "security.disable_pipeline",
    "emergency_stop.deactivate",
    "kernel.direct_call",
}


class SkillSandboxSecurityError(MCPError):
    """Error base de violaciones de seguridad en el Skill Sandbox."""

    pass


class SkillUndeclaredToolError(SkillSandboxSecurityError):
    """Error emitido cuando una Skill intenta invocar una herramienta no declarada en su manifiesto."""

    pass


class SkillRecursionLimitError(SkillSandboxSecurityError):
    """Error emitido cuando una Skill supera el límite máximo de delegación recursiva."""

    pass


class SkillSecurityViolationError(SkillSandboxSecurityError):
    """Error emitido por accesos fuera de límites, manipulación o inyecciones."""

    pass


@dataclass(frozen=True)
class UntrustedDataWrapper:
    """Contenedor inmutable que envuelve datos externos (web, documentos, memoria, outputs)."""

    source: str
    content: str
    is_untrusted: bool = True
    sanitized: bool = True
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def wrap(cls, source: str, raw_content: str) -> UntrustedDataWrapper:
        """Sanitiza y envuelve datos no confiables neutralizando patrones de prompt injection."""
        clean_text = raw_content
        for pattern in PROMPT_INJECTION_PATTERNS:
            clean_text = pattern.sub("[REDACTED_UNTRUSTED_INSTRUCTION]", clean_text)

        redacted_text, _ = SecretRedactor.redact(clean_text)
        return cls(
            source=source,
            content=redacted_text,
            is_untrusted=True,
            sanitized=True,
        )


@dataclass(frozen=True)
class SkillSandboxExecutionResult:
    """Resultado formal del despacho de una acción dentro del sandbox de seguridad."""

    decision: str  # ALLOW, DENY, REQUIRE_CONFIRMATION, STOP
    success: bool
    output: Any = None
    error: str | None = None
    reason: str = ""
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class SkillSecuritySandbox:
    """Sandbox de Aislamiento y Gobernanza para Habilidades de JESSYCA (Fase 28.2)."""

    def __init__(
        self,
        risk_engine: RiskEngine | None = None,
        permission_manager: PermissionManager | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.risk_engine = risk_engine or RiskEngine()
        self.permission_manager = permission_manager or PermissionManager()
        self.emergency_stop = emergency_stop or EmergencyStopManager.get_instance()

    def invoke_tool(
        self,
        skill: BaseSkill,
        tool_name: str,
        parameters: dict[str, Any],
        delegation_depth: int = 0,
        tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
        confirmation_approved: bool = False,
    ) -> SkillSandboxExecutionResult:
        """Despacha de forma segura una invocación de herramienta solicitada por una Skill."""
        start_time = time.perf_counter()

        # 1. PREVALENCIA DE PARADA DE EMERGENCIA
        if self.emergency_stop.is_stopped():
            logger.critical(f"[SANDBOX STOPPED] Skill '{skill.skill_id}' intentó invocar tool tras Emergency Stop.")
            return SkillSandboxExecutionResult(
                decision="STOP",
                success=False,
                error="Parada de Emergencia activa en el sistema. Invocación de herramienta bloqueada.",
                reason="EmergencyStopManager está activo.",
            )

        # 2. CONTROL DE DELEGACIÓN RECURSIVA
        if delegation_depth > MAX_SKILL_DELEGATION_DEPTH:
            logger.error(
                f"[SANDBOX RECURSION ERROR] Skill '{skill.skill_id}' superó el límite de delegación ({delegation_depth} > {MAX_SKILL_DELEGATION_DEPTH})."
            )
            return SkillSandboxExecutionResult(
                decision="DENY",
                success=False,
                error=f"Límite de delegación recursiva superado ({delegation_depth} > {MAX_SKILL_DELEGATION_DEPTH}).",
                reason="Delegación recursiva no autorizada.",
            )

        # 3. BLOQUEO DE HERRAMIENTAS Y VECTORES DIRECTOS PROHIBIDOS
        if tool_name.lower() in FORBIDDEN_DIRECT_TOOLS or "raw_exec" in tool_name.lower() or "disable_pipeline" in tool_name.lower() or "elevate" in tool_name.lower():
            logger.critical(
                f"[SANDBOX PRIVILEGE ESCALATION] Skill '{skill.skill_id}' intentó invocar vector prohibido '{tool_name}'."
            )
            return SkillSandboxExecutionResult(
                decision="DENY",
                success=False,
                error=f"Acceso denegado: Invocación de vector directo o prohibido '{tool_name}'.",
                reason="Vector prohibido de ejecución directa.",
            )

        # 4. VERIFICACIÓN DE HERRAMIENTA DECLARADA
        declared_tools = set(skill.definition.required_tools)
        if skill.definition.manifest:
            declared_tools.update(skill.definition.manifest.required_tools)

        # Si la herramienta no está declarada ni en tools ni asociada a capacidades
        if tool_name not in declared_tools:
            # Comprobar si corresponde por prefijo a alguna capacidad declarada
            has_matching_cap = any(
                tool_name.startswith(cap.replace("_", ".")) or cap.replace("_", ".") in tool_name
                for cap in skill.definition.capabilities
            )
            if not has_matching_cap:
                logger.warning(
                    f"[SANDBOX UNDECLARED TOOL] Skill '{skill.skill_id}' intentó invocar la herramienta no declarada '{tool_name}'."
                )
                return SkillSandboxExecutionResult(
                    decision="DENY",
                    success=False,
                    error=f"Violación de sandbox: La herramienta '{tool_name}' no fue declarada por la Skill '{skill.skill_id}'.",
                    reason="Herramienta no declarada.",
                )

        # 5. INSPECCIÓN DE RUTAS CRÍTICAS DE WINDOWS EN PARÁMETROS
        params_str = str(parameters).lower().replace("\\\\", "\\").replace("/", "\\")
        for crit_path in WINDOWS_CRITICAL_PATHS:
            if crit_path.replace("/", "\\") in params_str:
                logger.warning(
                    f"[SANDBOX PATH VIOLATION] Skill '{skill.skill_id}' intentó acceder a ruta crítica '{crit_path}'."
                )
                return SkillSandboxExecutionResult(
                    decision="DENY",
                    success=False,
                    error=f"Violación de sandbox: Intento de acceso a ruta protegida del sistema operativo '{crit_path}'.",
                    reason="Ruta protegida del sistema.",
                )

        # 6. EVALUACIÓN DE RIESGO Y PERMISOS (SecurityPipeline)
        sec_req = SecurityRequest(
            action="execute",
            context=SecurityContext(
                user="skill_user",
                tool_name=tool_name,
                parameters=parameters,
            ),
            metadata=ToolSecurityMetadata(
                tool_name=tool_name,
                category="skill_sandbox",
                risk_level=skill.definition.risk_level,
            ),
        )

        risk_assessment = self.risk_engine.evaluate_risk(sec_req)
        effective_risk = risk_assessment.risk_level

        perm_decision = self.permission_manager.check_permission(
            tool_name=tool_name,
            risk_level=effective_risk,
        )

        if perm_decision == PermissionDecision.DENY:
            logger.warning(f"[SANDBOX PERMISSION DENIED] Tool '{tool_name}' denegada por PermissionManager.")
            return SkillSandboxExecutionResult(
                decision="DENY",
                success=False,
                error=f"Autorización denegada por PermissionManager para la herramienta '{tool_name}'.",
                reason="Permiso denegado por política.",
            )

        if effective_risk in (SecurityLevel.DANGEROUS, SecurityLevel.CRITICAL) or perm_decision == PermissionDecision.REQUIRE_CONFIRMATION:
            if not confirmation_approved:
                logger.info(f"[SANDBOX CONFIRMATION REQUIRED] Tool '{tool_name}' requiere confirmación interactiva.")
                return SkillSandboxExecutionResult(
                    decision="REQUIRE_CONFIRMATION",
                    success=False,
                    error=f"La herramienta '{tool_name}' representa riesgo '{effective_risk.value}' y exige confirmación previa.",
                    reason="Operación de riesgo elevado requiere confirmación humana.",
                )

        # 7. EJECUCIÓN SEGURA Y SANITIZACIÓN DE SECRETOS
        try:
            raw_output: Any = "OK: Operación completada"
            if tool_executor:
                raw_output = tool_executor(tool_name, parameters)

            # Sanitizar salida si es texto, diccionario o lista
            clean_output: Any = raw_output
            if isinstance(raw_output, str):
                clean_output, _ = SecretRedactor.redact(raw_output)
            elif isinstance(raw_output, (dict, list)):
                import json
                try:
                    dumped = json.dumps(raw_output)
                    redacted_json, _ = SecretRedactor.redact(dumped)
                    clean_output = json.loads(redacted_json)
                except Exception:
                    clean_output, _ = SecretRedactor.redact(str(raw_output))

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillSandboxExecutionResult(
                decision="ALLOW",
                success=True,
                output=clean_output,
                reason="Operación autorizada y ejecutada en el sandbox.",
                duration_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillSandboxExecutionResult(
                decision="ALLOW",
                success=False,
                error=str(e),
                reason="Excepción durante la ejecución de la herramienta.",
                duration_ms=elapsed_ms,
            )
