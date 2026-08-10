"""Modelos inmutables para automatización y captura de visión de escritorio (`windows.desktop` - Subetapa 08.1).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Modelos inmutables (`@dataclass(frozen=True)`). No almacenan contraseñas, secretos ni datos
innecesarios del entorno.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ScreenshotRequest:
    """Parámetros de solicitud inmutables para captura de pantalla de escritorio."""

    x: int = 0
    y: int = 0
    width: int | None = None
    height: int | None = None
    format: str = "PNG"
    quality: int = 85

    def to_dict(self) -> dict[str, Any]:
        """Convierte la solicitud a diccionario estructurado."""
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "quality": self.quality,
        }


@dataclass(frozen=True)
class ScreenshotMetadata:
    """Metadatos inmutables de la imagen capturada de pantalla."""

    width: int
    height: int
    format: str
    size_bytes: int
    pixel_count: int
    timestamp: datetime
    backend: str

    def to_dict(self) -> dict[str, Any]:
        """Convierte los metadatos a diccionario seguro (sin datos binarios de la imagen)."""
        return {
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "size_bytes": self.size_bytes,
            "pixel_count": self.pixel_count,
            "timestamp": self.timestamp.isoformat(),
            "backend": self.backend,
        }


@dataclass(frozen=True)
class ScreenshotResult:
    """Resultado inmutable de la captura de pantalla de escritorio."""

    metadata: ScreenshotMetadata
    image_base64: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado completo a diccionario estructurado."""
        return {
            "metadata": self.metadata.to_dict(),
            "image_base64": self.image_base64,
        }


# =====================================================================
# MODELOS OCR (SUBETAPA 08.2)
# =====================================================================


@dataclass(frozen=True)
class OCRRequest:
    """Parámetros de solicitud inmutables para extracción OCR de texto."""

    x: int = 0
    y: int = 0
    width: int | None = None
    height: int | None = None
    language: str = "eng"
    image_base64: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convierte la solicitud OCR a un diccionario estructurado (sin base64 masivo)."""
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "language": self.language,
            "has_image_base64": self.image_base64 is not None,
        }


@dataclass(frozen=True)
class OCRBoundingBox:
    """Caja delimitadora inmutable de la posición de un texto en pantalla."""

    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict[str, Any]:
        """Convierte la bounding box a diccionario estructurado."""
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class OCRTextRegion:
    """Región individual de texto reconocido con bounding box y confianza."""

    text: str
    bounding_box: OCRBoundingBox
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        """Convierte la región OCR a diccionario estructurado."""
        return {
            "text": self.text,
            "bounding_box": self.bounding_box.to_dict(),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class OCRMetadata:
    """Metadatos inmutables del proceso de reconocimiento OCR."""

    char_count: int
    region_count: int
    avg_confidence: float
    processing_time_ms: float
    backend_name: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convierte los metadatos OCR a diccionario seguro para auditoría."""
        return {
            "char_count": self.char_count,
            "region_count": self.region_count,
            "avg_confidence": round(self.avg_confidence, 4),
            "processing_time_ms": round(self.processing_time_ms, 2),
            "backend_name": self.backend_name,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class OCRResult:
    """Resultado inmutable completo de la extracción OCR."""

    recognized_text: str
    regions: tuple[OCRTextRegion, ...]
    metadata: OCRMetadata
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado OCR a diccionario estructurado."""
        return {
            "recognized_text": self.recognized_text,
            "regions": [r.to_dict() for r in self.regions],
            "metadata": self.metadata.to_dict(),
            "truncated": self.truncated,
        }
