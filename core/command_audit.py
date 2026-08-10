"""Gestor de auditoría unificada y verificación de firmas criptográficas para comandos (CommandAuditManager - Subetapa 07.6).

GARANTÍA ABSOLUTA DE SEGURIDAD EN 07.6:
1. Verifica el binding criptográfico SHA-256 (action_fingerprint) de la evidencia de autorización contra alteración/tampering de ejecutable, argumentos, tipo de shell o request_id.
2. Emite eventos de auditoría estructurados y limpios (CERO RAW OUTPUT, CERO SECRETOS).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.exceptions import MCPError
from core.logger import get_logger
from core.permission_manager import PermissionDecision
from core.risk_engine import SecurityLevel
from server.evidence import AuthorizationEvidence

logger = get_logger("jessyca.core.command_audit")


class CommandAuditError(MCPError):
    """Error base del gestor de auditoría de comandos."""

    pass


class TamperingDetectedError(CommandAuditError):
    """Error emitido cuando se detecta alteración post-autorización en los parámetros o la firma del comando."""

    pass


@dataclass(frozen=True)
class CommandAuditEvent:
    """Modelo inmutable de evento de auditoría de comando sanitizado y seguro."""

    request_id: str
    tool_name: str
    operation: str
    shell_type: str
    normalized_executable: str
    action_fingerprint: str
    risk_level: SecurityLevel
    decision: PermissionDecision
    duration_ms: float
    exit_code: int | None
    timeout_occurred: bool
    output_sizes: dict[str, int]
    redactions_count: int
    truncation_status: bool

    def to_dict(self) -> dict[str, Any]:
        """Convierte el evento de auditoría a un diccionario estructurado (sin secrets ni output crudo)."""
        return {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "shell_type": self.shell_type,
            "normalized_executable": self.normalized_executable,
            "action_fingerprint": self.action_fingerprint,
            "risk_level": self.risk_level.value,
            "decision": self.decision.value,
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
            "timeout_occurred": self.timeout_occurred,
            "output_sizes": self.output_sizes,
            "redactions_count": self.redactions_count,
            "truncation_status": self.truncation_status,
        }


class CommandAuditManager:
    """Gestor centralizado de auditoría y verificación de integridad criptográfica para Etapa 07."""

    def __init__(self) -> None:
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def calculate_action_fingerprint(
        self,
        tool_name: str,
        operation: str,
        shell_type: str,
        executable: str,
        arguments: tuple[str, ...],
        request_id: str,
    ) -> str:
        """Calcula el hash canónico SHA-256 para verificación de binding criptográfico."""
        exec_norm = executable.split("\\")[-1].split("/")[-1].lower()
        args_joined = ",".join(arguments)
        raw_payload = f"{tool_name}:{operation}:{shell_type}:{exec_norm}:{args_joined}:{request_id}"
        return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()

    def verify_authorization_integrity(
        self,
        evidence: AuthorizationEvidence,
        expected_tool: str,
        expected_op: str,
        shell_type: str,
        executable: str,
        arguments: tuple[str, ...],
        request_id: str,
    ) -> bool:
        """Verifica que la evidencia de autorización no haya sido alterada tras su emisión (Anti-Tampering)."""
        if not evidence.is_valid:
            self._log_security_failure(request_id, expected_tool, expected_op, "Evidencia de autorización marcada como inválida.")
            return False

        if evidence.request_id != request_id:
            self._log_security_failure(request_id, expected_tool, expected_op, "Inconsistencia en request_id de la evidencia.")
            return False

        expected_fingerprint = self.calculate_action_fingerprint(
            expected_tool, expected_op, shell_type, executable, arguments, request_id
        )

        if evidence.action_fingerprint != expected_fingerprint:
            self._log_security_failure(
                request_id,
                expected_tool,
                expected_op,
                f"Detección de alteración post-autorización (Fingerprint Mismatch: '{evidence.action_fingerprint[:8]}' != '{expected_fingerprint[:8]}').",
            )
            return False

        return True

    def log_command_start(
        self,
        request_id: str,
        tool_name: str,
        operation: str,
        shell_type: str,
        executable: str,
    ) -> None:
        """Registra el evento de inicio de ciclo de auditoría de comando."""
        exec_norm = executable.split("\\")[-1].split("/")[-1].lower()
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.COMMAND_AUDIT_STARTED,
                request_id=request_id,
                tool_name=tool_name,
                operation=operation,
                reason=f"Inicio de auditoría de comando '{exec_norm}' en entorno '{shell_type}'.",
                metadata={"shell_type": shell_type, "executable": exec_norm},
            )
        )

    def log_command_completion(
        self,
        request_id: str,
        tool_name: str,
        operation: str,
        shell_type: str,
        executable: str,
        fingerprint: str,
        risk_level: SecurityLevel,
        decision: PermissionDecision,
        duration_ms: float,
        exit_code: int | None = 0,
        timeout: bool = False,
        output_sizes: dict[str, int] | None = None,
        redactions: int = 0,
        truncated: bool = False,
    ) -> CommandAuditEvent:
        """Registra la finalización de ciclo de auditoría de comando y emite los eventos correspondientes."""
        exec_norm = executable.split("\\")[-1].split("/")[-1].lower()
        sizes = output_sizes or {"stdout": 0, "stderr": 0}

        event = CommandAuditEvent(
            request_id=request_id,
            tool_name=tool_name,
            operation=operation,
            shell_type=shell_type,
            normalized_executable=exec_norm,
            action_fingerprint=fingerprint,
            risk_level=risk_level,
            decision=decision,
            duration_ms=duration_ms,
            exit_code=exit_code,
            timeout_occurred=timeout,
            output_sizes=sizes,
            redactions_count=redactions,
            truncation_status=truncated,
        )

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.COMMAND_AUDIT_COMPLETED,
                request_id=request_id,
                tool_name=tool_name,
                operation=operation,
                reason="Ciclo de auditoría de comando completado exitosamente.",
                metadata=event.to_dict(),
            )
        )

        self.event_bus.publish("command:audit_completed", event.to_dict())
        return event

    def _log_security_failure(self, request_id: str, tool_name: str, operation: str, reason: str) -> None:
        """Registra un fallo crítico de seguridad o intento de tampering."""
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.COMMAND_AUDIT_SECURITY_FAILURE,
                request_id=request_id,
                tool_name=tool_name,
                operation=operation,
                reason=reason,
                metadata={"security_failure": True},
            )
        )
        self.event_bus.publish("command:audit_security_failure", {"request_id": request_id, "reason": reason})
