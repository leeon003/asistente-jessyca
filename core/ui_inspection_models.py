"""Modelos inmutables para inspección visual de elementos UI (`windows.desktop` - Subetapa 08.3).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Modelos congelados e inmutables (`@dataclass(frozen=True)`). No realizan acciones UI ni almacenan secretos.
Incorpora hashing de estado (state_hash) y timestamps para la detección de cambios visuales y objetivos obsoletos.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class UIDetectionSource(StrEnum):
    """Origen de detección del elemento de interfaz gráfica."""

    UI_AUTOMATION = "UI_AUTOMATION"
    OCR = "OCR"
    HYBRID = "HYBRID"
    SCREENSHOT = "SCREENSHOT"


class UIControlType(StrEnum):
    """Enumeración controlada de tipos de elementos de interfaz gráfica."""

    WINDOW = "Window"
    BUTTON = "Button"
    EDIT = "Edit"
    TEXT = "Text"
    CHECKBOX = "CheckBox"
    RADIOBUTTON = "RadioButton"
    COMBOBOX = "ComboBox"
    LIST = "List"
    LISTITEM = "ListItem"
    TAB = "Tab"
    MENU = "Menu"
    MENUITEM = "MenuItem"
    TREE = "Tree"
    TREEITEM = "TreeItem"
    IMAGE = "Image"
    HYPERLINK = "Hyperlink"
    UNKNOWN = "Unknown"

    @classmethod
    def from_str(cls, value: str | None) -> UIControlType:
        """Convierte una cadena a un UIControlType de forma conservadora (FAIL-SAFE)."""
        if not value:
            return cls.UNKNOWN
        val_clean = str(value).strip()
        for member in cls:
            if member.value.lower() == val_clean.lower():
                return member
        return cls.UNKNOWN


@dataclass(frozen=True)
class UIElementBounds:
    """Caja delimitadora inmutable de la posición y dimensión de un elemento UI en pantalla."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        """Coordenada X del borde derecho."""
        return self.x + self.width

    @property
    def bottom(self) -> int:
        """Coordenada Y del borde inferior."""
        return self.y + self.height

    def to_dict(self) -> dict[str, Any]:
        """Convierte la bounding box a diccionario estructurado."""
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "right": self.right,
            "bottom": self.bottom,
        }


@dataclass(frozen=True)
class WindowInfo:
    """Información inmutable de una ventana principal de la interfaz gráfica."""

    hwnd: int
    title: str
    class_name: str
    process_id: int
    bounds: UIElementBounds
    is_active: bool
    is_minimized: bool
    is_maximized: bool
    is_visible: bool
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convierte la información de ventana a diccionario estructurado."""
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "class_name": self.class_name,
            "process_id": self.process_id,
            "bounds": self.bounds.to_dict(),
            "is_active": self.is_active,
            "is_minimized": self.is_minimized,
            "is_maximized": self.is_maximized,
            "is_visible": self.is_visible,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class DetectedUIElement:
    """Elemento UI individual detectado con fingerprint de estado para detección de cambios visuales."""

    element_id: str
    control_type: UIControlType
    bounds: UIElementBounds
    name: str
    automation_id: str
    class_name: str
    confidence: float
    owner_hwnd: int
    owner_window_title: str
    detection_source: UIDetectionSource
    timestamp: datetime
    state_hash: str
    is_enabled: bool = True
    is_offscreen: bool = False
    has_keyboard_focus: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convierte el elemento detectado a diccionario estructurado."""
        return {
            "element_id": self.element_id,
            "control_type": str(self.control_type),
            "bounds": self.bounds.to_dict(),
            "name": self.name,
            "automation_id": self.automation_id,
            "class_name": self.class_name,
            "confidence": self.confidence,
            "owner_hwnd": self.owner_hwnd,
            "owner_window_title": self.owner_window_title,
            "detection_source": str(self.detection_source),
            "timestamp": self.timestamp.isoformat(),
            "state_hash": self.state_hash,
            "is_enabled": self.is_enabled,
            "is_offscreen": self.is_offscreen,
            "has_keyboard_focus": self.has_keyboard_focus,
        }


@dataclass(frozen=True)
class UIElementRequest:
    """Parámetros de solicitud inmutables para inspección visual de elementos UI."""

    window_title: str | None = None
    control_type: str | None = None
    max_depth: int = 20
    max_elements: int = 1000

    def to_dict(self) -> dict[str, Any]:
        """Convierte la solicitud a diccionario estructurado."""
        return {
            "window_title": self.window_title,
            "control_type": self.control_type,
            "max_depth": self.max_depth,
            "max_elements": self.max_elements,
        }


@dataclass(frozen=True)
class UIElementInfo:
    """Información inmutable detallada de un elemento UI inspeccionado."""

    automation_id: str
    name: str
    control_type: UIControlType
    class_name: str
    bounds: UIElementBounds
    is_enabled: bool
    is_offscreen: bool
    has_keyboard_focus: bool
    process_id: int
    framework_id: str
    children: tuple[UIElementInfo, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Convierte los metadatos del elemento UI a diccionario estructurado."""
        return {
            "automation_id": self.automation_id,
            "name": self.name,
            "control_type": self.control_type.value,
            "class_name": self.class_name,
            "bounds": self.bounds.to_dict(),
            "is_enabled": self.is_enabled,
            "is_offscreen": self.is_offscreen,
            "has_keyboard_focus": self.has_keyboard_focus,
            "process_id": self.process_id,
            "framework_id": self.framework_id,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass(frozen=True)
class UIElementTree:
    """Jerarquía inmutable de elementos UI."""

    root: UIElementInfo

    def to_dict(self) -> dict[str, Any]:
        """Convierte el árbol completo a diccionario estructurado."""
        return {
            "root": self.root.to_dict(),
        }


@dataclass(frozen=True)
class UIInspectionMetadata:
    """Metadatos inmutables del proceso de inspección UI."""

    element_count: int
    max_depth_reached: int
    processing_time_ms: float
    backend_name: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convierte los metadatos a diccionario seguro para auditoría."""
        return {
            "element_count": self.element_count,
            "max_depth_reached": self.max_depth_reached,
            "processing_time_ms": round(self.processing_time_ms, 2),
            "backend_name": self.backend_name,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class UIInspectionResult:
    """Resultado inmutable completo de la inspección visual UI."""

    tree: UIElementTree
    elements_flat: tuple[UIElementInfo, ...]
    metadata: UIInspectionMetadata
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado de inspección UI a diccionario estructurado."""
        return {
            "tree": self.tree.to_dict(),
            "elements_count": len(self.elements_flat),
            "metadata": self.metadata.to_dict(),
            "truncated": self.truncated,
        }


def compute_ui_state_hash(hwnd: int, title: str, bounds: UIElementBounds, control_type: str) -> str:
    """Calcula un hash criptográfico SHA-256 para fingerprinting de estado visual e inspección de cambios."""
    raw = f"{hwnd}:{title}:{bounds.x}:{bounds.y}:{bounds.width}:{bounds.height}:{control_type}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
