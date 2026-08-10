"""Gestor declarativo de políticas de comandos y listas blancas (CommandPolicyManager - Subetapa 07.1).

GARANTÍA ABSOLUTA DE CERO EJECUCIÓN EN 07.1:
Este módulo es estrictamente POLICY-ONLY / METADATA-ONLY.
NO utiliza subprocess, os.system, os.popen, shell=True, cmd.exe ni powershell.exe.
La ejecución real de procesos está reservada exclusivamente para la Subetapa 07.4.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.exceptions import MCPError
from core.logger import get_logger
from core.permission_manager import PermissionDecision
from core.security_architecture import SecurityLevel

logger = get_logger("jessyca.core.command_policy")

# Operadores y metacarácteres de shell prohibidos expresamente
DANGEROUS_SHELL_PATTERNS = re.compile(
    r"(&&|\|\||&|\||;|\$|\(|\)|>|<|`|\$\{)",
    re.IGNORECASE,
)

# Ejecutables restringidos por defecto
RESTRICTED_EXECUTABLES = {"powershell.exe", "pwsh.exe", "cmd.exe", "powershell", "pwsh", "cmd"}


class CommandPolicyError(MCPError):
    """Error base de la política de comandos."""

    pass


class DuplicateRuleError(CommandPolicyError):
    """Error emitido al intentar registrar una regla duplicada o con ID existente."""

    pass


class RegistryLockedError(CommandPolicyError):
    """Error emitido al intentar modificar un registro de políticas sellado (locked)."""

    pass


@dataclass(frozen=True)
class CommandAllowlistRule:
    """Regla declarativa inmutable de lista blanca de comandos."""

    rule_id: str
    executable: str
    allowed_arguments_patterns: tuple[str, ...] = field(default_factory=tuple)
    risk_level: SecurityLevel = SecurityLevel.SAFE
    decision: PermissionDecision = PermissionDecision.ALLOW
    requires_confirmation: bool = False
    requires_elevation: bool = False
    description: str = ""
    enabled: bool = True
    immutable: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convierte la regla a un diccionario estructurado."""
        return {
            "rule_id": self.rule_id,
            "executable": self.executable,
            "allowed_arguments_patterns": list(self.allowed_arguments_patterns),
            "risk_level": self.risk_level.value,
            "decision": self.decision.value,
            "requires_confirmation": self.requires_confirmation,
            "requires_elevation": self.requires_elevation,
            "description": self.description,
            "enabled": self.enabled,
            "immutable": self.immutable,
        }


@dataclass(frozen=True)
class CommandPolicyEvaluation:
    """Resultado inmutable de la evaluación de política de un comando."""

    executable: str
    arguments: tuple[str, ...]
    decision: PermissionDecision
    risk_level: SecurityLevel
    reason: str
    rule_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado de evaluación a un diccionario estructurado."""
        return {
            "executable": self.executable,
            "arguments": list(self.arguments),
            "decision": self.decision.value,
            "risk_level": self.risk_level.value,
            "reason": self.reason,
            "rule_id": self.rule_id,
        }


class ShellMetacharacterDetector:
    """Detector determinista de metacarácteres y operadores peligrosos de shell."""

    @staticmethod
    def contains_dangerous_metacharacters(text: str) -> bool:
        """Verifica si la cadena contiene operadores de shell no autorizados."""
        if not text:
            return False
        return bool(DANGEROUS_SHELL_PATTERNS.search(text))


class CommandRiskClassifier:
    """Clasificador de riesgo determinista para comandos de consola.

    INVARIANTE DE SEGURIDAD:
    UNKNOWN -> DENY
    CRITICAL -> NO ALLOW
    """

    @staticmethod
    def classify(
        executable: str,
        arguments: tuple[str, ...],
        rule: CommandAllowlistRule | None,
    ) -> SecurityLevel:
        """Clasifica el nivel de riesgo del comando solicitado."""
        if not rule or not rule.enabled:
            return SecurityLevel.CRITICAL  # UNKNOWN representa alto riesgo -> DENY
        return rule.risk_level


class CommandPolicyManager:
    """Gestor thread-safe y sellable de políticas de comandos y listas blancas."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rules: dict[str, CommandAllowlistRule] = {}
        self._locked: bool = False
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

        settings = AppSettings()
        self.max_arguments: int = settings.COMMAND_MAX_ARGUMENTS
        self.max_argument_length: int = settings.COMMAND_MAX_ARGUMENT_LENGTH

        self._register_default_rules()

    def _register_default_rules(self) -> None:
        """Registra las reglas declarativas por defecto iniciales."""
        defaults = [
            CommandAllowlistRule(
                rule_id="rule-git",
                executable="git",
                allowed_arguments_patterns=("status", "log", "diff", "branch", "version"),
                risk_level=SecurityLevel.SAFE,
                decision=PermissionDecision.ALLOW,
                description="Comandos de inspección de Git autorizados por defecto.",
            ),
            CommandAllowlistRule(
                rule_id="rule-dir",
                executable="dir",
                allowed_arguments_patterns=(),
                risk_level=SecurityLevel.SAFE,
                decision=PermissionDecision.ALLOW,
                description="Comando de listado de directorio.",
            ),
            CommandAllowlistRule(
                rule_id="rule-echo",
                executable="echo",
                allowed_arguments_patterns=(),
                risk_level=SecurityLevel.SAFE,
                decision=PermissionDecision.ALLOW,
                description="Comando de impresión de texto.",
            ),
            CommandAllowlistRule(
                rule_id="rule-ipconfig",
                executable="ipconfig",
                allowed_arguments_patterns=("/all",),
                risk_level=SecurityLevel.SAFE,
                decision=PermissionDecision.ALLOW,
                description="Comando de consulta de interfaz de red.",
            ),
            CommandAllowlistRule(
                rule_id="rule-systeminfo",
                executable="systeminfo",
                allowed_arguments_patterns=(),
                risk_level=SecurityLevel.SAFE,
                decision=PermissionDecision.ALLOW,
                description="Comando de consulta de información de sistema.",
            ),
        ]
        for r in defaults:
            self._rules[r.executable.lower()] = r

    def register_rule(self, rule: CommandAllowlistRule) -> None:
        """Registra una nueva regla de lista blanca en el gestor."""
        with self._lock:
            if self._locked:
                raise RegistryLockedError("No se pueden registrar reglas en un CommandPolicyManager sellado (locked).")

            key = rule.executable.lower()
            if key in self._rules and self._rules[key].immutable:
                raise DuplicateRuleError(f"Regla inmutable existente para el ejecutable: '{rule.executable}'.")

            self._rules[key] = rule

    def get_rule(self, executable: str) -> CommandAllowlistRule | None:
        """Busca una regla registrada por el nombre del ejecutable."""
        with self._lock:
            return self._rules.get(executable.lower())

    def lock_registry(self) -> None:
        """Sella el registro impidiendo posteriores modificaciones o adición de reglas."""
        with self._lock:
            self._locked = True

    def is_locked(self) -> bool:
        """Retorna True si el registro está sellado."""
        with self._lock:
            return self._locked

    def evaluate_command(
        self,
        raw_executable_or_command: str,
        arguments: list[str] | tuple[str, ...] | None = None,
    ) -> CommandPolicyEvaluation:
        """Evalúa un comando y sus argumentos devolviendo una decisión determinista (FAIL-SAFE DENY)."""
        args_tuple = tuple(arguments or ())
        exec_name = raw_executable_or_command.strip()

        # 1. Detección de entrada nula o vacía
        if not exec_name:
            return self._deny_evaluation(exec_name, args_tuple, "Ejecutable o comando vacío.")

        # 2. Detección de caracteres nulos
        if "\x00" in exec_name or any("\x00" in a for a in args_tuple):
            return self._deny_evaluation(exec_name, args_tuple, "Detección de caracteres nulos (null bytes).")

        # 3. Detección de metacarácteres peligrosos de shell
        if ShellMetacharacterDetector.contains_dangerous_metacharacters(exec_name) or any(
            ShellMetacharacterDetector.contains_dangerous_metacharacters(a) for a in args_tuple
        ):
            return self._reject_evaluation(
                exec_name, args_tuple, "Rechazado: Contiene operadores o metacarácteres peligrosos de shell."
            )

        # 4. Verificación de ejecutables restringidos (powershell.exe, cmd.exe)
        exec_base = exec_name.split("\\")[-1].split("/")[-1].lower()
        if exec_base in RESTRICTED_EXECUTABLES:
            return self._deny_evaluation(
                exec_name,
                args_tuple,
                f"Rechazado: El ejecutable '{exec_base}' es restringido por defecto en Subetapa 07.1.",
            )

        # 5. Detección de límites de argumentos
        if len(args_tuple) > self.max_arguments:
            return self._deny_evaluation(
                exec_name,
                args_tuple,
                f"Excedido el límite máximo de argumentos ({len(args_tuple)} > {self.max_arguments}).",
            )

        for arg in args_tuple:
            if len(arg) > self.max_argument_length:
                return self._deny_evaluation(
                    exec_name,
                    args_tuple,
                    f"Excedido el límite máximo de longitud de argumento ({len(arg)} > {self.max_argument_length}).",
                )

        # 6. Búsqueda de regla en la Lista Blanca (Allowlist)
        rule = self.get_rule(exec_base)
        if not rule or not rule.enabled:
            return self._deny_evaluation(
                exec_name,
                args_tuple,
                f"FAIL-SAFE DENY: El ejecutable '{exec_base}' no está registrado en la lista blanca de comandos.",
            )

        # 7. Verificación de patrones de argumentos permitidos si se han especificado en la regla
        if rule.allowed_arguments_patterns and args_tuple:
            first_arg = args_tuple[0].lower()
            if not any(pattern.lower() in first_arg for pattern in rule.allowed_arguments_patterns):
                return self._deny_evaluation(
                    exec_name,
                    args_tuple,
                    f"Argumento '{first_arg}' no permitido por la regla '{rule.rule_id}'.",
                    rule_id=rule.rule_id,
                )

        # 8. Evaluación de decisiones y niveles de riesgo
        risk = CommandRiskClassifier.classify(exec_name, args_tuple, rule)

        # Invariante: UNKNOWN o CRITICAL nunca es ALLOW
        if risk == SecurityLevel.CRITICAL and rule.decision == PermissionDecision.ALLOW:
            decision = PermissionDecision.REQUIRE_CONFIRMATION
        elif rule.requires_elevation:
            decision = PermissionDecision.REQUIRE_ELEVATED_AUTHORIZATION
        elif rule.requires_confirmation:
            decision = PermissionDecision.REQUIRE_CONFIRMATION
        else:
            decision = rule.decision

        eval_result = CommandPolicyEvaluation(
            executable=exec_name,
            arguments=args_tuple,
            decision=decision,
            risk_level=risk,
            reason=f"Comando autorizado por regla '{rule.rule_id}'.",
            rule_id=rule.rule_id,
        )

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.COMMAND_POLICY_ALLOWED,
                tool_name="windows.shell",
                operation="evaluate_command",
                reason=eval_result.reason,
                metadata=eval_result.to_dict(),
            )
        )
        self.event_bus.publish("command:policy_allowed", eval_result.to_dict())

        return eval_result

    def _deny_evaluation(
        self,
        exec_name: str,
        args_tuple: tuple[str, ...],
        reason: str,
        rule_id: str | None = None,
    ) -> CommandPolicyEvaluation:
        """Produce una evaluación de denegación (DENY)."""
        res = CommandPolicyEvaluation(
            executable=exec_name,
            arguments=args_tuple,
            decision=PermissionDecision.DENY,
            risk_level=SecurityLevel.CRITICAL,
            reason=reason,
            rule_id=rule_id,
        )
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.COMMAND_POLICY_DENIED,
                tool_name="windows.shell",
                operation="evaluate_command",
                reason=reason,
                metadata=res.to_dict(),
            )
        )
        self.event_bus.publish("command:policy_denied", res.to_dict())
        return res

    def _reject_evaluation(
        self,
        exec_name: str,
        args_tuple: tuple[str, ...],
        reason: str,
    ) -> CommandPolicyEvaluation:
        """Produce una evaluación de rechazo por metacarácteres o inyección (REJECTED)."""
        res = CommandPolicyEvaluation(
            executable=exec_name,
            arguments=args_tuple,
            decision=PermissionDecision.DENY,
            risk_level=SecurityLevel.CRITICAL,
            reason=reason,
            rule_id=None,
        )
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.COMMAND_POLICY_REJECTED,
                tool_name="windows.shell",
                operation="evaluate_command",
                reason=reason,
                metadata=res.to_dict(),
            )
        )
        self.event_bus.publish("command:policy_rejected", res.to_dict())
        return res
