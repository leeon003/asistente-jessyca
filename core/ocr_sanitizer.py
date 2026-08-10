"""Sanitizador y redactor de secretos para resultados de texto OCR (OCRTextSanitizer - Subetapa 08.2).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Normaliza la codificación UTF-8, elimina caracteres de control y aplica SecretRedactor
sobre todo el texto OCR reconocido y sobre las regiones individuales para redactar automáticamente
contraseñas, API keys, tokens, private keys y credenciales detectadas visualmente.
"""

from __future__ import annotations

import re

from core.command_output import SecretRedactor
from core.desktop_models import OCRTextRegion
from core.logger import get_logger

logger = get_logger("jessyca.core.ocr_sanitizer")

# Regex para eliminación de caracteres de control (NUL, SOH, etc. excepto saltos de línea e imprimibles)
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


class OCRTextSanitizer:
    """Sanitizador de texto y redactor de secretos para salidas OCR (Subetapa 08.2)."""

    @staticmethod
    def sanitize_text(text: str) -> tuple[str, int]:
        """Normaliza codificación UTF-8, elimina caracteres de control y redacta secretos.

        Retorna (texto_sanitizado, conteo_de_redacciones).
        """
        if not text:
            return "", 0

        # 1. Normalización UTF-8 y eliminación de caracteres de control
        clean_text = text.encode("utf-8", errors="replace").decode("utf-8")
        clean_text = CONTROL_CHAR_PATTERN.sub("", clean_text)

        # 2. Redacción de secretos mediante SecretRedactor
        sanitized, count = SecretRedactor.redact(clean_text)
        return sanitized, count

    @classmethod
    def sanitize_regions(cls, regions: tuple[OCRTextRegion, ...]) -> tuple[tuple[OCRTextRegion, ...], int]:
        """Sanitiza y redacta los datos sensibles en cada región individual respetando sus coordenadas."""
        sanitized_regions: list[OCRTextRegion] = []
        total_redactions = 0

        for region in regions:
            clean_text, count = cls.sanitize_text(region.text)
            total_redactions += count

            sanitized_regions.append(
                OCRTextRegion(
                    text=clean_text,
                    bounding_box=region.bounding_box,
                    confidence=region.confidence,
                )
            )

        return tuple(sanitized_regions), total_redactions
