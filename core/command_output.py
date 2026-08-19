"""Sanitizador y redactor seguro de salida de comandos (CommandOutputSanitizer - Subetapa 07.5).

GARANTÍA ABSOLUTA DE SEGURIDAD EN 07.5:
El output crudo (RAW STDOUT / STDERR) NUNCA abandona la frontera interna de ejecución.
No llega al MCP Client, ni al AuditLogger, ni al EventBus, ni a los registros.
Toda salida pasa obligatoriamente por SecretRedactor, eliminación de ANSI,
normalización de encoding y límite de tamaño.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.command_output")

# Regex para eliminación de secuencias de escape ANSI
ANSI_ESCAPE_PATTERN = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])",
    re.IGNORECASE,
)

# Patrones de secretos compilados para redacción determinista
SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # 1. Private Keys (RSA, EC, OpenSSH, PGP)
    (
        re.compile(
            r"-----BEGIN\s+(?:RSA|EC|OPENSSH|DSA|PGP)?\s*PRIVATE\s+KEY-----[\s\S]*?-----END\s+(?:RSA|EC|OPENSSH|DSA|PGP)?\s*PRIVATE\s+KEY-----",
            re.IGNORECASE,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # 2. Bearer Tokens & Authorization Headers
    (
        re.compile(r"(Authorization\s*:\s*Bearer\s+)[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE),
        r"\1[REDACTED_BEARER_TOKEN]",
    ),
    (
        re.compile(r"(Bearer\s+)[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE),
        r"\1[REDACTED_BEARER_TOKEN]",
    ),
    # 3. JWT Tokens (eyJ...)
    (
        re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", re.IGNORECASE),
        "[REDACTED_JWT_TOKEN]",
    ),
    # 4. Connection Strings con credenciales (Password=..., mongodb://..., postgresql://...)
    (
        re.compile(r"(Password|pwd|passwd|UserPassword)\s*=\s*[^;'\"]+", re.IGNORECASE),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(r"(mongodb|postgresql|mysql|redis|amqp|mssql):\/\/([^:\s]+):([^@\s]+)@", re.IGNORECASE),
        r"\1://\2:[REDACTED]@",
    ),
    # 5. Claves genericas / Tokens / Contraseñas en asignaciones key=value o key: value
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|pass|api_key|apikey|api-key|api-token|access_token|refresh_token|id_token|client_secret|client-secret|clientSecret|secret|userpassword|user_password|auth_token)\b\s*([=:]\s*)([\"']?)([^\"'\s\r\n;,]+)([\"']?)",
            re.IGNORECASE,
        ),
        r"\1\2\3[REDACTED]\5",
    ),
    # 6. JSON Key-Value Secret Patterns ("password": "value")
    (
        re.compile(
            r'(?i)"(password|passwd|pwd|pass|api_key|apikey|api_token|access_token|refresh_token|client_secret|secret|token)"\s*:\s*"([^"]+)"',
            re.IGNORECASE,
        ),
        r'"\1": "[REDACTED]"',
    ),
    # 7. AWS Access Key ID (AKIA...)
    (
        re.compile(r"\bAKIA[0-9A-Z]{16}\b", re.IGNORECASE),
        "[REDACTED_AWS_KEY]",
    ),
    # 8. FIX MEDIUM-001 (Etapa 17.0): password/pwd seguido de dígitos como valor standalone
    # Captura: "password123", "pwd456", "pass789" (valores de contraseña sin key=)
    (
        re.compile(r"\b(password|passwd|pwd|pass)\d+\b", re.IGNORECASE),
        "[REDACTED_PASSWORD]",
    ),
    # 9. Valores de token/key en texto libre (token seguido de valor alfanumérico largo)
    (
        re.compile(r"\b(token|key|apikey|api_key)\s*[=:]\s*([A-Za-z0-9\-_]{16,})", re.IGNORECASE),
        r"\1=[REDACTED]",
    ),
    # 10. Hashes hexadecimales largos (32+ chars) — posibles API keys o tokens en texto libre
    (
        re.compile(r"\b[0-9a-f]{32,64}\b", re.IGNORECASE),
        "[REDACTED_HEX_SECRET]",
    ),
]



class CommandOutputError(MCPError):
    """Error base de sanitización de salida de comandos."""

    pass


class RedactionFailedError(CommandOutputError):
    """Error emitido en caso de fallo crítico en el proceso de redacción de secretos."""

    pass


@dataclass(frozen=True)
class SanitizedCommandOutput:
    """Modelo inmutable que representa el resultado sanitizado y seguro de la salida de un comando."""

    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    stdout_original_size: int
    stderr_original_size: int
    redactions_count: int
    total_output_size: int
    is_sanitized: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convierte la salida sanitizada a un diccionario estructurado (sin exponer datos crudos)."""
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "stdout_original_size": self.stdout_original_size,
            "stderr_original_size": self.stderr_original_size,
            "redactions_count": self.redactions_count,
            "total_output_size": self.total_output_size,
            "is_sanitized": self.is_sanitized,
        }


class SecretRedactor:
    """Redactor determinista de secretos y credenciales en texto de consola."""

    @staticmethod
    def redact(text: str) -> tuple[str, int]:
        """Sanitiza y redacta patrones de secretos en el texto recibido.

        Retorna (texto_redactado, cantidad_de_redacciones).
        GARANTÍA FAIL-SAFE: En caso de excepción, devuelve ([OUTPUT_REDACTION_FAILED], 1).
        """
        if not text:
            return "", 0

        try:
            redacted_text = text
            total_redactions = 0

            for pattern, replacement in SECRET_PATTERNS:
                new_text, count = pattern.subn(replacement, redacted_text)
                if count > 0:
                    total_redactions += count
                    redacted_text = new_text

            return redacted_text, total_redactions
        except Exception as e:
            logger.error(f"[SECRET REDACTOR FAIL-SAFE] Fallo crítico durante redacción de secretos: {e}")
            return "[OUTPUT_REDACTION_FAILED]", 1


class CommandOutputSanitizer:
    """Sanitizador y limitador seguro de salida de comandos de consola (Subetapa 07.5)."""

    def __init__(self) -> None:
        from config.settings import AppSettings
        settings = AppSettings()

        self.max_output_size: int = settings.COMMAND_MAX_OUTPUT_SIZE
        self.max_stdout_size: int = settings.COMMAND_MAX_STDOUT_SIZE
        self.max_stderr_size: int = settings.COMMAND_MAX_STDERR_SIZE
        self.redaction_enabled: bool = settings.COMMAND_OUTPUT_REDACTION_ENABLED
        self.ansi_sanitization_enabled: bool = settings.COMMAND_ANSI_SANITIZATION_ENABLED

        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def strip_ansi(self, text: str) -> str:
        """Elimina secuencias de escape ANSI para prevenir manipulación visual del terminal."""
        if not text or not self.ansi_sanitization_enabled:
            return text
        return ANSI_ESCAPE_PATTERN.sub("", text)

    def normalize_utf8(self, text: str | bytes | None) -> str:
        """Normaliza la codificación a UTF-8 válido reemplazando bytes o caracteres corruptos."""
        if text is None:
            return ""

        if isinstance(text, bytes):
            return text.decode("utf-8", errors="replace")

        # Asegurar codificación limpia de caracteres no imprimibles o malformados
        return text.encode("utf-8", errors="replace").decode("utf-8")

    def sanitize(
        self,
        raw_stdout: str | bytes | None,
        raw_stderr: str | bytes | None,
        request_id: str | None = None,
    ) -> SanitizedCommandOutput:
        """Procesa, redacta y acota el stdout y stderr crudo produciendo SanitizedCommandOutput inmutable."""
        req_id = request_id or "unknown-request"

        # 1. Normalización de codificación UTF-8
        clean_stdout = self.normalize_utf8(raw_stdout)
        clean_stderr = self.normalize_utf8(raw_stderr)

        stdout_orig_size = len(clean_stdout.encode("utf-8"))
        stderr_orig_size = len(clean_stderr.encode("utf-8"))

        # 2. Eliminación de secuencias de escape ANSI
        clean_stdout = self.strip_ansi(clean_stdout)
        clean_stderr = self.strip_ansi(clean_stderr)

        # 3. Redacción de secretos mediante SecretRedactor (antes de truncar para evitar cortar secretos)
        stdout_redactions = 0
        stderr_redactions = 0

        if self.redaction_enabled:
            clean_stdout, stdout_redactions = SecretRedactor.redact(clean_stdout)
            clean_stderr, stderr_redactions = SecretRedactor.redact(clean_stderr)

        total_redactions = stdout_redactions + stderr_redactions

        # 4. Truncamiento seguro por límites de tamaño
        stdout_bytes = clean_stdout.encode("utf-8")
        stderr_bytes = clean_stderr.encode("utf-8")

        stdout_truncated = False
        stderr_truncated = False

        if len(stdout_bytes) > self.max_stdout_size:
            clean_stdout = stdout_bytes[: self.max_stdout_size].decode("utf-8", errors="ignore") + "\n[STDOUT_TRUNCATED]"
            stdout_truncated = True

        if len(stderr_bytes) > self.max_stderr_size:
            clean_stderr = stderr_bytes[: self.max_stderr_size].decode("utf-8", errors="ignore") + "\n[STDERR_TRUNCATED]"
            stderr_truncated = True

        total_size = len(clean_stdout.encode("utf-8")) + len(clean_stderr.encode("utf-8"))

        sanitized_output = SanitizedCommandOutput(
            stdout=clean_stdout,
            stderr=clean_stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            stdout_original_size=stdout_orig_size,
            stderr_original_size=stderr_orig_size,
            redactions_count=total_redactions,
            total_output_size=total_size,
            is_sanitized=True,
        )

        # 5. Registro de auditoría y eventos informativos (ÚNICAMENTE METADATOS, CERO RAW OUTPUT)
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.COMMAND_OUTPUT_SANITIZED,
                request_id=req_id,
                tool_name="windows.shell",
                operation="sanitize_output",
                reason="Salida de comando sanitizada y redactada exitosamente.",
                metadata={
                    "redactions_count": total_redactions,
                    "stdout_size": len(clean_stdout),
                    "stderr_size": len(clean_stderr),
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                },
            )
        )

        self.event_bus.publish(
            "command:output_sanitized",
            {
                "request_id": req_id,
                "redactions_count": total_redactions,
                "total_output_size": total_size,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
            },
        )

        return sanitized_output
