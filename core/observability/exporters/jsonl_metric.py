"""JsonlMetricExporter — Exporter de snapshots de métricas en formato JSONL (Etapa 17.0).

Escribe un snapshot JSON de todas las métricas por línea en logs/jessyca_metrics.jsonl.
Llamado periódicamente (flush) por el ObservabilityManager.
Append-only. Thread-safe.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.observability.exporters.jsonl_metric")


class JsonlMetricExporter:
    """Exporter que serializa snapshots de métricas en un archivo JSONL append-only."""

    def __init__(self, file_path: Path | str) -> None:
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._file = self._path.open("a", encoding="utf-8", buffering=1)
        logger.debug(f"JsonlMetricExporter iniciado → {self._path}")

    def emit(self, snapshot: dict[str, Any]) -> None:
        """Escribe un snapshot de métricas con timestamp de captura."""
        try:
            record = {
                "snapshot_ts": datetime.now(UTC).isoformat(),
                **snapshot,
            }
            line = json.dumps(record, ensure_ascii=False, default=str)
            with self._lock:
                self._file.write(line + "\n")
        except Exception as exc:
            logger.error(f"Error al escribir snapshot de métricas en JSONL: {exc}")

    def flush(self) -> None:
        with self._lock:
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            try:
                self._file.flush()
                self._file.close()
            except Exception as exc:
                logger.error(f"Error al cerrar JsonlMetricExporter: {exc}")
