"""Subsistema de Observabilidad para JESSYCA 3.0 (Etapa 17.0 / 17.1).

Proporciona los seis canales de observabilidad separados:
  LOG            — diagnóstico técnico (usa core.logger existente)
  METRIC         — magnitudes numéricas (Counter, Histogram, Gauge)
  TRACE          — árbol de spans por solicitud (TraceManager)
  AUDIT EVENT    — registro inmutable de decisiones (AuditLogger existente, extendido)
  SECURITY EVENT — violaciones y alertas de seguridad (SecurityEventEmitter)
  ERROR          — fallos estructurados con contexto completo (ErrorRecorder)

Telemetría estructurada (Etapa 17.1):
  CorrelationId · ActionId · TraceContext · StructuredEvent · EventSeverity · EventCategory
  Sanitización Bounded y Redacción de Secretos con SecretRedactor.
"""

from __future__ import annotations

from core.observability.context import (
    ObservabilityContext,
    get_current_context,
    run_with_context,
    set_current_context,
)
from core.observability.error_models import ErrorCategory, ErrorRecord
from core.observability.error_recorder import ErrorRecorder, get_error_recorder
from core.observability.exporters import (
    JsonlErrorExporter,
    JsonlMetricExporter,
    JsonlSecurityEventExporter,
    JsonlStructuredEventExporter,
    JsonlTraceExporter,
)
from core.observability.manager import ObservabilityManager, get_observability_manager
from core.observability.metric_collector import MetricCollector, get_metric_collector
from core.observability.metric_models import Counter, Gauge, Histogram
from core.observability.security_event_emitter import (
    SecurityEventEmitter,
    get_security_event_emitter,
)
from core.observability.security_event_models import (
    SecurityEvent,
    SecurityEventType,
    SecuritySeverity,
)
from core.observability.span_models import Span, SpanEvent, SpanStatus
from core.observability.structured_event import (
    ActionId,
    CorrelationId,
    EventCategory,
    EventSeverity,
    StructuredEvent,
    StructuredEventEmitter,
    StructuredEventSink,
    StructuredTelemetryEmitter,
    TraceContext,
    get_structured_event_emitter,
    get_structured_telemetry_emitter,
    sanitize_bounded_metadata,
)
from core.observability.trace_manager import TraceManager, get_trace_manager

__all__ = [
    # Context & Identifiers
    "ObservabilityContext",
    "get_current_context",
    "set_current_context",
    "run_with_context",
    "CorrelationId",
    "ActionId",
    "TraceContext",
    # Structured Telemetry (Etapa 17.1)
    "StructuredEvent",
    "EventSeverity",
    "EventCategory",
    "sanitize_bounded_metadata",
    "StructuredEventEmitter",
    "StructuredTelemetryEmitter",
    "StructuredEventSink",
    "get_structured_telemetry_emitter",
    "get_structured_event_emitter",
    # Trace
    "TraceManager",
    "get_trace_manager",
    "Span",
    "SpanEvent",
    "SpanStatus",
    # Metrics
    "MetricCollector",
    "get_metric_collector",
    "Counter",
    "Histogram",
    "Gauge",
    # Security Events
    "SecurityEventEmitter",
    "get_security_event_emitter",
    "SecurityEvent",
    "SecurityEventType",
    "SecuritySeverity",
    # Errors
    "ErrorRecorder",
    "get_error_recorder",
    "ErrorRecord",
    "ErrorCategory",
    # Exporters
    "JsonlTraceExporter",
    "JsonlMetricExporter",
    "JsonlSecurityEventExporter",
    "JsonlErrorExporter",
    "JsonlStructuredEventExporter",
    # Manager
    "ObservabilityManager",
    "get_observability_manager",
    # Control Center & Real-Time Observability (Fase 24)
    "ControlCenter",
    "ControlCenterSnapshot",
    "ControlCommandResult",
    "SystemState",
    "get_control_center",
]

from core.observability.control_center import (
    ControlCenter,
    get_control_center,
)
from core.observability.control_center_models import (
    ControlCenterSnapshot,
    ControlCommandResult,
    SystemState,
)
