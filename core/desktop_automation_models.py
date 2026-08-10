"""Modelos inmutables para la frontera de automatización de escritorio (`windows.desktop` - Subetapa 08.4).

GARANTÍA ABSOLUTA DE SEGURIDAD Y PRIVACIDAD:
Modelos inmutables (`@dataclass(frozen=True)`). No almacenan secretos en representaciones o auditorías.
Vinculación criptográfica mediante huella SHA-256 (`action_fingerprint`).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class DesktopActionType(StrEnum):
    """Enumeración controlada de acciones gráficas de automatización."""

    CLICK_ELEMENT = "click_element"
    TYPE_TEXT = "type_text"
    FOCUS_WINDOW = "focus_window"
    DRAG_AND_DROP = "drag_and_drop"

    @classmethod
    def from_str(cls, value: str | None) -> DesktopActionType:
        """Convierte una cadena a un DesktopActionType de forma conservadora (FAIL-SAFE)."""
        if not value:
            raise ValueError("El tipo de acción no puede estar vacío.")
        val_clean = str(value).strip().lower()
        for member in cls:
            if member.value.lower() == val_clean or member.name.lower() == val_clean:
                return member
        raise ValueError(f"Tipo de acción de automatización no soportado: '{value}'")


@dataclass(frozen=True)
class DesktopActionTarget:
    """Identificador inmutable del objetivo visual sobre el cual se ejecuta una acción UI."""

    automation_id: str | None = None
    name: str | None = None
    control_type: str | None = None
    process_id: int | None = None
    window_handle: int | None = None
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None

    def to_summary(self) -> str:
        """Genera un resumen seguro sin exponer secretos para logs de auditoría."""
        parts: list[str] = []
        if self.automation_id:
            parts.append(f"auto_id={self.automation_id}")
        if self.control_type:
            parts.append(f"type={self.control_type}")
        if self.process_id:
            parts.append(f"pid={self.process_id}")
        if self.x is not None and self.y is not None:
            parts.append(f"pos=({self.x},{self.y})")
        return " | ".join(parts) if parts else "Target (unspecified)"

    def to_dict(self) -> dict[str, Any]:
        """Convierte el objetivo a diccionario estructurado."""
        return {
            "automation_id": self.automation_id,
            "name": self.name,
            "control_type": self.control_type,
            "process_id": self.process_id,
            "window_handle": self.window_handle,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class DesktopActionRequest:
    """Solicitud inmutable para la ejecución de una acción gráfica controlada."""

    action_type: DesktopActionType
    target: DesktopActionTarget
    text: str | None = None
    dest_x: int | None = None
    dest_y: int | None = None
    duration_ms: float = 100.0

    def to_dict(self, safe_privacy: bool = True) -> dict[str, Any]:
        """Convierte la solicitud a diccionario estructurado.

        INVARIANTE DE PRIVACIDAD: Si safe_privacy=True, NUNCA expone el texto crudo escrito por type_text.
        """
        dict_rep: dict[str, Any] = {
            "action_type": self.action_type.value,
            "target": self.target.to_dict(),
            "dest_x": self.dest_x,
            "dest_y": self.dest_y,
            "duration_ms": self.duration_ms,
        }

        if self.text is not None:
            if safe_privacy:
                dict_rep["text_length"] = len(self.text)
                dict_rep["text_hash"] = hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:12]
            else:
                dict_rep["text"] = self.text

        return dict_rep


@dataclass(frozen=True)
class DesktopActionMetadata:
    """Metadatos inmutables de la ejecución de una acción gráfica."""

    action_type: str
    target_summary: str
    action_fingerprint: str
    processing_time_ms: float
    backend_name: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convierte los metadatos a diccionario seguro para auditoría."""
        return {
            "action_type": self.action_type,
            "target_summary": self.target_summary,
            "action_fingerprint": self.action_fingerprint,
            "processing_time_ms": round(self.processing_time_ms, 2),
            "backend_name": self.backend_name,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class DesktopActionResult:
    """Resultado inmutable de la ejecución de una acción de automatización de escritorio."""

    success: bool
    metadata: DesktopActionMetadata
    message: str

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado a diccionario estructurado."""
        return {
            "success": self.success,
            "metadata": self.metadata.to_dict(),
            "message": self.message,
        }


def generate_action_fingerprint(
    tool_name: str,
    action_type: str,
    target_dict: dict[str, Any],
    arguments_dict: dict[str, Any],
    request_id: str,
) -> str:
    """Genera una firma criptográfica SHA-256 inmutable para vinculación con AuthorizationEvidence."""
    payload = {
        "tool_name": str(tool_name).strip().lower(),
        "action_type": str(action_type).strip().lower(),
        "target": target_dict,
        "arguments": arguments_dict,
        "request_id": str(request_id).strip(),
    }
    dumped = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()
