"""Validador y frontera de seguridad para operaciones OCR (OCRSecurityManager - Subetapa 08.2).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Aplica el principio FAIL-SAFE DENY sobre parámetros de solicitud OCR, dimensiones, regiones,
coordenadas, confianzas y tamaños de entrada.
Rechaza explícitamente NaN, Infinity, coordenadas negativas, overflow de enteros y dimensiones gigantes.
"""

from __future__ import annotations

import math
import sys

from config.settings import AppSettings
from core.desktop_models import OCRBoundingBox, OCRRequest
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.ocr_security")


class OCRSecurityError(MCPError):
    """Error base de la frontera de seguridad OCR."""

    pass


class OCRLimitExceededError(OCRSecurityError):
    """Error emitido cuando una solicitud OCR excede límites de dimensiones, caracteres o regiones."""

    pass


class OCRSecurityManager:
    """Validador estricto de seguridad para solicitudes y regiones de reconocimiento OCR."""

    def __init__(self) -> None:
        settings = AppSettings()
        self.max_width: int = settings.OCR_MAX_SCREEN_WIDTH
        self.max_height: int = settings.OCR_MAX_SCREEN_HEIGHT
        self.max_regions: int = settings.OCR_MAX_REGIONS
        self.max_text_length: int = settings.OCR_MAX_TEXT_LENGTH
        self.max_input_bytes: int = settings.OCR_MAX_INPUT_BYTES
        self.min_confidence: float = settings.OCR_MIN_CONFIDENCE

    def validate_request(self, request: OCRRequest) -> OCRRequest:
        """Valida rigurosamente la solicitud OCR.

        FAIL-SAFE DENY: Lanza OCRSecurityError ante cualquier incoherencia o desbordamiento.
        """
        # 1. Validación de coordenadas x, y (Enteros no negativos, no booleanos)
        if not isinstance(request.x, int) or isinstance(request.x, bool) or request.x < 0:
            raise OCRSecurityError(f"Coordenada OCR 'x' inválida o negativa: {request.x}")

        if not isinstance(request.y, int) or isinstance(request.y, bool) or request.y < 0:
            raise OCRSecurityError(f"Coordenada OCR 'y' inválida o negativa: {request.y}")

        # 2. Validación de dimensiones si se especifican
        if request.width is not None:
            if not isinstance(request.width, int) or isinstance(request.width, bool) or request.width <= 0:
                raise OCRSecurityError(f"Dimensión OCR 'width' debe ser un entero positivo: {request.width}")
            if request.width > self.max_width:
                raise OCRLimitExceededError(f"Dimensión OCR 'width' excede el máximo permitido ({request.width} > {self.max_width}).")

        if request.height is not None:
            if not isinstance(request.height, int) or isinstance(request.height, bool) or request.height <= 0:
                raise OCRSecurityError(f"Dimensión OCR 'height' debe ser un entero positivo: {request.height}")
            if request.height > self.max_height:
                raise OCRLimitExceededError(f"Dimensión OCR 'height' excede el máximo permitido ({request.height} > {self.max_height}).")

        # 3. Verificación de tamaño de payload base64 si se proporciona
        if request.image_base64 is not None:
            if not isinstance(request.image_base64, str):
                raise OCRSecurityError("Payload 'image_base64' debe ser una cadena.")
            if len(request.image_base64.encode("utf-8")) > self.max_input_bytes:
                raise OCRLimitExceededError("Payload de imagen base64 para OCR excede el tamaño máximo permitido.")

        return request

    def validate_bounding_box(self, box: OCRBoundingBox) -> OCRBoundingBox:
        """Valida que una caja delimitadora tenga coordenadas válidas sin NaN, Infinity ni desbordamiento."""
        for name, val in [("x", box.x), ("y", box.y)]:
            if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                raise OCRSecurityError(f"Valor de bounding box '{name}' inválido o negativo: {val}")

        for name, val in [("width", box.width), ("height", box.height)]:
            if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
                raise OCRSecurityError(f"Valor de bounding box '{name}' debe ser positivo: {val}")

        if box.x > sys.maxsize - box.width or box.y > sys.maxsize - box.height:
            raise OCRLimitExceededError("Desbordamiento detectado en las coordenadas de la bounding box.")

        return box

    def validate_confidence(self, confidence: float) -> float:
        """Valida y normaliza el nivel de confianza (0.0 - 1.0). Revisa NaN o Infinity."""
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise OCRSecurityError(f"Confianza de OCR inválida: {confidence}")

        val = float(confidence)
        if math.isnan(val) or math.isinf(val):
            raise OCRSecurityError(f"Confianza de OCR no puede ser NaN ni Infinity: {confidence}")

        # Normalizar rango 0-100 a 0.0-1.0 si es necesario
        if val > 1.0:
            val = val / 100.0

        if not (0.0 <= val <= 1.0):
            raise OCRSecurityError(f"Confianza de OCR fuera de rango [0.0 - 1.0]: {val}")

        return val
