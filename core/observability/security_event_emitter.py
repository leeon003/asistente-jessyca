"""SecurityEventEmitter — Canal SECURITY EVENT (Etapa 17.0).

Emisor centralizado de SecurityEvents. Separado del AuditLogger:
  AuditLogger → compliance inmutable de TODAS las acciones
  SecurityEventEmitter → alertas de alta prioridad de VIOLACIONES

Sinks:
  MemorySecurityEventSink → en memoria (tests, consultas programáticas)
  Exporters registrados → JSONL, futuros SIEM webhooks

Thread-safe singleton con lock interno.
"""

from __future__ import annotations

import threading
from typing import Any

from core.logger import get_logger
from core.observability.context import get_current_context
from core.observability.security_event_models import (
    SecurityEvent,
    SecurityEventType,
    SecuritySeverity,
)

logger = get_logger("jessyca.observability.security_event_emitter")


class MemorySecurityEventSink:
    """Store en memoria de security events. Thread-safe."""

    def __init__(self) -> None:
        self._events: list[SecurityEvent] = []
        self._lock = threading.Lock()

    def emit(self, event: SecurityEvent) -> None:
        with self._lock:
            self._events.append(event)

    def get_all(self) -> list[SecurityEvent]:
        with self._lock:
            return list(self._events)

    def get_by_severity(self, severity: SecuritySeverity | str) -> list[SecurityEvent]:
        sev_str = getattr(severity, "value", str(severity))
        with self._lock:
            return [e for e in self._events if str(e.severity) == sev_str]

    def get_by_type(self, event_type: SecurityEventType | str) -> list[SecurityEvent]:
        type_str = getattr(event_type, "value", str(event_type))
        with self._lock:
            return [e for e in self._events if str(e.event_type) == type_str]

    def get_by_correlation(self, correlation_id: str) -> list[SecurityEvent]:
        with self._lock:
            return [e for e in self._events if e.correlation_id == correlation_id]

    def get_critical(self) -> list[SecurityEvent]:
        return self.get_by_severity(SecuritySeverity.CRITICAL)

    def get_high_and_above(self) -> list[SecurityEvent]:
        high_severities = {str(SecuritySeverity.CRITICAL), str(SecuritySeverity.HIGH)}
        with self._lock:
            return [e for e in self._events if str(e.severity) in high_severities]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


class SecurityEventEmitter:
    """Emisor centralizado de eventos de seguridad.

    Uso:
        emitter = get_security_event_emitter()
        emitter.emit_violation(
            event_type=SecurityEventType.REGISTRY_ALLOWLIST_VIOLATION,
            severity=SecuritySeverity.MEDIUM,
            component="boundary.registry",
            description="Key path outside allowlist: HKLM\\...",
            tool_name="registry.write",
            operation="set_value",
            violated_policy="REGISTRY_WRITE_ALLOWLIST",
        )
    """

    def __init__(self) -> None:
        self._memory_sink = MemorySecurityEventSink()
        self._sinks: list[Any] = [self._memory_sink]
        self._lock = threading.Lock()

    def register_sink(self, sink: Any) -> None:
        """Registra un exporter adicional (JSONL, webhook, etc.)."""
        with self._lock:
            self._sinks.append(sink)

    def emit(self, event: SecurityEvent) -> None:
        """Emite un SecurityEvent a todos los sinks registrados."""
        self._dispatch(event)

        # Log al canal LOG según severidad — sin datos sensibles
        sev = str(event.severity)
        msg = f"[SECURITY EVENT] {event.event_type} | {event.component} | blocked={event.blocked}"
        if sev in ("CRITICAL", "HIGH"):
            logger.error(msg, extra={"correlation_id": event.correlation_id, "event_id": event.event_id})
        elif sev == "MEDIUM":
            logger.warning(msg, extra={"correlation_id": event.correlation_id, "event_id": event.event_id})
        else:
            logger.info(msg, extra={"correlation_id": event.correlation_id, "event_id": event.event_id})

    def emit_violation(
        self,
        event_type: SecurityEventType | str,
        severity: SecuritySeverity | str,
        component: str,
        description: str,
        blocked: bool = True,
        tool_name: str = "",
        operation: str = "",
        violated_policy: str = "",
        risk_level: str = "",
        plugin_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        session_id: str | None = None,
        action_id: str | None = None,
        task_id: str | None = None,
    ) -> SecurityEvent:
        """API de conveniencia — construye y emite un SecurityEvent.

        Infiere correlation_id / session_id / action_id / task_id del
        ObservabilityContext activo si no se proveen explícitamente.
        """
        ctx = get_current_context()
        event = SecurityEvent(
            event_type=event_type,
            severity=severity,
            component=component,
            description=description[:1000],  # sanitizado y limitado
            blocked=blocked,
            correlation_id=correlation_id or (ctx.correlation_id if ctx else ""),
            session_id=session_id or (ctx.session_id if ctx else ""),
            action_id=action_id or (ctx.action_id if ctx else None),
            task_id=task_id or (ctx.task_id if ctx else None),
            plugin_id=plugin_id or (ctx.plugin_id if ctx else None),
            tool_name=tool_name,
            operation=operation,
            violated_policy=violated_policy,
            risk_level=risk_level,
            metadata=metadata or {},
        )
        self.emit(event)
        return event

    def get_memory_sink(self) -> MemorySecurityEventSink:
        """Accede al sink en memoria para consultas y tests."""
        return self._memory_sink

    def _dispatch(self, event: SecurityEvent) -> None:
        sinks = list(self._sinks)
        for sink in sinks:
            try:
                sink.emit(event)
            except Exception as exc:
                logger.error(
                    f"Error en sink de security events {type(sink).__name__}: {exc}",
                    exc_info=True,
                )


# Singleton global
_security_event_emitter: SecurityEventEmitter | None = None
_sec_emitter_lock = threading.Lock()


def get_security_event_emitter() -> SecurityEventEmitter:
    """Retorna la instancia singleton global del SecurityEventEmitter."""
    global _security_event_emitter
    if _security_event_emitter is None:
        with _sec_emitter_lock:
            if _security_event_emitter is None:
                _security_event_emitter = SecurityEventEmitter()
    return _security_event_emitter
