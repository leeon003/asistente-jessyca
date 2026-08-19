"""Modelos de Security Events para el canal SECURITY EVENT (Etapa 17.0).

Un SecurityEvent es emitido cuando el sistema detecta una violación o intento
de violación de sus políticas de seguridad. Es separado del AuditEvent:

  AuditEvent   → responde "qué decidió el sistema" (compliance log)
  SecurityEvent → responde "qué violación ocurrió" (SIEM / alertas)

PRIVACIDAD: ningún campo puede contener passwords, tokens, secrets, clipboard
crudo, screenshots, contenido de audio, ni parámetros sin sanitizar.
Solo metadata de control: nombres, IDs de correlación, descripciones sanitizadas.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class SecurityEventType(StrEnum):
    """Tipos formales de security events."""

    # Policy violations
    SECURITY_POLICY_VIOLATION = "SECURITY_POLICY_VIOLATION"
    PRIVILEGE_ESCALATION_ATTEMPT = "PRIVILEGE_ESCALATION_ATTEMPT"
    PROMPT_INJECTION_DETECTED = "PROMPT_INJECTION_DETECTED"

    # Plugin
    PLUGIN_CAPABILITY_VIOLATION = "PLUGIN_CAPABILITY_VIOLATION"
    PLUGIN_SANDBOX_BREACH_ATTEMPT = "PLUGIN_SANDBOX_BREACH_ATTEMPT"
    PLUGIN_TIMEOUT_EXCEEDED = "PLUGIN_TIMEOUT_EXCEEDED"

    # Filesystem / Registry / Service
    PATH_TRAVERSAL_ATTEMPT = "PATH_TRAVERSAL_ATTEMPT"
    REGISTRY_ALLOWLIST_VIOLATION = "REGISTRY_ALLOWLIST_VIOLATION"
    PROTECTED_SERVICE_ACCESS_ATTEMPT = "PROTECTED_SERVICE_ACCESS_ATTEMPT"
    FORBIDDEN_SOFTWARE_INSTALL_ATTEMPT = "FORBIDDEN_SOFTWARE_INSTALL_ATTEMPT"

    # Confirmation / Pipeline
    CONFIRMATION_REPLAY_ATTACK = "CONFIRMATION_REPLAY_ATTACK"
    CONFIRMATION_FINGERPRINT_MISMATCH = "CONFIRMATION_FINGERPRINT_MISMATCH"
    PIPELINE_BYPASS_ATTEMPT = "PIPELINE_BYPASS_ATTEMPT"

    # Emergency Stop
    EMERGENCY_STOP_ACTIVATED = "EMERGENCY_STOP_ACTIVATED"
    EMERGENCY_STOP_RESET = "EMERGENCY_STOP_RESET"

    # Privacy / Data
    SENSITIVE_DATA_IN_CLIPBOARD = "SENSITIVE_DATA_IN_CLIPBOARD"
    MEMORY_AUTHORITY_ESCALATION_ATTEMPT = "MEMORY_AUTHORITY_ESCALATION_ATTEMPT"
    CREDENTIALS_DETECTED_ON_SCREEN = "CREDENTIALS_DETECTED_ON_SCREEN"

    # Browser
    BROWSER_BLOCKED_DOMAIN_ATTEMPT = "BROWSER_BLOCKED_DOMAIN_ATTEMPT"

    # Authority
    UNTRUSTED_SOURCE_AUTHORITY_CLAIM = "UNTRUSTED_SOURCE_AUTHORITY_CLAIM"
    SCHEDULER_AUTHORITY_ESCALATION = "SCHEDULER_AUTHORITY_ESCALATION"
    WORKFLOW_AUTHORITY_ESCALATION = "WORKFLOW_AUTHORITY_ESCALATION"

    # Generic
    SECURITY_BOUNDARY_VIOLATION = "SECURITY_BOUNDARY_VIOLATION"
    UNKNOWN_SECURITY_ANOMALY = "UNKNOWN_SECURITY_ANOMALY"


class SecuritySeverity(StrEnum):
    """Severidad de un SecurityEvent."""

    CRITICAL = "CRITICAL"   # Privilege escalation, pipeline bypass, confirmation replay
    HIGH = "HIGH"           # Policy violations, forbidden installs, sandbox breach
    MEDIUM = "MEDIUM"       # Allowlist violations, path traversal, blocked domain
    LOW = "LOW"             # Warnings, inusuales pero no bloqueados
    INFO = "INFO"           # Normal boundary checks (para auditoría de info)


@dataclass(frozen=True)
class SecurityEvent:
    """Evento de seguridad inmutable, sanitizado y hasheado.

    Emitido por SecurityEventEmitter cuando ocurre una violación de política.
    NUNCA debe contener datos sensibles en ningún campo.
    """

    event_type: SecurityEventType | str
    severity: SecuritySeverity | str
    component: str                  # "boundary.registry", "plugin.sandbox", "autonomy", etc.
    description: str                # Descripción sanitizada de la violación
    blocked: bool = True            # ¿La acción fue bloqueada?
    correlation_id: str = ""
    session_id: str = ""
    action_id: str | None = None
    task_id: str | None = None
    plugin_id: str | None = None
    tool_name: str = ""
    operation: str = ""
    violated_policy: str = ""       # ID o nombre de la política violada
    risk_level: str = ""            # READ_ONLY, SAFE, WARNING, DANGEROUS, CRITICAL
    metadata: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_hash: str = ""

    def __post_init__(self) -> None:
        # Calcular hash si no está definido
        if not self.event_hash:
            d = self._to_raw_dict()
            h = hashlib.sha256(
                json.dumps(d, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            object.__setattr__(self, "event_hash", h)

    def _to_raw_dict(self) -> dict[str, Any]:
        ev_type = getattr(self.event_type, "value", str(self.event_type))
        sev = getattr(self.severity, "value", str(self.severity))
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else str(self.timestamp),
            "event_type": ev_type,
            "severity": sev,
            "component": self.component,
            "description": self.description,
            "blocked": self.blocked,
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "action_id": self.action_id,
            "task_id": self.task_id,
            "plugin_id": self.plugin_id,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "violated_policy": self.violated_policy,
            "risk_level": self.risk_level,
            "metadata": self.metadata,
        }

    def to_dict(self) -> dict[str, Any]:
        """Representación serializable completa, lista para JSONL export."""
        d = self._to_raw_dict()
        d["event_hash"] = self.event_hash
        return d
