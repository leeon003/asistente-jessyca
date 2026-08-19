"""JsonlSecurityEventExporter — Exporter de SecurityEvents en formato JSONL (Etapa 17.0).

Escribe un SecurityEvent JSON por línea en logs/jessyca_security.jsonl.
Append-only. Thread-safe.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from core.logger import get_logger
from core.observability.security_event_models import SecurityEvent

logger = get_logger("jessyca.observability.exporters.jsonl_security_event")


class JsonlSecurityEventExporter:
    """Exporter que serializa SecurityEvents en un archivo JSONL append-only."""

    def __init__(self, file_path: Path | str) -> None:
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._file = self._path.open("a", encoding="utf-8", buffering=1)
        logger.debug(f"JsonlSecurityEventExporter iniciado → {self._path}")

    def emit(self, event: SecurityEvent) -> None:
        try:
            line = json.dumps(event.to_dict(), ensure_ascii=False, default=str)
            with self._lock:
                self._file.write(line + "\n")
        except Exception as exc:
            logger.error(f"Error al escribir security event en JSONL: {exc}")

    def flush(self) -> None:
        with self._lock:
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            try:
                self._file.flush()
                self._file.close()
            except Exception as exc:
                logger.error(f"Error al cerrar JsonlSecurityEventExporter: {exc}")
