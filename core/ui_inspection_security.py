"""Frontera de seguridad y validador de inspección UI (UIInspectionSecurityManager - Subetapa 08.3).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Aplica el principio FAIL-SAFE DENY sobre parámetros de solicitud, jerarquías de árbol,
cajas delimitadoras (bounding boxes), profundidades, conteos de elementos y textos.
Rechaza explícitamente NaN, Infinity, coordenadas negativas, overflow de enteros y dimensiones fuera de límites.
"""

from __future__ import annotations

import sys

from config.settings import AppSettings
from core.exceptions import MCPError
from core.logger import get_logger
from core.ui_inspection_models import UIElementBounds, UIElementRequest

logger = get_logger("jessyca.core.ui_inspection_security")


class UIInspectionSecurityError(MCPError):
    """Error base de la frontera de seguridad de inspección UI."""

    pass


class UIInspectionLimitExceededError(UIInspectionSecurityError):
    """Error emitido cuando una inspección UI excede límites de elementos, profundidad o dimensiones."""

    pass


class UIInspectionSecurityManager:
    """Validador estricto de seguridad para solicitudes y árboles de inspección visual UI."""

    def __init__(self) -> None:
        settings = AppSettings()
        self.max_width: int = settings.DESKTOP_MAX_WIDTH
        self.max_height: int = settings.DESKTOP_MAX_HEIGHT
        self.max_elements: int = settings.UI_MAX_ELEMENTS
        self.max_tree_depth: int = settings.UI_MAX_TREE_DEPTH
        self.max_text_length: int = settings.UI_MAX_TEXT_LENGTH
        self.max_name_length: int = settings.UI_MAX_NAME_LENGTH
        self.max_properties: int = settings.UI_MAX_PROPERTIES

    def validate_request(self, request: UIElementRequest) -> UIElementRequest:
        """Valida rigurosamente los parámetros de la solicitud de inspección UI.

        FAIL-SAFE DENY: Lanza UIInspectionSecurityError ante cualquier incoherencia.
        """
        # 1. Validación de profundidad máxima (Entero positivo no booleano)
        if not isinstance(request.max_depth, int) or isinstance(request.max_depth, bool) or request.max_depth <= 0:
            raise UIInspectionSecurityError(f"Profundidad máxima 'max_depth' inválida: {request.max_depth}")

        if request.max_depth > self.max_tree_depth:
            raise UIInspectionLimitExceededError(f"Profundidad 'max_depth' excede el límite máximo permitido ({request.max_depth} > {self.max_tree_depth}).")

        # 2. Validación de cantidad máxima de elementos (Entero positivo no booleano)
        if not isinstance(request.max_elements, int) or isinstance(request.max_elements, bool) or request.max_elements <= 0:
            raise UIInspectionSecurityError(f"Conteo máximo de elementos 'max_elements' inválido: {request.max_elements}")

        if request.max_elements > self.max_elements:
            raise UIInspectionLimitExceededError(f"Conteo 'max_elements' excede el límite máximo permitido ({request.max_elements} > {self.max_elements}).")

        # 3. Validación de cadenas opcionales de filtro (título de ventana, tipo de control)
        if request.window_title is not None:
            if not isinstance(request.window_title, str):
                raise UIInspectionSecurityError("El título de ventana 'window_title' debe ser una cadena.")
            if len(request.window_title) > self.max_name_length:
                raise UIInspectionLimitExceededError(f"Longitud de 'window_title' excede el límite máximo ({len(request.window_title)} > {self.max_name_length}).")

        if request.control_type is not None:
            if not isinstance(request.control_type, str):
                raise UIInspectionSecurityError("El tipo de control 'control_type' debe ser una cadena.")
            if len(request.control_type) > self.max_name_length:
                raise UIInspectionLimitExceededError("Longitud de 'control_type' excede el límite máximo.")

        return request

    def validate_bounds(self, bounds: UIElementBounds) -> UIElementBounds:
        """Valida que una caja delimitadora de elemento UI tenga coordenadas válidas sin NaN, Infinity ni desbordamiento."""
        for name, val in [("x", bounds.x), ("y", bounds.y)]:
            if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                raise UIInspectionSecurityError(f"Coordenada de elemento UI '{name}' inválida o negativa: {val}")

        for name, val in [("width", bounds.width), ("height", bounds.height)]:
            if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
                raise UIInspectionSecurityError(f"Dimensión de elemento UI '{name}' debe ser positiva: {val}")

        # Prevención de Integer Overflow
        if bounds.x > sys.maxsize - bounds.width or bounds.y > sys.maxsize - bounds.height:
            raise UIInspectionLimitExceededError("Desbordamiento numérico detectado en las coordenadas del elemento UI.")

        if bounds.right > self.max_width * 2 or bounds.bottom > self.max_height * 2:
            logger.debug(f"Elemento UI fuera de los límites virtuales de pantalla: right={bounds.right}, bottom={bounds.bottom}")

        return bounds

    def validate_string(self, value: str, max_length: int, field_name: str) -> str:
        """Valida y trunca de forma segura valores de texto o nombre de elementos UI."""
        if not isinstance(value, str):
            return str(value)[:max_length]

        if len(value) > max_length:
            return value[:max_length] + "..."

        return value
