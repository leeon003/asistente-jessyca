"""Frontera de seguridad específica para ejecuciones en entornos CMD (CMDExecutionBoundary - Subetapa 07.3).

GARANTÍA ABSOLUTA DE CERO EJECUCIÓN REAL EN 07.3:
Este módulo realiza ÚNICAMENTE validación de seguridad, bloqueo de flags (/c, /k, /s)
y construcción de la estructura inmutable CMDInvocation.
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
from core.logger import get_logger
from core.powershell_boundary import ShellBoundaryError

logger = get_logger("jessyca.core.cmd_boundary")

# Banderas de CMD prohibidas expresamente (/c, /k, /s)
FORBIDDEN_CMD_FLAGS = re.compile(
    r"(^|\s+)(/c|/k|/s)(\s+|$)",
    re.IGNORECASE,
)

# Metacarácteres y operadores prohibidos en CMD
FORBIDDEN_CMD_OPERATORS = re.compile(
    r"(&&|\|\||&|\||;|>|>>|<|<<|\^|%|!)",
    re.IGNORECASE,
)

# Patrones de anidación no autorizada (nesting)
FORBIDDEN_NESTED_SHELLS = re.compile(
    r"(powershell\.exe|pwsh\.exe|cmd\.exe|powershell|pwsh|cmd)",
    re.IGNORECASE,
)


class CMDBypassRejectedError(ShellBoundaryError):
    """Error emitido al detectar banderas de ejecución arbitraria (/c, /k, /s) o inyección en CMD."""

    pass


@dataclass(frozen=True)
class CMDInvocation:
    """Estructura inmutable de la representación segura de invocación CMD."""

    executable: str
    arguments: tuple[str, ...]
    action_fingerprint: str
    request_id: str
    is_valid: bool
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convierte la invocación a un diccionario estructurado."""
        return {
            "executable": self.executable,
            "arguments": list(self.arguments),
            "action_fingerprint": self.action_fingerprint,
            "request_id": self.request_id,
            "is_valid": self.is_valid,
            "rejection_reason": self.rejection_reason,
        }


class CMDExecutionBoundary:
    """Frontera de seguridad para validación e invocaciones de CMD (Subetapa 07.3)."""

    def __init__(self) -> None:
        settings = AppSettings()
        self.allowed_executables: set[str] = {exe.lower() for exe in settings.CMD_ALLOWED_EXECUTABLES}
        self.max_arguments: int = settings.CMD_MAX_ARGUMENTS
        self.max_command_length: int = settings.CMD_MAX_COMMAND_LENGTH

        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def calculate_fingerprint(self, executable: str, arguments: tuple[str, ...], request_id: str) -> str:
        """Calcula el hash canónico SHA-256 para binding de autorización criptográfica."""
        raw_payload = f"windows.shell:cmd:{executable.lower()}:{','.join(arguments)}:{request_id}"
        return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()

    def validate_and_build(
        self,
        executable: str,
        arguments: list[str] | tuple[str, ...],
        request_id: str,
    ) -> CMDInvocation:
        """Valida los parámetros de invocación de CMD y construye la representación segura."""
        args_tuple = tuple(arguments)
        self.event_bus.publish("cmd:boundary_evaluated", {"request_id": request_id, "executable": executable})

        exec_base = executable.split("\\")[-1].split("/")[-1].lower()
        if exec_base not in self.allowed_executables:
            reason = f"Ejecutable de CMD no autorizado por política: '{executable}'."
            return self._reject_invocation(executable, args_tuple, request_id, reason)

        joined_args = " ".join(args_tuple)
        if len(joined_args) > self.max_command_length:
            reason = f"Longitud de comando CMD excedida ({len(joined_args)} > {self.max_command_length})."
            return self._reject_invocation(executable, args_tuple, request_id, reason)

        # 1. Verificación de banderas prohibidas de ejecución arbitraria (/c, /k, /s)
        if FORBIDDEN_CMD_FLAGS.search(joined_args):
            reason = "Rechazado: Las banderas /c, /k y /s no están permitidas para delegación arbitraria en CMD."
            return self._reject_invocation(executable, args_tuple, request_id, reason)

        # 2. Detección de operadores y metacarácteres de CMD (&, &&, |, ||, ;, >, <, ^, %, !)
        if FORBIDDEN_CMD_OPERATORS.search(joined_args):
            reason = "Rechazado: Detección de operadores o metacarácteres peligrosos de CMD."
            return self._reject_invocation(executable, args_tuple, request_id, reason)

        # 3. Detección de anidación no autorizada de proyectiles de shell (nested shell calls)
        for arg in args_tuple:
            if FORBIDDEN_NESTED_SHELLS.search(arg):
                reason = f"Rechazado: Anidación de intérprete de shell no autorizada detectada ('{arg}')."
                return self._reject_invocation(executable, args_tuple, request_id, reason)

        fingerprint = self.calculate_fingerprint(executable, args_tuple, request_id)

        inv = CMDInvocation(
            executable=executable,
            arguments=args_tuple,
            action_fingerprint=fingerprint,
            request_id=request_id,
            is_valid=True,
            rejection_reason=None,
        )

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.CMD_BOUNDARY_ALLOWED,
                request_id=request_id,
                tool_name="windows.shell",
                operation="cmd_boundary_validate",
                reason="Invocación de CMD validada y construida exitosamente.",
                metadata=inv.to_dict(),
            )
        )
        self.event_bus.publish("cmd:boundary_allowed", inv.to_dict())
        return inv

    def _reject_invocation(
        self,
        executable: str,
        arguments: tuple[str, ...],
        request_id: str,
        reason: str,
    ) -> CMDInvocation:
        """Produce una invocación rechazada de CMD."""
        fingerprint = self.calculate_fingerprint(executable, arguments, request_id)
        inv = CMDInvocation(
            executable=executable,
            arguments=arguments,
            action_fingerprint=fingerprint,
            request_id=request_id,
            is_valid=False,
            rejection_reason=reason,
        )

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.CMD_BOUNDARY_REJECTED,
                request_id=request_id,
                tool_name="windows.shell",
                operation="cmd_boundary_validate",
                reason=reason,
                metadata=inv.to_dict(),
            )
        )
        self.event_bus.publish("cmd:boundary_rejected", inv.to_dict())
        return inv
