"""Frontera de seguridad específica para ejecuciones en entornos PowerShell (PowerShellExecutionBoundary - Subetapa 07.3).

GARANTÍA ABSOLUTA DE CERO EJECUCIÓN REAL EN 07.3:
Este módulo realiza ÚNICAMENTE validación de seguridad, detección de evasiones/obfuscación
y construcción de la estructura inmutable PowerShellInvocation.
NO utiliza subprocess, asyncio.create_subprocess_exec, os.system, os.popen, shell=True,
cmd.exe, powershell.exe, eval ni exec.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.exceptions import MCPError
from core.logger import get_logger
from core.permission_manager import PermissionDecision

logger = get_logger("jessyca.core.powershell_boundary")

# Banderas de bypass explícitamente prohibidas
FORBIDDEN_POWERSHELL_FLAGS = re.compile(
    r"-(encodedcommand|encoded|enc|executionpolicy\s+bypass|executionpolicy\s+unrestricted|commandwithargs|noexit|windowstyle\s+hidden|-c(\s+|$)|-command(\s+|$))",
    re.IGNORECASE,
)

# Patrones de obfuscación y ejecución dinámica prohibidos
POWERSHELL_OBFUSCATION_PATTERNS = re.compile(
    r"(invoke-expression|iex|invoke-command|start-process|new-object|add-type|system\.reflection|downloadstring|downloadfile|&\s*[\{\(])",
    re.IGNORECASE,
)


class ShellBoundaryError(MCPError):
    """Error base de fronteras de ejecuciones de consola."""

    pass


class PowerShellBypassRejectedError(ShellBoundaryError):
    """Error emitido al detectar banderas prohibidas o intentos de bypass en PowerShell."""

    pass


class ObfuscationDetectedError(ShellBoundaryError):
    """Error emitido al detectar obfuscación o ejecución dinámica en PowerShell."""

    pass


class FingerprintMismatchError(ShellBoundaryError):
    """Error emitido al detectar inconsistencia en la firma criptográfica action_fingerprint."""

    pass


@dataclass(frozen=True)
class ExecutionBoundaryDecision:
    """Resultado inmutable de la evaluación de frontera de ejecutor de consola."""

    allowed: bool
    reason: str
    decision: PermissionDecision
    shell_type: str
    rule_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convierte la decisión a un diccionario estructurado."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "decision": self.decision.value,
            "shell_type": self.shell_type,
            "rule_id": self.rule_id,
        }


@dataclass(frozen=True)
class PowerShellInvocation:
    """Estructura inmutable de la representación segura de invocación PowerShell."""

    executable: str
    mandatory_flags: tuple[str, ...]
    arguments: tuple[str, ...]
    action_fingerprint: str
    request_id: str
    is_valid: bool
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convierte la invocación a un diccionario estructurado."""
        return {
            "executable": self.executable,
            "mandatory_flags": list(self.mandatory_flags),
            "arguments": list(self.arguments),
            "action_fingerprint": self.action_fingerprint,
            "request_id": self.request_id,
            "is_valid": self.is_valid,
            "rejection_reason": self.rejection_reason,
        }


class PowerShellExecutionBoundary:
    """Frontera de seguridad para validación e invocaciones de PowerShell (Subetapa 07.3)."""

    def __init__(self) -> None:
        settings = AppSettings()
        self.allowed_executables: set[str] = {exe.lower() for exe in settings.POWERSHELL_ALLOWED_EXECUTABLES}
        self.force_no_profile: bool = settings.POWERSHELL_FORCE_NO_PROFILE
        self.force_non_interactive: bool = settings.POWERSHELL_FORCE_NON_INTERACTIVE
        self.max_arguments: int = settings.POWERSHELL_MAX_ARGUMENTS
        self.max_command_length: int = settings.POWERSHELL_MAX_COMMAND_LENGTH

        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def calculate_fingerprint(self, executable: str, arguments: tuple[str, ...], request_id: str) -> str:
        """Calcula el hash canónico SHA-256 para binding de autorización criptográfica."""
        raw_payload = f"windows.shell:powershell:{executable.lower()}:{','.join(arguments)}:{request_id}"
        return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()

    def validate_and_build(
        self,
        executable: str,
        arguments: list[str] | tuple[str, ...],
        request_id: str,
    ) -> PowerShellInvocation:
        """Valida los parámetros de invocación de PowerShell y construye la representación segura."""
        args_tuple = tuple(arguments)
        self.event_bus.publish("powershell:boundary_evaluated", {"request_id": request_id, "executable": executable})

        exec_base = executable.split("\\")[-1].split("/")[-1].lower()
        if exec_base not in self.allowed_executables:
            reason = f"Ejecutable de PowerShell no autorizado por política: '{executable}'."
            return self._reject_invocation(executable, args_tuple, request_id, reason)

        joined_args = " ".join(args_tuple)
        if len(joined_args) > self.max_command_length:
            reason = f"Longitud de comando PowerShell excedida ({len(joined_args)} > {self.max_command_length})."
            return self._reject_invocation(executable, args_tuple, request_id, reason)

        # 1. Verificación de banderas prohibidas (-EncodedCommand, -ExecutionPolicy Bypass, etc.)
        if FORBIDDEN_POWERSHELL_FLAGS.search(joined_args):
            reason = "Intento de bypass o bandera prohibida detectada en argumentos de PowerShell."
            return self._reject_invocation(executable, args_tuple, request_id, reason)

        # 2. Detección de obfuscación y llamadas dinámicas (Invoke-Expression, iex, Start-Process, etc.)
        if POWERSHELL_OBFUSCATION_PATTERNS.search(joined_args):
            reason = "Detección de ejecucion dinámica u obfuscación no autorizada en PowerShell."
            return self._reject_invocation(executable, args_tuple, request_id, reason)

        # 3. Construcción de flags obligatorias imponibles (-NoProfile, -NonInteractive)
        mandatory_flags: list[str] = []
        if self.force_no_profile:
            mandatory_flags.append("-NoProfile")
        if self.force_non_interactive:
            mandatory_flags.append("-NonInteractive")

        fingerprint = self.calculate_fingerprint(executable, args_tuple, request_id)

        inv = PowerShellInvocation(
            executable=executable,
            mandatory_flags=tuple(mandatory_flags),
            arguments=args_tuple,
            action_fingerprint=fingerprint,
            request_id=request_id,
            is_valid=True,
            rejection_reason=None,
        )

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.POWERSHELL_BOUNDARY_ALLOWED,
                request_id=request_id,
                tool_name="windows.shell",
                operation="powershell_boundary_validate",
                reason="Invocación de PowerShell validada y construida exitosamente.",
                metadata=inv.to_dict(),
            )
        )
        self.event_bus.publish("powershell:boundary_allowed", inv.to_dict())
        return inv

    def _reject_invocation(
        self,
        executable: str,
        arguments: tuple[str, ...],
        request_id: str,
        reason: str,
    ) -> PowerShellInvocation:
        """Produce una invocación rechazada de PowerShell."""
        fingerprint = self.calculate_fingerprint(executable, arguments, request_id)
        inv = PowerShellInvocation(
            executable=executable,
            mandatory_flags=(),
            arguments=arguments,
            action_fingerprint=fingerprint,
            request_id=request_id,
            is_valid=False,
            rejection_reason=reason,
        )

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.POWERSHELL_BOUNDARY_REJECTED,
                request_id=request_id,
                tool_name="windows.shell",
                operation="powershell_boundary_validate",
                reason=reason,
                metadata=inv.to_dict(),
            )
        )
        self.event_bus.publish("powershell:boundary_rejected", inv.to_dict())
        return inv
