"""ErrorRecorder — Canal ERROR (Etapa 17.0).

Crea y emite ErrorRecord estructurados con:
  - Sanitización del stack trace (solo módulo + función + línea)
  - Enriquecimiento automático desde ObservabilityContext
  - Deduplicación por hash (no registra el mismo error repetidamente)
  - Emisión al MemoryErrorSink + sinks adicionales

Thread-safe singleton.
"""

from __future__ import annotations

import re
import threading
import traceback
from typing import Any

from core.logger import get_logger
from core.observability.context import get_current_context
from core.observability.error_models import ErrorCategory, ErrorRecord

logger = get_logger("jessyca.observability.error_recorder")

# Regex para eliminar líneas de código fuente del traceback.
# Mantiene: líneas que empiezan con 'Traceback', '  File ', y los mensajes de excepción.
# Elimina: líneas de código fuente (indentadas sin 'File ') y sus valores de variable.
_TRACEBACK_CODE_LINE = re.compile(r"^\s{4,}(?!File\s).+$", re.MULTILINE)


def sanitize_stack_trace(exc: BaseException) -> str:
    """Extrae el stack trace de una excepción, manteniendo SOLO módulo + función + línea.

    Elimina las líneas de código fuente para evitar exponer valores de variables
    que podrían contener datos sensibles.

    Returns:
        Stack trace sanitizado, máximo 4000 caracteres.
    """
    try:
        raw_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        clean_lines = []
        for block in raw_lines:
            for line in block.splitlines(keepends=True):
                # Omitir líneas de código fuente (típicamente 4+ espacios de sangría que no son '  File ')
                stripped = line.strip()
                if line.startswith("    ") and not stripped.startswith("File "):
                    continue
                clean_lines.append(line)
        sanitized = "".join(clean_lines)
        sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
        return sanitized[:4000].strip()
    except Exception:
        return f"{type(exc).__name__}: {str(exc)[:500]}"


class MemoryErrorSink:
    """Store en memoria de error records. Thread-safe."""

    def __init__(self, max_size: int = 500) -> None:
        self._records: list[ErrorRecord] = []
        self._seen_hashes: set[str] = set()
        self._lock = threading.Lock()
        self._max_size = max_size

    def emit(self, record: ErrorRecord) -> bool:
        """Emite un error record. Retorna False si ya fue visto (dedup por hash)."""
        with self._lock:
            if record.event_hash in self._seen_hashes:
                return False
            if len(self._records) >= self._max_size:
                # FIFO: eliminar el más antiguo
                old = self._records.pop(0)
                self._seen_hashes.discard(old.event_hash)
            self._records.append(record)
            self._seen_hashes.add(record.event_hash)
            return True

    def get_all(self) -> list[ErrorRecord]:
        with self._lock:
            return list(self._records)

    def get_by_category(self, category: ErrorCategory | str) -> list[ErrorRecord]:
        cat_str = getattr(category, "value", str(category))
        with self._lock:
            return [r for r in self._records if str(r.error_category) == cat_str]

    def get_by_component(self, component: str) -> list[ErrorRecord]:
        with self._lock:
            return [r for r in self._records if r.component == component]

    def get_by_correlation(self, correlation_id: str) -> list[ErrorRecord]:
        with self._lock:
            return [r for r in self._records if r.correlation_id == correlation_id]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._seen_hashes.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)


class ErrorRecorder:
    """Grabador de errores estructurados del canal ERROR.

    Uso:
        try:
            ...
        except SomeError as e:
            get_error_recorder().record(
                exc=e,
                component="boundary.registry",
                error_category=ErrorCategory.SECURITY,
                tool_name="registry.write",
                operation="set_value",
                is_recoverable=False,
                recovery_action="abort",
            )
    """

    def __init__(self) -> None:
        self._memory_sink = MemoryErrorSink()
        self._sinks: list[Any] = [self._memory_sink]
        self._lock = threading.Lock()

    def register_sink(self, sink: Any) -> None:
        with self._lock:
            self._sinks.append(sink)

    def record(
        self,
        exc: BaseException,
        component: str,
        error_category: ErrorCategory | str = ErrorCategory.RUNTIME,
        tool_name: str = "",
        operation: str = "",
        is_recoverable: bool = False,
        recovery_action: str = "abort",
        context: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        session_id: str | None = None,
        action_id: str | None = None,
        task_id: str | None = None,
        plugin_id: str | None = None,
    ) -> ErrorRecord:
        """Crea y emite un ErrorRecord a partir de una excepción.

        Infiere correlation_id / session_id / action_id / task_id del
        ObservabilityContext activo si no se proveen.
        """
        ctx = get_current_context()
        stack = sanitize_stack_trace(exc)

        record = ErrorRecord(
            component=component,
            error_type=type(exc).__name__,
            error_category=error_category,
            message=str(exc)[:1000],  # sanitizado y limitado
            tool_name=tool_name,
            operation=operation,
            stack_trace=stack,
            is_recoverable=is_recoverable,
            recovery_action=recovery_action,
            correlation_id=correlation_id or (ctx.correlation_id if ctx else ""),
            session_id=session_id or (ctx.session_id if ctx else ""),
            task_id=task_id or (ctx.task_id if ctx else None),
            action_id=action_id or (ctx.action_id if ctx else None),
            plugin_id=plugin_id or (ctx.plugin_id if ctx else None),
            context=dict(context or {}),
        )

        self._dispatch(record)
        logger.error(
            f"[ERROR] {record.error_type} in {component}: {record.message[:200]}",
            extra={
                "error_id": record.error_id,
                "correlation_id": record.correlation_id,
                "component": component,
                "error_category": str(error_category),
            },
        )
        return record

    def get_memory_sink(self) -> MemoryErrorSink:
        return self._memory_sink

    def _dispatch(self, record: ErrorRecord) -> None:
        sinks = list(self._sinks)
        for sink in sinks:
            try:
                sink.emit(record)
            except Exception as exc:
                logger.error(f"Error en sink de error records {type(sink).__name__}: {exc}")


# Singleton global
_error_recorder: ErrorRecorder | None = None
_error_recorder_lock = threading.Lock()


def get_error_recorder() -> ErrorRecorder:
    """Retorna la instancia singleton global del ErrorRecorder."""
    global _error_recorder
    if _error_recorder is None:
        with _error_recorder_lock:
            if _error_recorder is None:
                _error_recorder = ErrorRecorder()
    return _error_recorder
