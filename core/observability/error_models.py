"""Modelos de Error Records para el canal ERROR (Etapa 17.0).

ErrorRecord es la representación estructurada de un fallo con:
  - Clasificación semántica (ErrorCategory)
  - Contexto completo de observabilidad (IDs de correlación)
  - Stack trace SANITIZADO (solo función y línea, sin valores de variables)
  - Clasificación de recuperabilidad y acción de recuperación
  - Hash de integridad SHA-256

PRIVACIDAD: el stack_trace NO debe contener valores de variables locales
que puedan exponer passwords, tokens o datos sensibles.
Se permite: nombres de módulos, funciones y números de línea.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ErrorCategory(StrEnum):
    """Clasificación semántica de errores."""

    VALIDATION = "VALIDATION"       # Error de validación de input o parámetros
    SECURITY = "SECURITY"           # Violación de política de seguridad
    RUNTIME = "RUNTIME"             # Error de ejecución inesperado (excepción no manejada)
    TIMEOUT = "TIMEOUT"             # Tiempo de espera excedido
    CONFIG = "CONFIG"               # Configuración incorrecta o ausente
    DEPENDENCY = "DEPENDENCY"       # Fallo de dependencia externa
    CANCELLED = "CANCELLED"         # Cancelación por Emergency Stop u otro motivo
    PERMISSION = "PERMISSION"       # Permiso denegado en capa de autonomía


@dataclass(frozen=True)
class ErrorRecord:
    """Registro estructurado inmutable de un fallo del sistema.

    Provee toda la información necesaria para diagnóstico y postmortem
    sin exponer datos sensibles.
    """

    component: str                  # módulo donde ocurrió (ej: "boundary.registry")
    error_type: str                 # nombre de la excepción (ej: "RegistrySecurityViolationError")
    error_category: ErrorCategory | str
    message: str                    # mensaje sanitizado (sin passwords ni tokens)
    tool_name: str = ""
    operation: str = ""
    stack_trace: str = ""           # sanitizado: solo módulo + función + línea
    is_recoverable: bool = False
    recovery_action: str = ""       # "retry", "rollback", "abort", "ignore"
    correlation_id: str = ""
    session_id: str = ""
    task_id: str | None = None
    action_id: str | None = None
    plugin_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)  # sanitizado
    error_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_hash: str = ""

    def __post_init__(self) -> None:
        if not self.event_hash:
            d = self._to_raw_dict()
            h = hashlib.sha256(
                json.dumps(d, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            object.__setattr__(self, "event_hash", h)

    def _to_raw_dict(self) -> dict[str, Any]:
        cat = getattr(self.error_category, "value", str(self.error_category))
        return {
            "error_id": self.error_id,
            "timestamp": self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else str(self.timestamp),
            "component": self.component,
            "error_type": self.error_type,
            "error_category": cat,
            "message": self.message,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "stack_trace": self.stack_trace,
            "is_recoverable": self.is_recoverable,
            "recovery_action": self.recovery_action,
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "action_id": self.action_id,
            "plugin_id": self.plugin_id,
            "context": self.context,
        }

    def to_dict(self) -> dict[str, Any]:
        d = self._to_raw_dict()
        d["event_hash"] = self.event_hash
        return d
