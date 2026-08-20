"""ObservabilityManager — Singleton unificador del subsistema de observabilidad (Etapa 17.0).

Punto de entrada único para inicializar y acceder a todos los componentes
del subsistema de observabilidad:
  - TraceManager
  - MetricCollector
  - SecurityEventEmitter
  - ErrorRecorder

Opcionalmente registra exporters JSONL en función de la configuración.
Thread-safe. Inicialización lazy.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.observability.error_recorder import ErrorRecorder, get_error_recorder
from core.observability.metric_collector import MetricCollector, get_metric_collector
from core.observability.security_event_emitter import (
    SecurityEventEmitter,
    get_security_event_emitter,
)
from core.observability.trace_manager import TraceManager, get_trace_manager

logger = get_logger("jessyca.observability.manager")

# Directorio por defecto de logs
_DEFAULT_LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


class ObservabilityManager:
    """Fachada unificada del subsistema de observabilidad.

    Provee:
      - Acceso a todos los subsistemas (trace, metric, security events, errors)
      - Inicialización de exporters JSONL opcionales
      - Método de cierre limpio (flush + close de archivos)

    Uso recomendado:
        mgr = get_observability_manager()
        mgr.initialize(logs_dir=Path("logs/"), enable_jsonl=True)

        # Desde cualquier componente:
        mgr.traces.span("executor.execute")
        mgr.metrics.record_request("registry.write", "write", "success")
        mgr.security.emit_violation(...)
        mgr.errors.record(exc, component="boundary.registry")
    """

    def __init__(self) -> None:
        self._initialized = False
        self._lock = threading.Lock()

        # Sub-managers (singletons globales)
        self._trace_manager: TraceManager = get_trace_manager()
        self._metric_collector: MetricCollector = get_metric_collector()
        self._security_emitter: SecurityEventEmitter = get_security_event_emitter()
        self._error_recorder: ErrorRecorder = get_error_recorder()
        self._jsonl_exporters: list[Any] = []

    def initialize(
        self,
        logs_dir: Path | str | None = None,
        enable_jsonl_traces: bool = True,
        enable_jsonl_security_events: bool = True,
        enable_jsonl_errors: bool = True,
        enable_jsonl_metrics: bool = True,
    ) -> None:
        """Inicializa el subsistema de observabilidad con exporters JSONL.

        Idempotente: si ya fue inicializado, solo loguea una advertencia.

        Args:
            logs_dir: Directorio donde escribir los JSONL. Por defecto 'logs/'.
            enable_jsonl_*: Habilita/deshabilita cada exporter JSONL.
        """
        with self._lock:
            if self._initialized:
                logger.debug("ObservabilityManager ya inicializado — ignorando llamada duplicada.")
                return

            resolved_logs = Path(logs_dir) if logs_dir else _DEFAULT_LOGS_DIR
            resolved_logs.mkdir(parents=True, exist_ok=True)

            if enable_jsonl_traces:
                from core.observability.exporters.jsonl_trace import JsonlTraceExporter
                trace_exporter = JsonlTraceExporter(resolved_logs / "jessyca_traces.jsonl")
                self._trace_manager.register_sink(trace_exporter)
                self._jsonl_exporters.append(trace_exporter)

            if enable_jsonl_security_events:
                from core.observability.exporters.jsonl_security_event import (
                    JsonlSecurityEventExporter,
                )
                sec_exporter = JsonlSecurityEventExporter(resolved_logs / "jessyca_security.jsonl")
                self._security_emitter.register_sink(sec_exporter)
                self._jsonl_exporters.append(sec_exporter)

            if enable_jsonl_errors:
                from core.observability.exporters.jsonl_error import JsonlErrorExporter
                err_exporter = JsonlErrorExporter(resolved_logs / "jessyca_errors.jsonl")
                self._error_recorder.register_sink(err_exporter)
                self._jsonl_exporters.append(err_exporter)

            if enable_jsonl_metrics:
                from core.observability.exporters.jsonl_metric import JsonlMetricExporter
                met_exporter = JsonlMetricExporter(resolved_logs / "jessyca_metrics.jsonl")
                self._metric_collector.register_sink(met_exporter)
                self._jsonl_exporters.append(met_exporter)

            self._initialized = True
            logger.info(
                f"ObservabilityManager inicializado. JSONL exporters: {len(self._jsonl_exporters)}. "
                f"Directorio: {resolved_logs}"
            )

    @property
    def traces(self) -> TraceManager:
        """Acceso al TraceManager."""
        return self._trace_manager

    @property
    def metrics(self) -> MetricCollector:
        """Acceso al MetricCollector."""
        return self._metric_collector

    @property
    def security(self) -> SecurityEventEmitter:
        """Acceso al SecurityEventEmitter."""
        return self._security_emitter

    @property
    def errors(self) -> ErrorRecorder:
        """Acceso al ErrorRecorder."""
        return self._error_recorder

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def flush(self) -> None:
        """Fuerza el flush de todos los exporters (métricas, pendientes, etc.)."""
        try:
            self._metric_collector.flush_to_sinks()
        except Exception as exc:
            logger.error(f"Error en flush de métricas: {exc}")
        for exporter in self._jsonl_exporters:
            if hasattr(exporter, "flush"):
                try:
                    exporter.flush()
                except Exception as exc:
                    logger.error(f"Error en flush de exporter {type(exporter).__name__}: {exc}")

    def shutdown(self) -> None:
        """Cierre limpio: flush final + close de archivos."""
        self.flush()
        for exporter in self._jsonl_exporters:
            if hasattr(exporter, "close"):
                try:
                    exporter.close()
                except Exception as exc:
                    logger.error(f"Error al cerrar exporter {type(exporter).__name__}: {exc}")
        logger.info("ObservabilityManager cerrado correctamente.")


# Singleton global
_observability_manager: ObservabilityManager | None = None
_obs_manager_lock = threading.Lock()


def get_observability_manager() -> ObservabilityManager:
    """Retorna la instancia singleton global del ObservabilityManager."""
    global _observability_manager
    if _observability_manager is None:
        with _obs_manager_lock:
            if _observability_manager is None:
                _observability_manager = ObservabilityManager()
    return _observability_manager
