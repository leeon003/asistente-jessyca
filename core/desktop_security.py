"""Frontera de seguridad y validador de parámetros de escritorio (DesktopSecurityManager - Subetapa 08.1).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Aplica el principio FAIL-SAFE DENY sobre todos los parámetros de captura (x, y, width, height, formato).
Impide desbordamientos numéricos, dimensiones negativas, formatos no autorizados o capturas gigantes.
"""

from __future__ import annotations

import sys

from config.settings import AppSettings
from core.desktop_models import ScreenshotRequest
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.desktop_security")

ALLOWED_FORMATS: set[str] = {"PNG", "JPEG", "JPG", "WEBP"}


class DesktopSecurityError(MCPError):
    """Error base de la frontera de seguridad de escritorio."""

    pass


class DesktopLimitExceededError(DesktopSecurityError):
    """Error emitido cuando una captura excede los límites de píxeles o dimensiones configurados."""

    pass


class DesktopSecurityManager:
    """Validador estricto de parámetros y límites de captura de pantalla (Subetapa 08.1)."""

    def __init__(self) -> None:
        settings = AppSettings()
        self.max_width: int = settings.DESKTOP_MAX_WIDTH
        self.max_height: int = settings.DESKTOP_MAX_HEIGHT
        self.max_pixels: int = settings.DESKTOP_MAX_PIXELS
        self.max_bytes: int = settings.DESKTOP_MAX_CAPTURE_BYTES

    def validate_request(self, request: ScreenshotRequest) -> ScreenshotRequest:
        """Valida rigurosamente los parámetros de la solicitud de captura.

        FAIL-SAFE DENY: Lanza DesktopSecurityError ante cualquier incoherencia.
        """
        # 1. Validación de tipos y valores enteros no negativos de coordenadas
        if not isinstance(request.x, int) or isinstance(request.x, bool) or request.x < 0:
            raise DesktopSecurityError(f"Coordenada 'x' inválida o negativa: {request.x}")

        if not isinstance(request.y, int) or isinstance(request.y, bool) or request.y < 0:
            raise DesktopSecurityError(f"Coordenada 'y' inválida o negativa: {request.y}")

        # 2. Validación de dimensiones si se especifican
        if request.width is not None:
            if not isinstance(request.width, int) or isinstance(request.width, bool) or request.width <= 0:
                raise DesktopSecurityError(f"Dimensión 'width' debe ser un entero positivo: {request.width}")
            if request.width > self.max_width:
                raise DesktopLimitExceededError(f"Dimensión 'width' excede el máximo permitido ({request.width} > {self.max_width}).")

        if request.height is not None:
            if not isinstance(request.height, int) or isinstance(request.height, bool) or request.height <= 0:
                raise DesktopSecurityError(f"Dimensión 'height' debe ser un entero positivo: {request.height}")
            if request.height > self.max_height:
                raise DesktopLimitExceededError(f"Dimensión 'height' excede el máximo permitido ({request.height} > {self.max_height}).")

        # 3. Prevención de Integer Overflow y verificación de total de píxeles
        w = request.width or self.max_width
        h = request.height or self.max_height

        if w > sys.maxsize // h:
            raise DesktopLimitExceededError("Desbordamiento numérico detectado en el cálculo de área de píxeles.")

        pixel_count = w * h
        if pixel_count > self.max_pixels:
            raise DesktopLimitExceededError(f"El área total solicitada excede el límite máximo de píxeles ({pixel_count} > {self.max_pixels}).")

        # 4. Validación de formato y calidad
        fmt_upper = str(request.format).upper().strip()
        if fmt_upper not in ALLOWED_FORMATS:
            raise DesktopSecurityError(f"Formato de imagen no soportado: '{request.format}'. Formatos permitidos: {ALLOWED_FORMATS}")

        if not isinstance(request.quality, int) or isinstance(request.quality, bool) or not (1 <= request.quality <= 100):
            raise DesktopSecurityError(f"Calidad de imagen fuera de rango [1-100]: {request.quality}")

        return ScreenshotRequest(
            x=request.x,
            y=request.y,
            width=request.width,
            height=request.height,
            format=fmt_upper,
            quality=request.quality,
        )
