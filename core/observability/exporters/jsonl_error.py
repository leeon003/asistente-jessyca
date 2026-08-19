"""JsonlErrorExporter — Exporter de ErrorRecords en formato JSONL (Etapa 17.0).

Escribe un ErrorRecord JSON por línea en logs/jessyca_errors.jsonl.
Append-only. Thread-safe.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from core.logger import get_logger
from core.observability.error_models import ErrorRecord

logger = get_logger("jessyca.observability.exporters.jsonl_error")


class JsonlErrorExporter:
    """Exporter que serializa ErrorRecords en un archivo JSONL append-only."""

    def __init__(self, file_path: Path | str) -> None:
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._file = self._path.open("a", encoding="utf-8", buffering=1)
        logger.debug(f"JsonlErrorExporter iniciado → {self._path}")

    def emit(self, record: ErrorRecord) -> None:
        try:
            line = json.dumps(record.to_dict(), ensure_ascii=False, default=str)
            with self._lock:
                self._file.write(line + "\n")
        except Exception as exc:
            logger.error(f"Error al escribir error record en JSONL: {exc}")

    def flush(self) -> None:
        with self._lock:
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            try:
                self._file.flush()
                self._file.close()
            except Exception as exc:
                logger.error(f"Error al cerrar JsonlErrorExporter: {exc}")
