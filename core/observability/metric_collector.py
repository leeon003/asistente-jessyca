"""MetricCollector — API de métricas del canal METRIC (Etapa 17.0).

Registra y mantiene las métricas estándar de JESSYCA 3.0:

Contadores:
  jessyca_requests_total
  jessyca_security_denials_total
  jessyca_confirmations_total
  jessyca_emergency_stops_total
  jessyca_plugin_executions_total
  jessyca_audit_events_total
  jessyca_errors_total

Histogramas:
  jessyca_request_duration_ms
  jessyca_policy_evaluation_duration_ms
  jessyca_confirmation_wait_duration_ms
  jessyca_plugin_execution_duration_ms
  jessyca_audit_emit_duration_ms

Gauges:
  jessyca_active_sessions
  jessyca_pending_confirmations
  jessyca_audit_queue_size
  jessyca_emergency_stop_active

Thread-safe singleton. Sinks desacoplados (JSONL exporter).
"""

from __future__ import annotations

import threading
from typing import Any

from core.logger import get_logger
from core.observability.metric_models import Counter, Gauge, Histogram

logger = get_logger("jessyca.observability.metric_collector")


class MetricCollector:
    """Colector central de métricas de JESSYCA 3.0.

    Todas las métricas están pre-registradas como atributos para evitar
    errores de naming en runtime.
    """

    def __init__(self) -> None:
        # ── COUNTERS ────────────────────────────────────────────────────────
        self.requests_total = Counter(
            name="jessyca_requests_total",
            help="Total de solicitudes recibidas por tool/operación/status",
        )
        self.security_denials_total = Counter(
            name="jessyca_security_denials_total",
            help="Total de denegaciones de seguridad por razón y risk_level",
        )
        self.confirmations_total = Counter(
            name="jessyca_confirmations_total",
            help="Total de confirmaciones por status (approved/rejected/expired)",
        )
        self.emergency_stops_total = Counter(
            name="jessyca_emergency_stops_total",
            help="Total de activaciones del Emergency Stop",
        )
        self.plugin_executions_total = Counter(
            name="jessyca_plugin_executions_total",
            help="Total de ejecuciones de plugin por plugin_id y status",
        )
        self.audit_events_total = Counter(
            name="jessyca_audit_events_total",
            help="Total de eventos de auditoría emitidos por event_type",
        )
        self.errors_total = Counter(
            name="jessyca_errors_total",
            help="Total de errores por componente y error_type",
        )
        self.security_events_total = Counter(
            name="jessyca_security_events_total",
            help="Total de security events por tipo y severidad",
        )

        # ── HISTOGRAMAS ──────────────────────────────────────────────────────
        self.request_duration_ms = Histogram(
            name="jessyca_request_duration_ms",
            help="Duración completa de solicitudes en ms",
            buckets=[10.0, 50.0, 100.0, 500.0, 1000.0, 5000.0, 30000.0],
        )
        self.policy_evaluation_duration_ms = Histogram(
            name="jessyca_policy_evaluation_duration_ms",
            help="Duración de evaluación de política de seguridad en ms",
            buckets=[0.5, 1.0, 5.0, 10.0, 50.0, 100.0],
        )
        self.confirmation_wait_duration_ms = Histogram(
            name="jessyca_confirmation_wait_duration_ms",
            help="Duración de espera de confirmación humana en ms",
            buckets=[1000.0, 5000.0, 15000.0, 30000.0, 60000.0, 300000.0],
        )
        self.plugin_execution_duration_ms = Histogram(
            name="jessyca_plugin_execution_duration_ms",
            help="Duración de ejecución de plugin en ms",
            buckets=[10.0, 100.0, 500.0, 1000.0, 5000.0, 30000.0],
        )
        self.audit_emit_duration_ms = Histogram(
            name="jessyca_audit_emit_duration_ms",
            help="Duración de emisión de evento de auditoría en ms",
            buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 50.0],
        )

        # ── GAUGES ───────────────────────────────────────────────────────────
        self.active_sessions = Gauge(
            name="jessyca_active_sessions",
            help="Número de sesiones activas en este momento",
        )
        self.pending_confirmations = Gauge(
            name="jessyca_pending_confirmations",
            help="Número de confirmaciones pendientes de respuesta del usuario",
        )
        self.audit_queue_size = Gauge(
            name="jessyca_audit_queue_size",
            help="Eventos en cola de auditoría pendientes de flush",
        )
        self.emergency_stop_active = Gauge(
            name="jessyca_emergency_stop_active",
            help="1 si Emergency Stop está activo, 0 si no",
        )

        self._sinks: list[Any] = []
        self._lock = threading.Lock()

    def register_sink(self, sink: Any) -> None:
        """Registra un exporter/sink adicional para flush periódico."""
        with self._lock:
            self._sinks.append(sink)

    # ── API de conveniencia ──────────────────────────────────────────────────

    def record_request(self, tool: str, operation: str, status: str) -> None:
        """Registra una solicitud completada."""
        self.requests_total.increment()

    def record_security_denial(self, reason: str, risk_level: str) -> None:
        """Registra una denegación de seguridad."""
        self.security_denials_total.increment()

    def record_confirmation(self, status: str) -> None:
        """Registra el resultado de una confirmación (approved/rejected/expired)."""
        self.confirmations_total.increment()

    def record_emergency_stop(self) -> None:
        """Registra una activación del Emergency Stop."""
        self.emergency_stops_total.increment()
        self.emergency_stop_active.set(1.0)

    def record_emergency_stop_reset(self) -> None:
        """Registra el reset del Emergency Stop."""
        self.emergency_stop_active.set(0.0)

    def record_plugin_execution(self, plugin_id: str, status: str, duration_ms: float) -> None:
        """Registra la ejecución de un plugin."""
        self.plugin_executions_total.increment()
        self.plugin_execution_duration_ms.observe(duration_ms)

    def record_audit_event(self, event_type: str) -> None:
        """Registra la emisión de un evento de auditoría."""
        self.audit_events_total.increment()

    def record_error(self, component: str, error_type: str) -> None:
        """Registra un error por componente."""
        self.errors_total.increment()

    def record_security_event(self, event_type: str, severity: str) -> None:
        """Registra la emisión de un security event."""
        self.security_events_total.increment()

    def observe_request_duration(self, duration_ms: float) -> None:
        self.request_duration_ms.observe(duration_ms)

    def observe_policy_evaluation(self, duration_ms: float) -> None:
        self.policy_evaluation_duration_ms.observe(duration_ms)

    def observe_confirmation_wait(self, duration_ms: float) -> None:
        self.confirmation_wait_duration_ms.observe(duration_ms)

    def observe_audit_emit(self, duration_ms: float) -> None:
        self.audit_emit_duration_ms.observe(duration_ms)

    def set_active_sessions(self, count: int) -> None:
        self.active_sessions.set(float(count))

    def set_pending_confirmations(self, count: int) -> None:
        self.pending_confirmations.set(float(count))

    def snapshot(self) -> dict[str, Any]:
        """Retorna un snapshot completo de todas las métricas en este momento."""
        return {
            "counters": {
                "requests_total": self.requests_total.to_dict(),
                "security_denials_total": self.security_denials_total.to_dict(),
                "confirmations_total": self.confirmations_total.to_dict(),
                "emergency_stops_total": self.emergency_stops_total.to_dict(),
                "plugin_executions_total": self.plugin_executions_total.to_dict(),
                "audit_events_total": self.audit_events_total.to_dict(),
                "errors_total": self.errors_total.to_dict(),
                "security_events_total": self.security_events_total.to_dict(),
            },
            "histograms": {
                "request_duration_ms": self.request_duration_ms.to_dict(),
                "policy_evaluation_duration_ms": self.policy_evaluation_duration_ms.to_dict(),
                "confirmation_wait_duration_ms": self.confirmation_wait_duration_ms.to_dict(),
                "plugin_execution_duration_ms": self.plugin_execution_duration_ms.to_dict(),
                "audit_emit_duration_ms": self.audit_emit_duration_ms.to_dict(),
            },
            "gauges": {
                "active_sessions": self.active_sessions.to_dict(),
                "pending_confirmations": self.pending_confirmations.to_dict(),
                "audit_queue_size": self.audit_queue_size.to_dict(),
                "emergency_stop_active": self.emergency_stop_active.to_dict(),
            },
        }

    def flush_to_sinks(self) -> None:
        """Emite un snapshot a todos los sinks registrados."""
        snap = self.snapshot()
        for sink in self._sinks:
            try:
                sink.emit(snap)
            except Exception as exc:
                logger.error(f"Error en sink de métricas {type(sink).__name__}: {exc}")


# Singleton global
_metric_collector: MetricCollector | None = None
_metric_lock = threading.Lock()


def get_metric_collector() -> MetricCollector:
    """Retorna la instancia singleton global del MetricCollector."""
    global _metric_collector
    if _metric_collector is None:
        with _metric_lock:
            if _metric_collector is None:
                _metric_collector = MetricCollector()
    return _metric_collector
