"""Parser seguro de comandos y tokenizador determinista (SecureCommandParser - Subetapa 07.2).

GARANTÍA ABSOLUTA DE CERO EJECUCIÓN EN 07.2:
Este módulo realiza ÚNICAMENTE análisis léxico y estructuración de cadenas de texto.
NO utiliza subprocess, asyncio.create_subprocess_exec, os.system, os.popen, shell=True,
cmd.exe, powershell.exe, eval ni exec.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.command_parser")

# Patrón estricto de operadores de shell prohibidos
SHELL_OPERATORS_PATTERN = re.compile(
    r"(&&|\|\||&|\||;|\$|\(|\)|>>|>|<<|<|`|\$\{)",
    re.IGNORECASE,
)


class CommandParseError(MCPError):
    """Error base de parseo de comandos."""

    pass


class ShellOperatorRejectedError(CommandParseError):
    """Rechazo por detección de operadores o metacarácteres de shell."""

    pass


class NullByteRejectedError(CommandParseError):
    """Rechazo por caracteres nulos en el comando."""

    pass


class NewlineInjectionError(CommandParseError):
    """Rechazo por inyección de saltos de línea (CR/LF) o comandos compuestos."""

    pass


class UnterminatedQuoteError(CommandParseError):
    """Rechazo por comillas sin cerrar."""

    pass


class ArgumentValidationError(CommandParseError):
    """Rechazo por violaciones de límites o formato de argumentos."""

    pass


@dataclass(frozen=True)
class StructuredCommand:
    """Estructura inmutable resultado del parseo determinista de un comando."""

    executable: str
    arguments: tuple[str, ...]
    raw_input_hash: str
    argument_count: int
    is_valid: bool
    normalized_executable: str
    parser_version: str = "1.0.0"
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convierte la estructura a un diccionario estructurado."""
        return {
            "executable": self.executable,
            "arguments": list(self.arguments),
            "raw_input_hash": self.raw_input_hash,
            "argument_count": self.argument_count,
            "is_valid": self.is_valid,
            "normalized_executable": self.normalized_executable,
            "parser_version": self.parser_version,
            "rejection_reason": self.rejection_reason,
        }


class CommandLexer:
    """Tokenizador léxico determinista para cadenas de comandos de consola."""

    @staticmethod
    def tokenize(raw_input: str) -> tuple[str, tuple[str, ...]]:
        """Tokeniza la cadena raw_input en (executable, arguments).

        Soporta comillas dobles y simples. Rechaza operadores shell, nulos y newlines.
        """
        if not raw_input or not raw_input.strip():
            raise ArgumentValidationError("La cadena de comando está vacía.")

        # 1. Detección de caracteres nulos
        if "\x00" in raw_input:
            raise NullByteRejectedError("Detección de caracteres nulos (null bytes).")

        # 2. Detección de saltos de línea (multilínea / CRLF injection)
        if "\r" in raw_input or "\n" in raw_input:
            raise NewlineInjectionError("Detección de saltos de línea (multiline command injection).")

        # 3. Detección de operadores peligrosos de shell
        if SHELL_OPERATORS_PATTERN.search(raw_input):
            raise ShellOperatorRejectedError("Detección de operadores o metacarácteres peligrosos de shell.")

        tokens: list[str] = []
        current_token: list[str] = []
        in_quote: str | None = None
        i = 0
        n = len(raw_input)

        while i < n:
            char = raw_input[i]

            if in_quote:
                if char == in_quote:
                    in_quote = None
                else:
                    current_token.append(char)
            else:
                if char in ('"', "'"):
                    in_quote = char
                elif char.isspace():
                    if current_token:
                        tokens.append("".join(current_token))
                        current_token = []
                else:
                    current_token.append(char)
            i += 1

        if in_quote:
            raise UnterminatedQuoteError(f"Comilla sin cerrar detectada ({in_quote}).")

        if current_token:
            tokens.append("".join(current_token))

        if not tokens:
            raise ArgumentValidationError("No se encontraron tokens válidos en la entrada.")

        executable = tokens[0]
        arguments = tuple(tokens[1:])
        return executable, arguments


class CommandArgumentValidator:
    """Validador estricto de límites y formato de argumentos."""

    def __init__(self) -> None:
        settings = AppSettings()
        self.max_total_length: int = settings.COMMAND_MAX_TOTAL_LENGTH
        self.max_arguments: int = settings.COMMAND_MAX_ARGUMENTS
        self.max_argument_length: int = settings.COMMAND_MAX_ARGUMENT_LENGTH

    def validate(self, raw_input: str, executable: str, arguments: tuple[str, ...]) -> None:
        """Valida los límites del comando tokenizado."""
        if len(raw_input) > self.max_total_length:
            raise ArgumentValidationError(
                f"Longitud total de entrada excedida ({len(raw_input)} > {self.max_total_length})."
            )

        if len(arguments) > self.max_arguments:
            raise ArgumentValidationError(
                f"Cantidad máxima de argumentos excedida ({len(arguments)} > {self.max_arguments})."
            )

        for arg in arguments:
            if len(arg) > self.max_argument_length:
                raise ArgumentValidationError(
                    f"Longitud de argumento excedida ({len(arg)} > {self.max_argument_length})."
                )

            # Control de caracteres de control Unicode no imprimibles
            for c in arg:
                category = unicodedata.category(c)
                if category.startswith("C") and c not in ("\t",):
                    raise ArgumentValidationError(f"Carácter de control no permitido detectado: {hex(ord(c))}.")


class SecureCommandParser:
    """Parser seguro de comandos de consola (Subetapa 07.2 - TEXT ANALYSIS ONLY)."""

    def __init__(self, validator: CommandArgumentValidator | None = None) -> None:
        self.validator = validator or CommandArgumentValidator()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def parse(self, raw_input: str) -> StructuredCommand:
        """Parsea una cadena de comando no confiable y retorna un StructuredCommand inmutable."""
        self.event_bus.publish("command:parse_started", {"raw_input_length": len(raw_input) if raw_input else 0})

        raw_str = raw_input.strip() if raw_input else ""
        raw_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

        try:
            executable, arguments = CommandLexer.tokenize(raw_str)
            self.validator.validate(raw_str, executable, arguments)

            # Normalizar nombre base del ejecutable manteniendo la ruta original
            normalized_exec = executable.split("\\")[-1].split("/")[-1].lower()

            cmd = StructuredCommand(
                executable=executable,
                arguments=arguments,
                raw_input_hash=raw_hash,
                argument_count=len(arguments),
                is_valid=True,
                normalized_executable=normalized_exec,
                rejection_reason=None,
            )

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.COMMAND_PARSE_SUCCEEDED,
                    tool_name="windows.shell",
                    operation="parse_command",
                    reason="Parseo léxico estructurado exitoso.",
                    metadata=cmd.to_dict(),
                )
            )
            self.event_bus.publish("command:parse_completed", cmd.to_dict())
            return cmd

        except CommandParseError as e:
            reason = str(e)
            logger.warning(f"[COMMAND PARSE REJECTED] {reason}")

            cmd_rejected = StructuredCommand(
                executable=raw_str.split()[0] if raw_str.split() else "",
                arguments=(),
                raw_input_hash=raw_hash,
                argument_count=0,
                is_valid=False,
                normalized_executable="",
                rejection_reason=reason,
            )

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.COMMAND_PARSE_REJECTED,
                    tool_name="windows.shell",
                    operation="parse_command",
                    reason=reason,
                    metadata=cmd_rejected.to_dict(),
                )
            )
            self.event_bus.publish("command:parse_rejected", cmd_rejected.to_dict())
            return cmd_rejected
