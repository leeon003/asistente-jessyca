"""Backends desacoplados de captura de pantalla (Subetapa 08.1).

GARANTÍA ABSOLUTA DE SEGURIDAD:
NO utiliza subprocess, os.system, os.popen, shell=True, cmd.exe ni powershell.exe.
La captura se realiza directamente desde Python utilizando bibliotecas nativas de imagen o un backend sintetico de pruebas.
"""

from __future__ import annotations

import base64
import io
from datetime import UTC, datetime
from typing import Protocol

from core.desktop_models import ScreenshotMetadata, ScreenshotRequest, ScreenshotResult
from core.logger import get_logger

logger = get_logger("jessyca.tools.desktop.backend")


class IDesktopCaptureBackend(Protocol):
    """Protocolo abstracto para backends de captura de pantalla del escritorio."""

    def capture_screenshot(self, request: ScreenshotRequest) -> ScreenshotResult:
        """Realiza la captura de pantalla según los parámetros validados."""
        ...


class FakeDesktopCaptureBackend:
    """Backend sintético seguro para pruebas multiplataforma en memoria sin entorno gráfico de Windows."""

    def __init__(self, default_width: int = 1920, default_height: int = 1080) -> None:
        self.default_width = default_width
        self.default_height = default_height

    def capture_screenshot(self, request: ScreenshotRequest) -> ScreenshotResult:
        """Genera una imagen sintética de prueba en formato base64."""
        w = request.width or self.default_width
        h = request.height or self.default_height
        pixel_count = w * h

        # Crear un payload PNG sintético de prueba mínimo en bytes
        fake_png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
        b64_str = base64.b64encode(fake_png_bytes).decode("ascii")

        metadata = ScreenshotMetadata(
            width=w,
            height=h,
            format=request.format,
            size_bytes=len(fake_png_bytes),
            pixel_count=pixel_count,
            timestamp=datetime.now(UTC),
            backend="FakeDesktopCaptureBackend",
        )

        return ScreenshotResult(metadata=metadata, image_base64=b64_str)


class WindowsDesktopCaptureBackend:
    """Backend nativo para captura de pantalla de Windows utilizando PIL / ImageGrab en memoria."""

    def capture_screenshot(self, request: ScreenshotRequest) -> ScreenshotResult:
        """Realiza la captura de pantalla nativa mediante Pillow ImageGrab."""
        try:
            from PIL import ImageGrab
        except ImportError:
            logger.warning("Pillow no está disponible. Delegando a FakeDesktopCaptureBackend.")
            return FakeDesktopCaptureBackend().capture_screenshot(request)

        bbox = None
        if request.width is not None and request.height is not None:
            bbox = (request.x, request.y, request.x + request.width, request.y + request.height)

        img = ImageGrab.grab(bbox=bbox)
        w, h = img.size
        pixel_count = w * h

        buffer = io.BytesIO()
        save_format = request.format if request.format != "JPG" else "JPEG"
        img.save(buffer, format=save_format, quality=request.quality)
        raw_bytes = buffer.getvalue()

        b64_str = base64.b64encode(raw_bytes).decode("ascii")

        metadata = ScreenshotMetadata(
            width=w,
            height=h,
            format=request.format,
            size_bytes=len(raw_bytes),
            pixel_count=pixel_count,
            timestamp=datetime.now(UTC),
            backend="WindowsDesktopCaptureBackend",
        )

        return ScreenshotResult(metadata=metadata, image_base64=b64_str)
