"""Jerarquía de excepciones tipadas para el pipeline de visión multimodal (core/vision/vision_exceptions.py - Fase 4).

Proporciona excepciones específicas para errores de entrada de imagen, timeouts, indisponibilidad del modelo
y respuestas corruptas o malformadas.
"""

from __future__ import annotations

from core.exceptions import MCPError


class VisionError(MCPError):
    """Excepción base para todos los errores del pipeline de visión multimodal."""

    pass


class VisionModelUnavailableError(VisionError):
    """Emitida cuando el modelo de visión (e.g. qwen3-vl:4b) no se encuentra disponible o no responde."""

    pass


class VisionTimeoutError(VisionError):
    """Emitida cuando la petición de análisis visual supera el tiempo límite configurado."""

    pass


class InvalidImageError(VisionError):
    """Emitida cuando la imagen suministrada tiene formato inválido, datos corruptos o no soportados."""

    pass


class EmptyScreenshotError(InvalidImageError):
    """Emitida cuando la captura de pantalla o buffer de imagen está vacío o tiene dimensiones nulas."""

    pass


class CorruptVisionResponseError(VisionError):
    """Emitida cuando la respuesta del modelo de visión es ininteligible o no puede estructurarse."""

    pass
