"""TraceManager — Gestión de spans del canal TRACE (Etapa 17.0).

Provee API ergonómica para:
  - start_span(): abrir un span vinculado al ObservabilityContext activo
  - end_span(): cerrar un span con status y duración
  - get_current_span(): obtener el span activo del hilo actual
  - Context manager: uso con 'with trace_manager.span("name"):'

El TraceManager almacena spans en memoria (InMemoryTraceStore) y los exporta
vía sinks desacoplados (JSONL, OTLP futuro).

Thread-safe: usa threading.Lock para proteger el store interno.
"""

import contextvars
import threading
from collections import deque
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from core.logger import get_logger
from core.observability.context import ObservabilityContext, get_current_context
from core.observability.span_models import Span, SpanStatus

logger = get_logger("jessyca.observability.trace_manager")

# ContextVar local para el span activo del hilo/tarea actual
_CURRENT_SPAN: contextvars.ContextVar[Span | None] = contextvars.ContextVar(
    "jessyca_current_span", default=None
)

# Capacidad máxima del store en memoria (ring buffer)
_DEFAULT_MAX_SPANS: int = 2000


class InMemoryTraceStore:
    """Store circular de spans en memoria. Thread-safe."""

    def __init__(self, max_size: int = _DEFAULT_MAX_SPANS) -> None:
        self._spans: deque[Span] = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def add(self, span: Span) -> None:
        with self._lock:
            self._spans.append(span)

    def get_all(self) -> list[Span]:
        with self._lock:
            return list(self._spans)

    def get_by_trace(self, trace_id: str) -> list[Span]:
        with self._lock:
            return [s for s in self._spans if s.trace_id == trace_id]

    def get_by_session(self, session_id: str) -> list[Span]:
        with self._lock:
            return [s for s in self._spans if s.session_id == session_id]

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._spans)


class TraceManager:
    """Gestor de spans para el canal TRACE.

    Uso recomendado:
        with get_trace_manager().span("executor.execute_step") as s:
            s.set_attribute("tool.name", "registry.write")
            # ... trabajo ...
            # el span se cierra automáticamente con status OK o ERROR
    """

    def __init__(self, max_store_size: int = _DEFAULT_MAX_SPANS) -> None:
        self._store = InMemoryTraceStore(max_store_size)
        self._sinks: list[Any] = []  # exporters registrados

    def register_sink(self, sink: Any) -> None:
        """Registra un exporter/sink adicional (JSONL, OTLP, etc.)."""
        self._sinks.append(sink)

    def start_span(
        self,
        name: str,
        component: str | None = None,
        attributes: dict[str, str | int | float | bool] | None = None,
        ctx: ObservabilityContext | None = None,
    ) -> Span:
        """Abre un nuevo span vinculado al contexto de observabilidad activo.

        Si existe un span activo en el hilo actual, el nuevo span lo usa como padre
        (propagación automática de parent_span_id).

        Args:
            name: Nombre del span en formato 'component.operation'.
            component: Componente dueño (inferido de name si no se provee).
            attributes: Atributos iniciales del span (limpios, sin datos sensibles).
            ctx: ObservabilityContext explícito (usa el ContextVar si None).

        Returns:
            Span recién abierto (no finalizado).
        """
        resolved_ctx = ctx or get_current_context()
        parent = _CURRENT_SPAN.get(None)

        span = Span(
            name=name,
            component=component or name.split(".")[0],
            trace_id=resolved_ctx.correlation_id if resolved_ctx else "no-trace",
            session_id=resolved_ctx.session_id if resolved_ctx else "",
            parent_span_id=parent.span_id if parent else None,
            task_id=resolved_ctx.task_id if resolved_ctx else None,
            action_id=resolved_ctx.action_id if resolved_ctx else None,
            plugin_id=resolved_ctx.plugin_id if resolved_ctx else None,
            attributes=dict(attributes or {}),
        )
        logger.debug(
            "Span abierto",
            extra={"span_id": span.span_id, "name": name, "trace_id": span.trace_id},
        )
        return span

    def end_span(
        self,
        span: Span,
        status: SpanStatus = SpanStatus.OK,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Finaliza un span y lo persiste en el store + sinks registrados."""
        span.end(status=status, error_type=error_type, error_message=error_message)
        self._store.add(span)
        self._emit_to_sinks(span)
        logger.debug(
            "Span cerrado",
            extra={
                "span_id": span.span_id,
                "name": span.name,
                "status": str(span.status),
                "duration_ms": span.duration_ms,
            },
        )

    @contextmanager
    def span(
        self,
        name: str,
        component: str | None = None,
        attributes: dict[str, str | int | float | bool] | None = None,
        ctx: ObservabilityContext | None = None,
    ) -> Generator[Span, None, None]:
        """Context manager que abre, activa y cierra un span automáticamente.

        El span activo se propaga al ContextVar para que los spans hijos lo detecten.
        Si el bloque lanza una excepción, el span se cierra con status ERROR.

        Ejemplo:
            with get_trace_manager().span("executor.execute_step") as s:
                s.set_attribute("tool.name", "registry.write")
        """
        span = self.start_span(name=name, component=component, attributes=attributes, ctx=ctx)
        token = _CURRENT_SPAN.set(span)
        try:
            yield span
            self.end_span(span, status=SpanStatus.OK)
        except Exception as exc:
            self.end_span(
                span,
                status=SpanStatus.ERROR,
                error_type=type(exc).__name__,
                error_message=str(exc)[:500],  # sanitizado, limitado
            )
            raise
        finally:
            _CURRENT_SPAN.reset(token)

    def get_current_span(self) -> Span | None:
        """Retorna el span activo del hilo/tarea actual."""
        return _CURRENT_SPAN.get(None)

    def get_store(self) -> InMemoryTraceStore:
        """Accede al store en memoria para consultas y tests."""
        return self._store

    def get_spans_for_trace(self, trace_id: str) -> list[Span]:
        """Retorna todos los spans de un trace (correlation_id)."""
        return self._store.get_by_trace(trace_id)

    def _emit_to_sinks(self, span: Span) -> None:
        for sink in self._sinks:
            try:
                sink.emit(span)
            except Exception as exc:
                logger.error(f"Error en sink de trace {type(sink).__name__}: {exc}")


# Singleton global
_trace_manager: TraceManager | None = None
_trace_manager_lock = threading.Lock()


def get_trace_manager() -> TraceManager:
    """Retorna la instancia singleton global del TraceManager."""
    global _trace_manager
    if _trace_manager is None:
        with _trace_manager_lock:
            if _trace_manager is None:
                _trace_manager = TraceManager()
    return _trace_manager
