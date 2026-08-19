"""Structured Telemetry & Events — Modelos y Sanitización Bounded (Etapa 17.1).

Proporciona:
  - CorrelationId & ActionId: Tipos inmutables de identificación y correlación.
  - TraceContext: Contexto de trazabilidad distribuida para vincular eventos.
  - EventSeverity & EventCategory: Taxonomía canónica de severidad y categorías.
  - StructuredEvent: Evento machine-readable con metadatos acotados (bounded) y
    redacción obligatoria de secretos mediante SecretRedactor.
  - Sanitización estricta: Bloqueo de contraseñas, contenido de portapapeles,
    tokens, screenshots crudos, audio crudo y campos web sensibles.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from core.command_output import SecretRedactor
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.observability.structured_event")

# ─────────────────────────────────────────────────────────────────────────────
# Constantes de Límites para Bounded Metadata
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_MAX_DEPTH: int = 5
DEFAULT_MAX_KEYS: int = 50
DEFAULT_MAX_STRING_LEN: int = 1000
DEFAULT_MAX_LIST_ITEMS: int = 20

# Claves prohibidas que nunca deben persistir su valor real
SENSITIVE_KEY_REGEX = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|auth|bearer|api_key|apikey|credential|"
    r"private_key|privkey|certificate|ssn|credit_card|cvv|clipboard_content|raw_screenshot|"
    r"raw_audio|cookie|session_secret)\b"
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. CorrelationId & ActionId
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CorrelationId:
    """Identificador inmutable raíz para correlacionar eventos a través de todos los canales.

    Garantiza unicidad y trazabilidad end-to-end de una solicitud o ejecución.
    """

    value: str

    def __post_init__(self) -> None:
        val = str(self.value).strip()
        if not val:
            raise ValueError("CorrelationId no puede estar vacío.")
        object.__setattr__(self, "value", val)

    @classmethod
    def generate(cls, prefix: str = "corr_") -> "CorrelationId":
        """Genera un nuevo CorrelationId con UUIDv4."""
        return cls(f"{prefix}{uuid.uuid4().hex}")

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"CorrelationId('{self.value}')"


@dataclass(frozen=True)
class ActionId:
    """Identificador inmutable de una acción atómica o invocación de herramienta.

    Permite identificar unitariamente cada operación individual dentro de un plan o tarea.
    """

    value: str

    def __post_init__(self) -> None:
        val = str(self.value).strip()
        if not val:
            raise ValueError("ActionId no puede estar vacío.")
        object.__setattr__(self, "value", val)

    @classmethod
    def generate(cls, prefix: str = "act_") -> "ActionId":
        """Genera un nuevo ActionId con UUIDv4 corto."""
        return cls(f"{prefix}{uuid.uuid4().hex[:12]}")

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"ActionId('{self.value}')"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Categorías y Severidades de Eventos
# ─────────────────────────────────────────────────────────────────────────────

class EventSeverity(StrEnum):
    """Niveles canónicos de severidad para eventos de telemetría estructurada."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventCategory(StrEnum):
    """Categorías formales de eventos en JESSYCA 3.0 (Etapa 17.1)."""

    ACTION = "ACTION"
    TOOL = "TOOL"
    SECURITY = "SECURITY"
    MEMORY = "MEMORY"
    BROWSER = "BROWSER"
    DESKTOP = "DESKTOP"
    SCHEDULER = "SCHEDULER"
    PLUGIN = "PLUGIN"
    SYSTEM = "SYSTEM"
    ERROR = "ERROR"


# ─────────────────────────────────────────────────────────────────────────────
# 3. TraceContext
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TraceContext:
    """Contexto de trazabilidad distribuida asociado a un evento estructurado.

    Vincula un evento a la sesión, solicitud raíz, tarea, acción y jerarquía de spans.
    """

    correlation_id: str
    action_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    plugin_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    sampled: bool = True
    baggage: dict[str, str] = field(default_factory=dict)

    def derive(
        self,
        action_id: str | None = None,
        task_id: str | None = None,
        plugin_id: str | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> "TraceContext":
        """Deriva un contexto hijo heredando los identificadores base."""
        return TraceContext(
            correlation_id=self.correlation_id,
            action_id=action_id if action_id is not None else self.action_id,
            session_id=self.session_id,
            task_id=task_id if task_id is not None else self.task_id,
            plugin_id=plugin_id if plugin_id is not None else self.plugin_id,
            span_id=span_id if span_id is not None else self.span_id,
            parent_span_id=parent_span_id if parent_span_id is not None else self.parent_span_id,
            sampled=self.sampled,
            baggage=dict(self.baggage),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialización segura del contexto de traza."""
        return {
            "correlation_id": self.correlation_id,
            "action_id": self.action_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "plugin_id": self.plugin_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "sampled": self.sampled,
            "baggage": dict(self.baggage),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TraceContext":
        """Deserializa un TraceContext desde un diccionario."""
        return cls(
            correlation_id=str(data["correlation_id"]),
            action_id=data.get("action_id"),
            session_id=data.get("session_id"),
            task_id=data.get("task_id"),
            plugin_id=data.get("plugin_id"),
            span_id=data.get("span_id"),
            parent_span_id=data.get("parent_span_id"),
            sampled=bool(data.get("sampled", True)),
            baggage=dict(data.get("baggage", {})),
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Sanitización Bounded y Redacción de Secretos
# ─────────────────────────────────────────────────────────────────────────────

def sanitize_bounded_metadata(
    data: Any,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_keys: int = DEFAULT_MAX_KEYS,
    max_string_len: int = DEFAULT_MAX_STRING_LEN,
    max_list_items: int = DEFAULT_MAX_LIST_ITEMS,
    current_depth: int = 0,
) -> Any:
    """Sanitiza y acota estructuras de datos para observabilidad sin fuga de secretos.

    Aplica:
      1. Límite de profundidad (max_depth) para prevenir bucles de recursión.
      2. Límite de claves por diccionario (max_keys) y elementos por lista (max_list_items).
      3. Redacción de claves sensibles conocidas (password, secret, token, clipboard, etc.).
      4. Redacción determinista de cadenas mediante SecretRedactor.
      5. Truncado de cadenas largas (max_string_len).
      6. Protección contra datos binarios crudos (bytes/bytearrays -> resumen hash).
    """
    if current_depth > max_depth:
        return "[DEPTH_LIMIT_EXCEEDED]"

    if data is None:
        return None

    # Tipos primitivos seguros
    if isinstance(data, (bool, int, float)):
        return data

    # Datos binarios (imágenes, buffers de audio, etc.)
    if isinstance(data, (bytes, bytearray, memoryview)):
        b_len = len(data)
        b_hash = hashlib.sha256(bytes(data)).hexdigest()[:12]
        return f"[BINARY_DATA len={b_len} sha256_prefix={b_hash}]"

    # Cadenas de texto
    if isinstance(data, str):
        # 1. Redactar secretos en el contenido
        redacted, _ = SecretRedactor.redact(data)
        # 2. Acotar longitud
        if len(redacted) > max_string_len:
            return redacted[:max_string_len] + "...[TRUNCATED]"
        return redacted

    # Diccionarios
    if isinstance(data, dict):
        result: dict[str, Any] = {}
        items = list(data.items())

        for idx, (key, val) in enumerate(items):
            if idx >= max_keys:
                result["_truncated_keys_count"] = len(items) - max_keys
                break

            key_str = str(key)
            # Redactar si la clave misma es sensible
            if SENSITIVE_KEY_REGEX.search(key_str):
                result[key_str] = "[REDACTED_SENSITIVE_VALUE]"
            else:
                result[key_str] = sanitize_bounded_metadata(
                    val,
                    max_depth=max_depth,
                    max_keys=max_keys,
                    max_string_len=max_string_len,
                    max_list_items=max_list_items,
                    current_depth=current_depth + 1,
                )
        return result

    # Listas / Tuplas / Sets
    if isinstance(data, (list, tuple, set)):
        items_list = list(data)
        sanitized_list: list[Any] = []

        for idx, item in enumerate(items_list):
            if idx >= max_list_items:
                sanitized_list.append(f"[LIST_TRUNCATED +{len(items_list) - max_list_items} items]")
                break

            sanitized_list.append(
                sanitize_bounded_metadata(
                    item,
                    max_depth=max_depth,
                    max_keys=max_keys,
                    max_string_len=max_string_len,
                    max_list_items=max_list_items,
                    current_depth=current_depth + 1,
                )
            )
        return sanitized_list

    # Objetos personalizados con to_dict()
    if hasattr(data, "to_dict") and callable(getattr(data, "to_dict")):
        try:
            return sanitize_bounded_metadata(
                data.to_dict(),
                max_depth=max_depth,
                max_keys=max_keys,
                max_string_len=max_string_len,
                max_list_items=max_list_items,
                current_depth=current_depth + 1,
            )
        except Exception as exc:
            return f"[TO_DICT_CONVERSION_ERROR: {exc}]"

    # Fallback genérico a string sanitizado
    return sanitize_bounded_metadata(
        str(data),
        max_depth=max_depth,
        max_keys=max_keys,
        max_string_len=max_string_len,
        max_list_items=max_list_items,
        current_depth=current_depth + 1,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 5. StructuredEvent (Modelo Principal Machine-Readable)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StructuredEvent:
    """Evento de telemetría estructurado y machine-readable para JESSYCA 3.0.

    INVARIANTES:
    - Bounded: Payload y metadatos con límites estrictos de tamaño y profundidad.
    - Zero-Leakage: Sanitizado con SecretRedactor antes de almacenamiento.
    - Serializable: Métodos to_dict(), to_json(), from_dict(), from_json().
    """

    event_id: str
    timestamp: datetime
    name: str
    category: EventCategory
    severity: EventSeverity
    correlation_id: str
    action_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    plugin_id: str | None = None
    trace_context: TraceContext | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    duration_ms: float | None = None
    error_detail: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        # Asegurar tipos canónicos y sanitización obligatoria de payload y error
        sanitized_payload = sanitize_bounded_metadata(self.payload)
        sanitized_error = sanitize_bounded_metadata(self.error_detail) if self.error_detail else None

        object.__setattr__(self, "payload", sanitized_payload if isinstance(sanitized_payload, dict) else {"data": sanitized_payload})
        object.__setattr__(self, "error_detail", sanitized_error if isinstance(sanitized_error, dict) or sanitized_error is None else {"error": sanitized_error})

    @classmethod
    def create(
        cls,
        name: str,
        category: EventCategory,
        correlation_id: str | CorrelationId,
        severity: EventSeverity = EventSeverity.INFO,
        action_id: str | ActionId | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        plugin_id: str | None = None,
        trace_context: TraceContext | None = None,
        payload: dict[str, Any] | None = None,
        duration_ms: float | None = None,
        error_detail: dict[str, Any] | None = None,
        event_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> "StructuredEvent":
        """Fábrica para construir eventos estructurados con correlación automática."""
        c_id = correlation_id.value if isinstance(correlation_id, CorrelationId) else str(correlation_id)
        a_id = action_id.value if isinstance(action_id, ActionId) else (str(action_id) if action_id else None)

        return cls(
            event_id=event_id or str(uuid.uuid4()),
            timestamp=timestamp or datetime.now(UTC),
            name=name.strip(),
            category=category,
            severity=severity,
            correlation_id=c_id,
            action_id=a_id,
            session_id=session_id,
            task_id=task_id,
            plugin_id=plugin_id,
            trace_context=trace_context,
            payload=payload or {},
            duration_ms=duration_ms,
            error_detail=error_detail,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa el evento a un diccionario machine-readable y seguro."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "name": self.name,
            "category": self.category.value,
            "severity": self.severity.value,
            "correlation_id": self.correlation_id,
            "action_id": self.action_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "plugin_id": self.plugin_id,
            "trace_context": self.trace_context.to_dict() if self.trace_context else None,
            "payload": self.payload,
            "duration_ms": self.duration_ms,
            "error_detail": self.error_detail,
        }

    def to_json(self) -> str:
        """Serializa el evento a formato JSON estándar sin caracteres escapados inseguros."""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StructuredEvent":
        """Reconstruye un StructuredEvent desde un diccionario serializado."""
        tc_raw = data.get("trace_context")
        trace_ctx = TraceContext.from_dict(tc_raw) if tc_raw and isinstance(tc_raw, dict) else None

        ts_raw = data.get("timestamp")
        if isinstance(ts_raw, str):
            ts = datetime.fromisoformat(ts_raw)
        elif isinstance(ts_raw, datetime):
            ts = ts_raw
        else:
            ts = datetime.now(UTC)

        return cls(
            event_id=str(data["event_id"]),
            timestamp=ts,
            name=str(data["name"]),
            category=EventCategory(data["category"]),
            severity=EventSeverity(data.get("severity", EventSeverity.INFO.value)),
            correlation_id=str(data["correlation_id"]),
            action_id=data.get("action_id"),
            session_id=data.get("session_id"),
            task_id=data.get("task_id"),
            plugin_id=data.get("plugin_id"),
            trace_context=trace_ctx,
            payload=dict(data.get("payload", {})),
            duration_ms=float(data["duration_ms"]) if data.get("duration_ms") is not None else None,
            error_detail=dict(data["error_detail"]) if data.get("error_detail") else None,
        )

    @classmethod
    def from_json(cls, json_str: str) -> "StructuredEvent":
        """Deserializa un StructuredEvent desde una cadena JSON."""
        return cls.from_dict(json.loads(json_str))


# ─────────────────────────────────────────────────────────────────────────────
# 6. Protocolo de Sinks y Emisor de Telemetría Estructurada
# ─────────────────────────────────────────────────────────────────────────────

class StructuredEventSink(Protocol):
    """Protocolo que deben cumplir los destinos/exportadores de telemetría estructurada."""

    def emit(self, event: StructuredEvent) -> None:
        """Emite o almacena un evento estructurado."""
        ...


class StructuredTelemetryEmitter:
    """Emisor central thread-safe de eventos de telemetría estructurada."""

    def __init__(self) -> None:
        self._sinks: list[StructuredEventSink] = []
        import threading
        self._lock = threading.Lock()

    def register_sink(self, sink: StructuredEventSink) -> None:
        """Registra un nuevo destino de eventos."""
        with self._lock:
            if sink not in self._sinks:
                self._sinks.append(sink)

    def emit(self, event: StructuredEvent) -> None:
        """Envía un evento estructurado a todos los sinks registrados."""
        with self._lock:
            sinks_copy = list(self._sinks)

        for sink in sinks_copy:
            try:
                sink.emit(event)
            except Exception as exc:
                logger.error(f"[TELEMETRY ERROR] Fallo al emitir StructuredEvent a {type(sink).__name__}: {exc}")

    def emit_action(
        self,
        name: str,
        correlation_id: str | CorrelationId,
        action_id: str | ActionId,
        payload: dict[str, Any] | None = None,
        severity: EventSeverity = EventSeverity.INFO,
        duration_ms: float | None = None,
        **kwargs: Any,
    ) -> StructuredEvent:
        """Atajo para emitir eventos de categoría ACTION."""
        event = StructuredEvent.create(
            name=name,
            category=EventCategory.ACTION,
            correlation_id=correlation_id,
            action_id=action_id,
            severity=severity,
            payload=payload,
            duration_ms=duration_ms,
            **kwargs,
        )
        self.emit(event)
        return event

    def emit_tool(
        self,
        tool_name: str,
        operation: str,
        correlation_id: str | CorrelationId,
        action_id: str | ActionId | None = None,
        parameters: dict[str, Any] | None = None,
        duration_ms: float | None = None,
        severity: EventSeverity = EventSeverity.INFO,
        **kwargs: Any,
    ) -> StructuredEvent:
        """Atajo para emitir eventos de categoría TOOL."""
        event = StructuredEvent.create(
            name=f"{tool_name}.{operation}",
            category=EventCategory.TOOL,
            correlation_id=correlation_id,
            action_id=action_id,
            severity=severity,
            payload={"tool_name": tool_name, "operation": operation, "parameters": parameters or {}},
            duration_ms=duration_ms,
            **kwargs,
        )
        self.emit(event)
        return event

    def emit_security(
        self,
        name: str,
        correlation_id: str | CorrelationId,
        severity: EventSeverity = EventSeverity.WARNING,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> StructuredEvent:
        """Atajo para emitir eventos de categoría SECURITY."""
        event = StructuredEvent.create(
            name=name,
            category=EventCategory.SECURITY,
            correlation_id=correlation_id,
            severity=severity,
            payload=payload,
            **kwargs,
        )
        self.emit(event)
        return event

    def emit_error(
        self,
        name: str,
        correlation_id: str | CorrelationId,
        error_detail: dict[str, Any],
        severity: EventSeverity = EventSeverity.ERROR,
        **kwargs: Any,
    ) -> StructuredEvent:
        """Atajo para emitir eventos de categoría ERROR."""
        event = StructuredEvent.create(
            name=name,
            category=EventCategory.ERROR,
            correlation_id=correlation_id,
            severity=severity,
            error_detail=error_detail,
            **kwargs,
        )
        self.emit(event)
        return event


# Singleton global de StructuredTelemetryEmitter
_global_telemetry_emitter: StructuredTelemetryEmitter | None = None
_emitter_lock = __import__("threading").Lock()


def get_structured_telemetry_emitter() -> StructuredTelemetryEmitter:
    """Obtiene el singleton global del emisor de telemetría estructurada."""
    global _global_telemetry_emitter
    if _global_telemetry_emitter is None:
        with _emitter_lock:
            if _global_telemetry_emitter is None:
                _global_telemetry_emitter = StructuredTelemetryEmitter()
    return _global_telemetry_emitter


# Alias canónicos para conveniencia e interoperabilidad
StructuredEventEmitter = StructuredTelemetryEmitter
get_structured_event_emitter = get_structured_telemetry_emitter
