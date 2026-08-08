"""Context Manager para Jessyca Windows MCP.

Mantiene el estado temporal del usuario y del entorno de escritorio Windows
(ventana activa, archivo actual, última carpeta, última aplicación, captura, OCR, etc.)
de manera 100% independiente del LLM utilizado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.context")


@dataclass
class ContextItem:
    """Elemento individual de contexto almacenado con marcas temporales y TTL opcional."""

    key: str
    value: Any
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    ttl_seconds: float | None = None

    @property
    def is_expired(self) -> bool:
        """Indica si el elemento ha sobrepasado su tiempo de vida útil (TTL)."""
        if self.ttl_seconds is None:
            return False
        elapsed = (datetime.now(UTC) - self.timestamp).total_seconds()
        return elapsed > self.ttl_seconds


class ContextManager:
    """Gestor de contexto temporal independiente para el estado de conversación y sistema."""

    def __init__(self) -> None:
        self._items: dict[str, ContextItem] = {}

    # -------------------------------------------------------------------------
    # Operaciones CRUD Básicas
    # -------------------------------------------------------------------------

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        """Guarda o actualiza un valor en el contexto temporal.

        Args:
            key: Clave identificadora del contexto.
            value: Valor a almacenar.
            ttl_seconds: Tiempo de vida útil en segundos (opcional).
        """
        item = ContextItem(key=key, value=value, ttl_seconds=ttl_seconds)
        self._items[key] = item
        logger.debug(f"Contexto actualizado: '{key}' [TTL: {ttl_seconds}s]")

    def get(self, key: str, default: Any = None) -> Any:
        """Lee un valor del contexto si existe y no ha expirado.

        Args:
            key: Clave identificadora.
            default: Valor por defecto si no existe o expiró.

        Returns:
            Valor almacenado o default.
        """
        item = self._items.get(key)
        if item is None:
            return default

        if item.is_expired:
            logger.debug(f"Contexto expirado ignorado: '{key}'")
            self.delete(key)
            return default

        return item.value

    def has(self, key: str) -> bool:
        """Comprueba si una clave existe en el contexto y está vigente."""
        return self.get(key) is not None

    def delete(self, key: str) -> bool:
        """Elimina una clave del contexto."""
        if key in self._items:
            del self._items[key]
            logger.debug(f"Contexto eliminado: '{key}'")
            return True
        return False

    def clear(self) -> None:
        """Limpia todo el contexto almacenado."""
        self._items.clear()
        logger.info("Todo el contexto temporal ha sido limpiado.")

    def get_snapshot(self) -> dict[str, Any]:
        """Obtiene una copia instantánea en diccionario de todo el contexto vigente no expirado."""
        snapshot: dict[str, Any] = {}
        expired_keys = []

        for key, item in self._items.items():
            if item.is_expired:
                expired_keys.append(key)
            else:
                snapshot[key] = item.value

        # Limpieza diferida de elementos expirados
        for k in expired_keys:
            del self._items[k]

        return snapshot

    # -------------------------------------------------------------------------
    # Helpers Específicos para el Entorno de Escritorio Windows
    # -------------------------------------------------------------------------

    def set_active_window(
        self, window_title: str, process_name: str, pid: int | None = None
    ) -> None:
        """Registra la ventana activa actual del sistema operativo."""
        data = {
            "title": window_title,
            "process_name": process_name,
            "pid": pid,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self.set("active_window", data)

    def set_current_file(self, file_path: str | Path, mime_type: str | None = None) -> None:
        """Registra el archivo actual en foco o en trabajo."""
        p = Path(file_path).resolve()
        data = {
            "path": str(p),
            "name": p.name,
            "extension": p.suffix,
            "mime_type": mime_type,
            "exists": p.exists(),
        }
        self.set("current_file", data)

    def set_last_directory(self, directory_path: str | Path) -> None:
        """Registra el último directorio o carpeta abierta/navegada."""
        p = Path(directory_path).resolve()
        data = {
            "path": str(p),
            "name": p.name,
            "exists": p.exists(),
        }
        self.set("last_directory", data)

    def set_last_application(self, app_name: str, executable_path: str | None = None) -> None:
        """Registra la última aplicación abierta o interactuada."""
        data = {
            "name": app_name,
            "executable_path": executable_path,
        }
        self.set("last_application", data)

    def set_last_screenshot(
        self, image_path: str | Path, dimensions: tuple[int, int] | None = None
    ) -> None:
        """Registra la última captura de pantalla realizada."""
        p = Path(image_path).resolve()
        data = {
            "image_path": str(p),
            "dimensions": dimensions,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.set("last_screenshot", data)

    def set_last_ocr_result(self, text: str, language: str = "es") -> None:
        """Registra el último resultado de reconocimiento óptico de caracteres (OCR)."""
        data = {
            "text": text,
            "language": language,
            "char_count": len(text),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.set("last_ocr_result", data)
