"""Modelos e interfaces inmutables para ejecutores de ratón y teclado (Subetapa 08.4).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Modelos inmutables (`@dataclass(frozen=True)`).
Prohíbe la invocación directa de clics/teclas con coordenadas mágicas sin un ValidatedTarget inspeccionado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from core.exceptions import MCPError
from core.ui_inspection_models import UIElementBounds


class ActionGuardValidationError(MCPError):
    """Error emitido cuando una acción no supera las validaciones de ActionGuard."""

    pass


class TargetNotFoundError(ActionGuardValidationError):
    """Error emitido cuando el objetivo especificado no existe o no es visible."""

    pass


class StaleTargetError(ActionGuardValidationError):
    """Error emitido cuando la posición o el estado visual del objetivo ha cambiado desde su inspección."""

    pass


class InsufficientConfidenceError(ActionGuardValidationError):
    """Error emitido cuando el nivel de confianza de detección del objetivo es inferior al umbral mínimo."""

    pass


class ActionTimeoutError(ActionGuardValidationError):
    """Error emitido cuando una acción excede el tiempo límite de ejecución configurado."""

    pass


@dataclass(frozen=True)
class ValidatedTarget:
    """Objetivo de automatización gráfica totalmente inspeccionado y validado."""

    hwnd: int
    owner_title: str
    bounds: UIElementBounds
    confidence: float
    state_hash: str
    timestamp: datetime
    automation_id: str | None = None
    control_type: str | None = None

    @property
    def center_x(self) -> int:
        """Coordenada X del centro del objetivo."""
        return self.bounds.x + (self.bounds.width // 2)

    @property
    def center_y(self) -> int:
        """Coordenada Y del centro del objetivo."""
        return self.bounds.y + (self.bounds.height // 2)

    def to_dict(self) -> dict[str, Any]:
        """Convierte el objetivo validado a diccionario estructurado."""
        return {
            "hwnd": self.hwnd,
            "owner_title": self.owner_title,
            "bounds": self.bounds.to_dict(),
            "center_pos": (self.center_x, self.center_y),
            "confidence": self.confidence,
            "state_hash": self.state_hash,
            "timestamp": self.timestamp.isoformat(),
            "automation_id": self.automation_id,
            "control_type": self.control_type,
        }


class IMouseExecutor(Protocol):
    """Protocolo abstracto para el ejecutor de acciones de ratón."""

    def move(self, x: int, y: int) -> None:
        """Mueve el puntero del ratón a una posición especificada."""
        ...

    def click(self, x: int, y: int, button: str = "left") -> None:
        """Realiza un clic de ratón en una posición especificada."""
        ...

    def double_click(self, x: int, y: int) -> None:
        """Realiza un doble clic de ratón en una posición especificada."""
        ...


class IKeyboardExecutor(Protocol):
    """Protocolo abstracto para el ejecutor de acciones de teclado."""

    def key_press(self, key: str) -> None:
        """Presiona y libera una tecla individual de forma segura."""
        ...

    def hotkey(self, keys: tuple[str, ...]) -> None:
        """Ejecuta una combinación secuencial de teclas (hotkey)."""
        ...

    def type_text(self, text: str) -> None:
        """Escribe una cadena de texto en el foco activo."""
        ...
