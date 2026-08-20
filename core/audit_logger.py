"""Audit Logger estructurado y desacoplado para Jessyca Windows MCP (Subetapa 04.6).

Proporciona registro inmutable, sanitización recursiva de datos sensibles,
truncamiento explicito de texto extenso, concurrencia segura (threading.Lock),
formato JSON Lines (.jsonl), rotación por tamaño/tiempo y sinks desacoplados
(MemoryAuditSink, FileAuditSink).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from core.event_bus import EventBus, get_event_bus
from core.logger import get_logger
from core.security import PermissionAction, RiskLevel
from core.security_architecture import SecurityLevel
from core.types import JSONDict

logger = get_logger("jessyca.audit_logger")

SENSITIVE_KEY_PATTERNS: set[str] = {
    "password",
    "passwd",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "secret",
    "credential",
    "authorization",
    "cookie",
    "session_cookie",
    "private_key",
    "certificate_private_key",
    "auth_token",
}


class AuditEventType(StrEnum):
    """Tipos formales de eventos de auditoría de seguridad y ejecución."""

    CAPABILITY_RESOLVED = "CAPABILITY_RESOLVED"
    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    RISK_EVALUATED = "RISK_EVALUATED"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    PERMISSION_EVALUATED = "PERMISSION_EVALUATED"
    CONFIRMATION_REQUESTED = "CONFIRMATION_REQUESTED"
    CONFIRMATION_APPROVED = "CONFIRMATION_APPROVED"
    CONFIRMATION_REJECTED = "CONFIRMATION_REJECTED"
    CONFIRMATION_EXPIRED = "CONFIRMATION_EXPIRED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    EXECUTION_SUCCEEDED = "EXECUTION_SUCCEEDED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_DENIED = "EXECUTION_DENIED"
    EXECUTION_DISABLED = "EXECUTION_DISABLED"
    ERROR = "ERROR"
    SECURITY_ALERT = "SECURITY_ALERT"
    FILESYSTEM_PATH_VALIDATED = "FILESYSTEM_PATH_VALIDATED"
    FILESYSTEM_OPERATION_REQUESTED = "FILESYSTEM_OPERATION_REQUESTED"
    FILESYSTEM_OPERATION_STARTED = "FILESYSTEM_OPERATION_STARTED"
    FILESYSTEM_OPERATION_SUCCEEDED = "FILESYSTEM_OPERATION_SUCCEEDED"
    FILESYSTEM_OPERATION_FAILED = "FILESYSTEM_OPERATION_FAILED"
    FILESYSTEM_OPERATION_DENIED = "FILESYSTEM_OPERATION_DENIED"
    FILESYSTEM_OPERATION_CONFIRMATION_REQUIRED = "FILESYSTEM_OPERATION_CONFIRMATION_REQUIRED"
    FILE_ACTION_SUCCEEDED = "FILE_ACTION_SUCCEEDED"
    FILE_ACTION_FAILED = "FILE_ACTION_FAILED"
    PROCESS_QUERY_STARTED = "PROCESS_QUERY_STARTED"
    PROCESS_QUERY_SUCCEEDED = "PROCESS_QUERY_SUCCEEDED"
    PROCESS_QUERY_FAILED = "PROCESS_QUERY_FAILED"
    PROCESS_TERMINATION_REQUESTED = "PROCESS_TERMINATION_REQUESTED"
    PROCESS_TERMINATION_CONFIRMED = "PROCESS_TERMINATION_CONFIRMED"
    PROCESS_TERMINATION_DENIED = "PROCESS_TERMINATION_DENIED"
    PROCESS_TERMINATION_SUCCEEDED = "PROCESS_TERMINATION_SUCCEEDED"
    PROCESS_TERMINATION_FAILED = "PROCESS_TERMINATION_FAILED"
    REGISTRY_PATH_VALIDATED = "REGISTRY_PATH_VALIDATED"
    REGISTRY_QUERY_STARTED = "REGISTRY_QUERY_STARTED"
    REGISTRY_QUERY_SUCCEEDED = "REGISTRY_QUERY_SUCCEEDED"
    REGISTRY_QUERY_FAILED = "REGISTRY_QUERY_FAILED"
    REGISTRY_ACCESS_DENIED = "REGISTRY_ACCESS_DENIED"
    SERVICE_NAME_VALIDATED = "SERVICE_NAME_VALIDATED"
    SERVICE_QUERY_STARTED = "SERVICE_QUERY_STARTED"
    SERVICE_QUERY_SUCCEEDED = "SERVICE_QUERY_SUCCEEDED"
    SERVICE_QUERY_FAILED = "SERVICE_QUERY_FAILED"
    SERVICE_ACCESS_DENIED = "SERVICE_ACCESS_DENIED"
    COMMAND_POLICY_EVALUATED = "COMMAND_POLICY_EVALUATED"
    COMMAND_POLICY_ALLOWED = "COMMAND_POLICY_ALLOWED"
    COMMAND_POLICY_DENIED = "COMMAND_POLICY_DENIED"
    COMMAND_POLICY_REJECTED = "COMMAND_POLICY_REJECTED"
    COMMAND_PARSE_STARTED = "COMMAND_PARSE_STARTED"
    COMMAND_PARSE_SUCCEEDED = "COMMAND_PARSE_SUCCEEDED"
    COMMAND_PARSE_REJECTED = "COMMAND_PARSE_REJECTED"
    COMMAND_ARGUMENT_VALIDATED = "COMMAND_ARGUMENT_VALIDATED"
    POWERSHELL_BOUNDARY_EVALUATED = "POWERSHELL_BOUNDARY_EVALUATED"
    POWERSHELL_BOUNDARY_ALLOWED = "POWERSHELL_BOUNDARY_ALLOWED"
    POWERSHELL_BOUNDARY_DENIED = "POWERSHELL_BOUNDARY_DENIED"
    POWERSHELL_BOUNDARY_REJECTED = "POWERSHELL_BOUNDARY_REJECTED"
    CMD_BOUNDARY_EVALUATED = "CMD_BOUNDARY_EVALUATED"
    CMD_BOUNDARY_ALLOWED = "CMD_BOUNDARY_ALLOWED"
    CMD_BOUNDARY_DENIED = "CMD_BOUNDARY_DENIED"
    CMD_BOUNDARY_REJECTED = "CMD_BOUNDARY_REJECTED"
    COMMAND_OUTPUT_SANITIZED = "COMMAND_OUTPUT_SANITIZED"
    COMMAND_OUTPUT_REDACTED = "COMMAND_OUTPUT_REDACTED"
    COMMAND_OUTPUT_TRUNCATED = "COMMAND_OUTPUT_TRUNCATED"
    COMMAND_OUTPUT_SANITIZATION_FAILED = "COMMAND_OUTPUT_SANITIZATION_FAILED"
    COMMAND_AUDIT_STARTED = "COMMAND_AUDIT_STARTED"
    COMMAND_AUTHORIZATION_ALLOWED = "COMMAND_AUTHORIZATION_ALLOWED"
    COMMAND_AUTHORIZATION_DENIED = "COMMAND_AUTHORIZATION_DENIED"
    COMMAND_EXECUTION_STARTED = "COMMAND_EXECUTION_STARTED"
    COMMAND_EXECUTION_SUCCEEDED = "COMMAND_EXECUTION_SUCCEEDED"
    COMMAND_EXECUTION_FAILED = "COMMAND_EXECUTION_FAILED"
    COMMAND_EXECUTION_TIMEOUT = "COMMAND_EXECUTION_TIMEOUT"
    COMMAND_EXECUTION_TERMINATED = "COMMAND_EXECUTION_TERMINATED"
    COMMAND_AUDIT_COMPLETED = "COMMAND_AUDIT_COMPLETED"
    COMMAND_AUDIT_SECURITY_FAILURE = "COMMAND_AUDIT_SECURITY_FAILURE"
    DESKTOP_CAPTURE_REQUESTED = "DESKTOP_CAPTURE_REQUESTED"
    DESKTOP_CAPTURE_VALIDATED = "DESKTOP_CAPTURE_VALIDATED"
    DESKTOP_CAPTURE_STARTED = "DESKTOP_CAPTURE_STARTED"
    DESKTOP_CAPTURE_SUCCEEDED = "DESKTOP_CAPTURE_SUCCEEDED"
    DESKTOP_CAPTURE_FAILED = "DESKTOP_CAPTURE_FAILED"
    DESKTOP_CAPTURE_DENIED = "DESKTOP_CAPTURE_DENIED"
    DESKTOP_CAPTURE_TIMEOUT = "DESKTOP_CAPTURE_TIMEOUT"
    OCR_REQUESTED = "OCR_REQUESTED"
    OCR_VALIDATED = "OCR_VALIDATED"
    OCR_STARTED = "OCR_STARTED"
    OCR_SUCCEEDED = "OCR_SUCCEEDED"
    OCR_FAILED = "OCR_FAILED"
    OCR_DENIED = "OCR_DENIED"
    OCR_TIMEOUT = "OCR_TIMEOUT"
    OCR_BACKEND_UNAVAILABLE = "OCR_BACKEND_UNAVAILABLE"
    OCR_OUTPUT_SANITIZED = "OCR_OUTPUT_SANITIZED"
    UI_INSPECTION_REQUESTED = "UI_INSPECTION_REQUESTED"
    UI_INSPECTION_VALIDATED = "UI_INSPECTION_VALIDATED"
    UI_INSPECTION_STARTED = "UI_INSPECTION_STARTED"
    UI_INSPECTION_SUCCEEDED = "UI_INSPECTION_SUCCEEDED"
    UI_INSPECTION_FAILED = "UI_INSPECTION_FAILED"
    UI_INSPECTION_DENIED = "UI_INSPECTION_DENIED"
    UI_INSPECTION_TIMEOUT = "UI_INSPECTION_TIMEOUT"
    UI_INSPECTION_SANITIZED = "UI_INSPECTION_SANITIZED"
    UI_INSPECTION_LIMIT_REACHED = "UI_INSPECTION_LIMIT_REACHED"
    DESKTOP_ACTION_REQUESTED = "DESKTOP_ACTION_REQUESTED"
    DESKTOP_ACTION_VALIDATED = "DESKTOP_ACTION_VALIDATED"
    DESKTOP_ACTION_AUTHORIZATION_REQUIRED = "DESKTOP_ACTION_AUTHORIZATION_REQUIRED"
    DESKTOP_ACTION_AUTHORIZED = "DESKTOP_ACTION_AUTHORIZED"
    DESKTOP_ACTION_STARTED = "DESKTOP_ACTION_STARTED"
    DESKTOP_ACTION_SUCCEEDED = "DESKTOP_ACTION_SUCCEEDED"
    DESKTOP_ACTION_FAILED = "DESKTOP_ACTION_FAILED"
    DESKTOP_ACTION_DENIED = "DESKTOP_ACTION_DENIED"
    DESKTOP_ACTION_TIMEOUT = "DESKTOP_ACTION_TIMEOUT"
    DESKTOP_ACTION_EMERGENCY_STOP = "DESKTOP_ACTION_EMERGENCY_STOP"
    DESKTOP_ACTION_STALE_TARGET = "DESKTOP_ACTION_STALE_TARGET"
    DESKTOP_ACTION_SANITIZED = "DESKTOP_ACTION_SANITIZED"
    NETWORK_INSPECTION_REQUESTED = "NETWORK_INSPECTION_REQUESTED"
    NETWORK_INSPECTION_VALIDATED = "NETWORK_INSPECTION_VALIDATED"
    NETWORK_INSPECTION_STARTED = "NETWORK_INSPECTION_STARTED"
    NETWORK_INSPECTION_SUCCEEDED = "NETWORK_INSPECTION_SUCCEEDED"
    NETWORK_INSPECTION_FAILED = "NETWORK_INSPECTION_FAILED"
    NETWORK_INSPECTION_DENIED = "NETWORK_INSPECTION_DENIED"
    NETWORK_INSPECTION_TIMEOUT = "NETWORK_INSPECTION_TIMEOUT"
    NETWORK_INSPECTION_SANITIZED = "NETWORK_INSPECTION_SANITIZED"
    NETWORK_INSPECTION_LIMIT_REACHED = "NETWORK_INSPECTION_LIMIT_REACHED"
    NETWORK_BACKEND_UNAVAILABLE = "NETWORK_BACKEND_UNAVAILABLE"
    NETWORK_CONNECTIONS_REQUESTED = "NETWORK_CONNECTIONS_REQUESTED"
    NETWORK_CONNECTIONS_VALIDATED = "NETWORK_CONNECTIONS_VALIDATED"
    NETWORK_CONNECTIONS_STARTED = "NETWORK_CONNECTIONS_STARTED"
    NETWORK_CONNECTIONS_SUCCEEDED = "NETWORK_CONNECTIONS_SUCCEEDED"
    NETWORK_CONNECTIONS_FAILED = "NETWORK_CONNECTIONS_FAILED"
    NETWORK_CONNECTIONS_DENIED = "NETWORK_CONNECTIONS_DENIED"
    NETWORK_CONNECTIONS_TIMEOUT = "NETWORK_CONNECTIONS_TIMEOUT"
    NETWORK_CONNECTIONS_SANITIZED = "NETWORK_CONNECTIONS_SANITIZED"
    NETWORK_CONNECTIONS_LIMIT_REACHED = "NETWORK_CONNECTIONS_LIMIT_REACHED"
    NETWORK_CONNECTIONS_BACKEND_UNAVAILABLE = "NETWORK_CONNECTIONS_BACKEND_UNAVAILABLE"
    NETWORK_ROUTING_REQUESTED = "NETWORK_ROUTING_REQUESTED"
    NETWORK_ROUTING_VALIDATED = "NETWORK_ROUTING_VALIDATED"
    NETWORK_ROUTING_STARTED = "NETWORK_ROUTING_STARTED"
    NETWORK_ROUTING_SUCCEEDED = "NETWORK_ROUTING_SUCCEEDED"
    NETWORK_ROUTING_FAILED = "NETWORK_ROUTING_FAILED"
    NETWORK_ROUTING_DENIED = "NETWORK_ROUTING_DENIED"
    NETWORK_ROUTING_TIMEOUT = "NETWORK_ROUTING_TIMEOUT"
    NETWORK_ROUTING_SANITIZED = "NETWORK_ROUTING_SANITIZED"
    NETWORK_ROUTING_LIMIT_REACHED = "NETWORK_ROUTING_LIMIT_REACHED"
    NETWORK_ROUTING_BACKEND_UNAVAILABLE = "NETWORK_ROUTING_BACKEND_UNAVAILABLE"
    NETWORK_DNS_CACHE_REQUESTED = "NETWORK_DNS_CACHE_REQUESTED"
    NETWORK_DNS_CACHE_VALIDATED = "NETWORK_DNS_CACHE_VALIDATED"
    NETWORK_DNS_CACHE_STARTED = "NETWORK_DNS_CACHE_STARTED"
    NETWORK_DNS_CACHE_SUCCEEDED = "NETWORK_DNS_CACHE_SUCCEEDED"
    NETWORK_DNS_CACHE_FAILED = "NETWORK_DNS_CACHE_FAILED"
    NETWORK_DNS_CACHE_DENIED = "NETWORK_DNS_CACHE_DENIED"
    NETWORK_DNS_CACHE_TIMEOUT = "NETWORK_DNS_CACHE_TIMEOUT"
    NETWORK_DNS_CACHE_SANITIZED = "NETWORK_DNS_CACHE_SANITIZED"
    NETWORK_DNS_CACHE_LIMIT_REACHED = "NETWORK_DNS_CACHE_LIMIT_REACHED"
    NETWORK_DNS_CACHE_BACKEND_UNAVAILABLE = "NETWORK_DNS_CACHE_BACKEND_UNAVAILABLE"
    SESSION_CREATED = "SESSION_CREATED"
    SESSION_ACCESSED = "SESSION_ACCESSED"
    SESSION_UPDATED = "SESSION_UPDATED"
    SESSION_MESSAGE_ADDED = "SESSION_MESSAGE_ADDED"
    SESSION_FACT_ADDED = "SESSION_FACT_ADDED"
    SESSION_PREFERENCE_ADDED = "SESSION_PREFERENCE_ADDED"
    SESSION_SNAPSHOT_CREATED = "SESSION_SNAPSHOT_CREATED"
    SESSION_PAUSED = "SESSION_PAUSED"
    SESSION_RESUMED = "SESSION_RESUMED"
    SESSION_CANCELLED = "SESSION_CANCELLED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SESSION_DENIED = "SESSION_DENIED"
    SESSION_SANITIZED = "SESSION_SANITIZED"
    SESSION_LIMIT_REACHED = "SESSION_LIMIT_REACHED"
    SESSION_STORE_ERROR = "SESSION_STORE_ERROR"
    SESSION_COMPACTED = "SESSION_COMPACTED"
    MEMORY_CONSOLIDATED = "MEMORY_CONSOLIDATED"

    CONTEXT_REQUESTED = "CONTEXT_REQUESTED"
    CONTEXT_VALIDATED = "CONTEXT_VALIDATED"
    CONTEXT_RETRIEVAL_STARTED = "CONTEXT_RETRIEVAL_STARTED"
    CONTEXT_RETRIEVAL_SUCCEEDED = "CONTEXT_RETRIEVAL_SUCCEEDED"
    CONTEXT_RETRIEVAL_FAILED = "CONTEXT_RETRIEVAL_FAILED"
    CONTEXT_DENIED = "CONTEXT_DENIED"
    CONTEXT_TIMEOUT = "CONTEXT_TIMEOUT"
    CONTEXT_SANITIZED = "CONTEXT_SANITIZED"
    CONTEXT_LIMIT_REACHED = "CONTEXT_LIMIT_REACHED"
    CONTEXT_BUILT = "CONTEXT_BUILT"
    CONTEXT_TRUNCATED = "CONTEXT_TRUNCATED"
    EMERGENCY_STOP_ACTIVATED = "EMERGENCY_STOP_ACTIVATED"
    EMERGENCY_STOP_DEACTIVATED = "EMERGENCY_STOP_DEACTIVATED"
    EMERGENCY_STOP_CHECKED = "EMERGENCY_STOP_CHECKED"
    ACTION_ABORTED_BY_EMERGENCY_STOP = "ACTION_ABORTED_BY_EMERGENCY_STOP"
    # Etapa 17.0 — Observability
    OBSERVABILITY_TRACE_STARTED = "OBSERVABILITY_TRACE_STARTED"
    OBSERVABILITY_TRACE_COMPLETED = "OBSERVABILITY_TRACE_COMPLETED"
    PLUGIN_SANDBOX_ENTERED = "PLUGIN_SANDBOX_ENTERED"
    PLUGIN_SANDBOX_EXITED = "PLUGIN_SANDBOX_EXITED"
    WAKE_WORD_DETECTED = "WAKE_WORD_DETECTED"
    AUTONOMY_LEVEL_APPLIED = "AUTONOMY_LEVEL_APPLIED"


class AuditFailureMode(StrEnum):
    """Modo de gestión de fallos del logger de auditoría."""

    BEST_EFFORT = "BEST_EFFORT"
    FAIL_CLOSED = "FAIL_CLOSED"


def _is_sensitive_key(key: str) -> bool:
    k = key.lower()
    if k in SENSITIVE_KEY_PATTERNS:
        return True
    words = set(re.split(r"[_\-\s]+", k))
    return bool(words & SENSITIVE_KEY_PATTERNS)


def sanitize_audit_data(data: Any, max_str_len: int = 1000) -> Any:
    """Sanitiza recursivamente datos en dicts, listas, tuplas, sets y objetos.

    Reemplaza claves sensibles con '[REDACTED]' y trunca cadenas excesivas con '[TRUNCATED]'.
    Se ejecuta SIEMPRE ANTES de persistir o emitir cualquier evento de auditoría.
    """
    if isinstance(data, dict):
        sanitized_dict: JSONDict = {}
        for k, v in data.items():
            key_str = str(k)
            if _is_sensitive_key(key_str):
                sanitized_dict[k] = "[REDACTED]"
            else:
                sanitized_dict[k] = sanitize_audit_data(v, max_str_len)
        return sanitized_dict
    elif isinstance(data, (list, tuple, set)):
        return [sanitize_audit_data(item, max_str_len) for item in data]
    elif isinstance(data, str):
        if len(data) > max_str_len:
            return data[:max_str_len] + " [TRUNCATED]"
        return data
    elif hasattr(data, "__dict__"):
        try:
            return sanitize_audit_data(vars(data), max_str_len)
        except Exception:
            return str(data)
    else:
        return data


def compute_canonical_event_hash(event_dict: JSONDict) -> str:
    """Calcula un hash SHA-256 canónico sobre la representación ordenada de un evento sanitizado.

    NOTA DE ARQUITECTURA:
    El event_hash se calcula sobre la representación canónica sanitizada. No constituye aún
    una cadena criptográfica completa de auditoría (blockchain/merkle tree) ni protege el archivo
    contra modificaciones posteriores en el sistema de archivos. La integridad criptográfica avanzada
    está reservada para subetapas futuras.
    """
    temp_dict = {k: v for k, v in event_dict.items() if k != "event_hash"}
    canonical_json = json.dumps(temp_dict, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditEvent:
    """Evento estructurado inmutable de auditoría de seguridad e inspección del ciclo de vida."""

    event_type: AuditEventType | str
    user: str = "system"
    tool_name: str = ""
    operation: str = ""
    parameters: JSONDict = field(default_factory=dict)
    security_level: SecurityLevel | str = SecurityLevel.SAFE
    risk_factors: frozenset[str] = field(default_factory=frozenset)
    policy_id: str = ""
    policy_version: str = "1.0.0"
    policy_source: str = "SYSTEM"
    policy_decision: str = ""
    permission_decision: str = ""
    confirmation_status: str = ""
    requires_elevation: bool = False
    success: bool = True
    reason: str = ""
    error_code: str = ""
    error_message: str = ""
    duration_ms: float = 0.0
    metadata: JSONDict = field(default_factory=dict)
    session_id: str = ""
    correlation_id: str = ""
    request_id: str = ""
    # Etapa 17.0 — Identificadores de correlación extendidos
    action_id: str = ""
    task_id: str = ""
    plugin_id: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_hash: str = ""

    def __post_init__(self) -> None:
        if not self.event_id or not str(self.event_id).strip():
            object.__setattr__(self, "event_id", str(uuid.uuid4()))
        if self.timestamp is None:
            object.__setattr__(self, "timestamp", datetime.now(UTC))

        # Sanitización y truncamiento recursivo previo obligatorio
        san_params = sanitize_audit_data(self.parameters)
        san_meta = sanitize_audit_data(self.metadata)
        san_reason = str(sanitize_audit_data(self.reason))
        san_error = str(sanitize_audit_data(self.error_message))
        rf_frozen = (
            frozenset(self.risk_factors)
            if isinstance(self.risk_factors, (set, list, tuple, frozenset))
            else frozenset()
        )

        object.__setattr__(self, "parameters", san_params)
        object.__setattr__(self, "metadata", san_meta)
        object.__setattr__(self, "reason", san_reason)
        object.__setattr__(self, "error_message", san_error)
        object.__setattr__(self, "risk_factors", rf_frozen)

        if not self.event_hash:
            d = self.to_dict()
            h = compute_canonical_event_hash(d)
            object.__setattr__(self, "event_hash", h)

    def to_dict(self) -> JSONDict:
        """Devuelve una representación serializable en diccionario completamente sanitizada."""
        sec_level = getattr(self.security_level, "value", str(self.security_level))
        ev_type = getattr(self.event_type, "value", str(self.event_type))

        raw_dict: JSONDict = {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else str(self.timestamp),
            "event_type": ev_type,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            # Etapa 17.0 — extended correlation IDs
            "action_id": self.action_id,
            "task_id": self.task_id,
            "plugin_id": self.plugin_id,
            "user": self.user,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "parameters": sanitize_audit_data(self.parameters),
            "security_level": sec_level,
            "risk_factors": sorted(list(self.risk_factors)),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_source": self.policy_source,
            "policy_decision": self.policy_decision,
            "permission_decision": self.permission_decision,
            "confirmation_status": self.confirmation_status,
            "requires_elevation": self.requires_elevation,
            "success": self.success,
            "reason": sanitize_audit_data(self.reason),
            "error_code": self.error_code,
            "error_message": sanitize_audit_data(self.error_message),
            "duration_ms": round(self.duration_ms, 2),
            "metadata": sanitize_audit_data(self.metadata),
            "event_hash": self.event_hash,
        }

        if not self.event_hash:
            raw_dict["event_hash"] = compute_canonical_event_hash(raw_dict)

        return raw_dict


class MemoryAuditSink:
    """Sink de auditoría en memoria seguro para hilos, pruebas y consultas rápidas (IAuditSink)."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = threading.Lock()

    def emit(self, event: AuditEvent) -> None:
        """Registra un evento sanitizado e inmutable en memoria."""
        with self._lock:
            self._events.append(event)

    def get_events(
        self,
        request_id: str | None = None,
        correlation_id: str | None = None,
        session_id: str | None = None,
        event_type: str | None = None,
        tool_name: str | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        """Consulta eventos filtrando por múltiples dimensiones."""
        with self._lock:
            filtered = list(self._events)

        if request_id:
            filtered = [e for e in filtered if e.request_id == request_id]
        if correlation_id:
            filtered = [e for e in filtered if e.correlation_id == correlation_id]
        if session_id:
            filtered = [e for e in filtered if e.session_id == session_id]
        if event_type:
            et_str = getattr(event_type, "value", str(event_type))
            filtered = [e for e in filtered if str(e.event_type) == et_str]
        if tool_name:
            filtered = [e for e in filtered if e.tool_name.lower() == tool_name.lower()]

        if limit is not None:
            filtered = filtered[-limit:]

        return list(filtered)

    def clear(self) -> None:
        """Limpia los eventos en memoria."""
        with self._lock:
            self._events.clear()


class FileAuditSink:
    """Sink de auditoría atómico y seguro en disco (JSON Lines `.jsonl`) con rotación por tamaño (IAuditSink)."""

    def __init__(
        self,
        audit_dir: Path | str = Path("logs/audit"),
        file_name: str = "audit.jsonl",
        max_bytes: int = 10485760,  # 10 MB
        backup_count: int = 5,
    ) -> None:
        self.audit_dir = Path(audit_dir)
        self.file_name = file_name
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._lock = threading.Lock()

        # Crear directorio si no existe
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.current_file = self.audit_dir / self.file_name

    def emit(self, event: AuditEvent) -> None:
        """Persiste un evento en formato JSON Lines (`.jsonl`) con rotación y cerrojo de hilos."""
        event_dict = event.to_dict()
        json_line = json.dumps(event_dict, ensure_ascii=False) + "\n"

        with self._lock:
            self._rotate_if_needed()
            with open(self.current_file, "a", encoding="utf-8") as f:
                f.write(json_line)

    def _rotate_if_needed(self) -> None:
        """Ejecuta la rotación de archivos si el archivo actual supera `max_bytes`."""
        if not self.current_file.exists():
            return

        if self.current_file.stat().st_size >= self.max_bytes:
            for i in range(self.backup_count - 1, 0, -1):
                sfn = self.audit_dir / f"{self.file_name}.{i}"
                dfn = self.audit_dir / f"{self.file_name}.{i + 1}"
                if sfn.exists():
                    if dfn.exists():
                        dfn.unlink()
                    sfn.rename(dfn)

            dfn = self.audit_dir / f"{self.file_name}.1"
            if dfn.exists():
                dfn.unlink()
            self.current_file.rename(dfn)


@dataclass
class AuditLogEntry:
    """Entrada estructurada inmutable de auditoría (retrocompatibilidad Subetapas 04.1-04.4)."""

    usuario: str
    accion: str
    herramienta: str
    riesgo: RiskLevel
    resultado: str
    fecha: datetime
    duracion_ms: float
    autorizacion: PermissionAction
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "usuario": self.usuario,
            "accion": self.accion,
            "herramienta": self.herramienta,
            "riesgo": self.riesgo.value if isinstance(self.riesgo, RiskLevel) else str(self.riesgo),
            "resultado": self.resultado,
            "fecha": self.fecha.isoformat(),
            "duracion_ms": self.duracion_ms,
            "autorizacion": (
                self.autorizacion.value if isinstance(self.autorizacion, PermissionAction) else str(self.autorizacion)
            ),
            "details": sanitize_audit_data(self.details),
        }


class AuditLogger:
    """Gestor principal de auditoría estructurada (Subetapa 04.6).

    Proporciona:
    1. Sanitización de datos sensibles previa a la emisión.
    2. Emisión atómica y thread-safe hacia sinks desacoplados.
    3. Fail-Safe: Los fallos de auditoría en modo BEST_EFFORT no alteran decisiones de seguridad.
    """

    def __init__(
        self,
        sinks: list[Any] | None = None,
        failure_mode: AuditFailureMode = AuditFailureMode.BEST_EFFORT,
        event_bus: EventBus | None = None,
    ) -> None:
        self.event_bus = event_bus or get_event_bus()
        self.failure_mode = failure_mode
        self._sinks: list[Any] = sinks if sinks is not None else [MemoryAuditSink(), FileAuditSink()]
        self._legacy_entries: list[AuditLogEntry] = []
        self._lock = threading.Lock()

    def add_sink(self, sink: Any) -> None:
        """Agrega un sink de auditoría."""
        with self._lock:
            self._sinks.append(sink)

    def get_events(self, **kwargs: Any) -> list[AuditEvent]:
        """Obtiene eventos filtrados delegando al MemoryAuditSink en la lista de sinks."""
        with self._lock:
            for sink in self._sinks:
                if isinstance(sink, MemoryAuditSink):
                    return sink.get_events(**kwargs)
        return []


    def log_audit_event(self, event: AuditEvent) -> AuditEvent:
        """Registra, sanitiza y emite un evento estructurado AuditEvent a todos los sinks."""
        with self._lock:
            active_sinks = list(self._sinks)

        for sink in active_sinks:
            try:
                sink.emit(event)
            except Exception as e:
                logger.error(f"Fallo al emitir evento de auditoría [{event.event_id}] en sink {type(sink).__name__}: {e}")
                if self.failure_mode == AuditFailureMode.FAIL_CLOSED:
                    raise

        # Notificación asíncrona al EventBus
        try:
            payload = event.to_dict()
            if event.user:
                payload["usuario"] = event.user
            if event.tool_name:
                payload["herramienta"] = event.tool_name
            if event.operation:
                payload["accion"] = event.operation
            self.event_bus.publish("audit:logged", payload)
        except Exception as e:
            logger.warning(f"Error notificando al EventBus: {e}")

        return event

    def log_event(
        self,
        usuario: str,
        accion: str,
        herramienta: str,
        riesgo: RiskLevel,
        resultado: str,
        duracion_ms: float,
        autorizacion: PermissionAction,
        details: dict[str, Any] | None = None,
    ) -> AuditLogEntry:
        """Método de retrocompatibilidad con Subetapas 04.1-04.4."""
        entry = AuditLogEntry(
            usuario=usuario.strip(),
            accion=accion.strip(),
            herramienta=herramienta.strip(),
            riesgo=riesgo,
            resultado=resultado.strip(),
            fecha=datetime.now(UTC),
            duracion_ms=round(duracion_ms, 2),
            autorizacion=autorizacion,
            details=sanitize_audit_data(details or {}),
        )

        with self._lock:
            self._legacy_entries.append(entry)

        modern_event = AuditEvent(
            event_type=AuditEventType.EXECUTION_SUCCEEDED if resultado == "SUCCESS" else AuditEventType.EXECUTION_FAILED,
            user=usuario,
            tool_name=herramienta,
            operation=accion,
            security_level=getattr(riesgo, "value", str(riesgo)),
            duration_ms=duracion_ms,
            permission_decision=getattr(autorizacion, "value", str(autorizacion)),
            success=(resultado == "SUCCESS"),
            metadata=entry.details,
        )
        self.log_audit_event(modern_event)

        return entry

    def get_logs(
        self,
        user_filter: str | None = None,
        tool_filter: str | None = None,
        result_filter: str | None = None,
        limit: int | None = None,
    ) -> list[AuditLogEntry]:
        """Obtiene entradas legacy filtradas."""
        with self._lock:
            filtered = list(self._legacy_entries)

        if user_filter:
            uf = user_filter.strip().lower()
            filtered = [e for e in filtered if e.usuario.lower() == uf]

        if tool_filter:
            tf = tool_filter.strip().lower()
            filtered = [e for e in filtered if e.herramienta.lower() == tf]

        if result_filter:
            rf = result_filter.strip().lower()
            filtered = [e for e in filtered if e.resultado.lower() == rf]

        if limit is not None:
            filtered = filtered[-limit:]

        return list(filtered)

    def export_logs_json(self) -> str:
        """Exporta los logs legacy en JSON."""
        with self._lock:
            data = [entry.to_dict() for entry in self._legacy_entries]
        return json.dumps(data, indent=2, ensure_ascii=False)

    def export_logs_csv(self) -> str:
        """Exporta los logs legacy en CSV."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["entry_id", "usuario", "accion", "herramienta", "riesgo", "resultado", "fecha", "duracion_ms", "autorizacion"]
        )

        with self._lock:
            entries = list(self._legacy_entries)

        for entry in entries:
            writer.writerow(
                [
                    entry.entry_id,
                    entry.usuario,
                    entry.accion,
                    entry.herramienta,
                    getattr(entry.riesgo, "value", str(entry.riesgo)),
                    entry.resultado,
                    entry.fecha.isoformat(),
                    entry.duracion_ms,
                    getattr(entry.autorizacion, "value", str(entry.autorizacion)),
                ]
            )

        return output.getvalue()

    def clear_logs(self) -> None:
        """Limpia registros en memoria."""
        with self._lock:
            self._legacy_entries.clear()
            for sink in self._sinks:
                if hasattr(sink, "clear"):
                    sink.clear()
        logger.info("Historial de auditoría limpiado.")


# Instancia Singleton Global
_global_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """Obtiene la instancia global del AuditLogger."""
    global _global_audit_logger
    if _global_audit_logger is None:
        _global_audit_logger = AuditLogger()
    return _global_audit_logger
