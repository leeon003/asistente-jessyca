"""JsonlTraceExporter — Exporter de spans al canal TRACE en formato JSONL (Etapa 17.0).

Escribe un span JSON por línea en logs/jessyca_traces.jsonl.
Append-only. Thread-safe. Rotation no incluida en esta etapa (usa RotatingFileHandler futuro).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from core.logger import get_logger
from core.observability.span_models import Span

logger = get_logger("jessyca.observability.exporters.jsonl_trace")


class JsonlTraceExporter:
    """Exporter que serializa spans finalizados en un archivo JSONL append-only."""

    def __init__(self, file_path: Path | str) -> None:
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._file = self._path.open("a", encoding="utf-8", buffering=1)  # line-buffered
        logger.debug(f"JsonlTraceExporter iniciado → {self._path}")

    def emit(self, span: Span) -> None:
        """Serializa y escribe un span finalizado en el archivo JSONL."""
        try:
            line = json.dumps(span.to_dict(), ensure_ascii=False, default=str)
            with self._lock:
                self._file.write(line + "\n")
        except Exception as exc:
            logger.error(f"Error al escribir span en JSONL: {exc}")

    def flush(self) -> None:
        with self._lock:
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            try:
                self._file.flush()
                self._file.close()
            except Exception as exc:
                logger.error(f"Error al cerrar JsonlTraceExporter: {exc}")
