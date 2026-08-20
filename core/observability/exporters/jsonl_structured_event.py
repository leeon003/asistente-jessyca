"""JsonlStructuredEventExporter — Exportador de StructuredEvent a archivo JSONL (Etapa 17.1).

Escribe cada evento estructurado serializado como una línea JSON en logs/jessyca_telemetry.jsonl.
Garantiza persistencia segura, thread-safe y formato machine-readable.
"""

from __future__ import annotations

import threading
from pathlib import Path

from core.logger import get_logger
from core.observability.structured_event import StructuredEvent

logger = get_logger("jessyca.observability.exporters.jsonl_structured_event")


class JsonlStructuredEventExporter:
    """Exportador append-only de StructuredEvent a un archivo JSONL."""

    def __init__(self, file_path: Path | str) -> None:
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._file = self._path.open("a", encoding="utf-8", buffering=1)  # line-buffered
        logger.debug(f"JsonlStructuredEventExporter iniciado → {self._path}")

    def emit(self, event: StructuredEvent) -> None:
        """Serializa y escribe un StructuredEvent en el archivo JSONL."""
        try:
            line = event.to_json()
            with self._lock:
                self._file.write(line + "\n")
        except Exception as exc:
            logger.error(f"Error al escribir StructuredEvent en JSONL: {exc}")

    def flush(self) -> None:
        """Fuerza el vaciado del buffer a disco."""
        with self._lock:
            try:
                self._file.flush()
            except Exception as exc:
                logger.error(f"Error en flush de JsonlStructuredEventExporter: {exc}")

    def close(self) -> None:
        """Cierra el descriptor de archivo de forma segura."""
        with self._lock:
            try:
                self._file.flush()
                self._file.close()
            except Exception as exc:
                logger.error(f"Error al cerrar JsonlStructuredEventExporter: {exc}")
