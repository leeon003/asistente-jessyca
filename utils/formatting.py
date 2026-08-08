"""Utilidades de formateo y sanitización de datos para Jessyca Windows MCP."""

from __future__ import annotations

import json
from typing import Any


def format_bytes(size_in_bytes: int) -> str:
    """Convierte una cantidad de bytes a una representación legible (KB, MB, GB)."""
    if size_in_bytes < 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_in_bytes)
    unit_index = 0

    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1

    return f"{size:.2f} {units[unit_index]}"


def sanitize_string(text: str) -> str:
    """Elimina caracteres de control no imprimibles de un string."""
    if not text:
        return ""
    return "".join(ch for ch in text if ch.isprintable() or ch in "\n\r\t").strip()


def to_json_pretty(data: dict[str, Any]) -> str:
    """Convierte un diccionario a JSON formateado con identación de 2 espacios."""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)
