"""Guardia de Seguridad y Blindaje contra Inyección de Instrucciones (proactive_security.py - Fase 44).

INVARIANTES ABSOLUTAS:
1. EXTERNAL EVENTS = UNTRUSTED DATA (Todo evento proveniente de navegador, documento, app o memoria es tratado como dato hostil).
2. ANTI-PROMPT INJECTION: Queda estrictamente prohibido que texto externo modifique las directivas del sistema o se auto-convierta en instrucción ejecutable.
3. PREVALENCIA DE AUTONOMY POLICY Y PARADA DE EMERGENCIA: Ninguna acción sensible se ejecuta sin pasar por RiskEngine y confirmación humana.
"""

from __future__ import annotations

import re
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.command_output import SecretRedactor
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger
from core.proactive.proactive_models import ProactiveEvent

logger = get_logger("jessyca.proactive.security")

# Patrones de inyección indirecta de instrucciones y secuestro de prompts
INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(previous|all|above|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+prompt\s*:", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(in\s+)?(developer\s+mode|dan|unrestricted)", re.IGNORECASE),
    re.compile(r"new\s+system\s+directive\s*:", re.IGNORECASE),
    re.compile(r"override\s+security\s+policy", re.IGNORECASE),
    re.compile(r"bypass\s+confirmation", re.IGNORECASE),
    re.compile(r"execute\s+(powershell|cmd|bash|sh)\s+command", re.IGNORECASE),
    re.compile(r"(format\s+[c-z]:|rmdir\s+/s|del\s+/f|sudo\s+rm)", re.IGNORECASE),
    re.compile(r"<\s*script[^>]*>", re.IGNORECASE),
    re.compile(r"<!--\s*#system", re.IGNORECASE),
)

# Caracteres de control prohibidos o peligrosos
PROHIBITED_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ProactiveSecurityGuard:
    """Guardia de seguridad especializado en sanitización, detección de inyecciones y validación de procedencia."""

    def __init__(
        self,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self.audit_logger = get_audit_logger()

    def inspect_and_sanitize(self, event: ProactiveEvent) -> tuple[bool, str | None, dict[str, Any]]:
        """Inspecciona un ProactiveEvent buscando anomalías de seguridad, caracteres nulos o inyección de prompts.

        Returns:
            (is_safe, failure_reason, security_metadata)
        """
        # 1. Comprobar Parada de Emergencia
        if self.emergency_stop.is_stopped():
            return False, "Parada de Emergencia activa. Operación bloqueada.", {"emergency_stop": True}

        # 2. Verificar caracteres de control o nulos en summary o payload
        raw_text = f"{event.summary} {str(event.payload)} {str(event.tool_parameters)}"
        if "\x00" in raw_text:
            self._log_security_threat(event, "Caracteres nulos (\x00) detectados en el evento.")
            return False, "Inyección de caracteres nulos detectada en el payload del evento.", {"null_byte_detected": True}

        if PROHIBITED_CHARS_PATTERN.search(raw_text):
            self._log_security_threat(event, "Caracteres de control prohibidos en el payload.")
            return False, "Caracteres de control prohibidos detectados en el evento.", {"control_chars_detected": True}

        # 3. Detección de Inyección de Prompts / Indirect Instruction Hijacking
        for pattern in INJECTION_PATTERNS:
            if pattern.search(raw_text):
                threat_msg = f"Patrón de inyección de instrucciones detectado: '{pattern.pattern}'"
                logger.warning(f"[SECURITY BLOCKED] {threat_msg} en evento '{event.event_id}'.")
                self._log_security_threat(event, threat_msg)
                return False, f"Ataque de inyección de instrucciones contenido: {threat_msg}", {"prompt_injection_detected": True}

        # 4. Sanitización de secretos
        sanitized_summary, secrets_found = SecretRedactor.redact(event.summary)

        return True, None, {
            "untrusted_data_verified": True,
            "secrets_redacted": secrets_found > 0,
            "sanitized_summary": sanitized_summary,
        }

    def _log_security_threat(self, event: ProactiveEvent, reason: str) -> None:
        """Registra un evento de auditoría de seguridad para trazabilidad forense."""
        try:
            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.SECURITY_ALERT,
                    user=f"proactive_source:{event.source}",
                    operation="proactive_event_security_check",
                    reason=reason,
                    metadata={
                        "event_id": event.event_id,
                        "source_type": str(event.source_type),
                        "summary_snippet": event.summary[:100],
                        "status": "BLOCKED",
                    },
                )
            )
        except Exception as ex:
            logger.error(f"Error al registrar violación de seguridad en auditoría: {ex}")
