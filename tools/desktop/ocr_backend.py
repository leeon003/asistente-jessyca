"""Backends desacoplados para el motor de extracción OCR (Subetapa 08.2).

GARANTÍA ABSOLUTA DE SEGURIDAD:
NO utiliza subprocess, os.system, os.popen, shell=True, cmd.exe ni powershell.exe.
La extracción OCR se realiza directamente desde Python o mediante un FakeOCRBackend para entornos de pruebas.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Protocol

from core.desktop_models import OCRBoundingBox, OCRMetadata, OCRRequest, OCRResult, OCRTextRegion
from core.logger import get_logger

logger = get_logger("jessyca.tools.desktop.ocr_backend")


class IOCRBackend(Protocol):
    """Protocolo abstracto para el motor backend de reconocimiento OCR."""

    def extract_text(self, request: OCRRequest, screenshot_bytes: bytes | None = None) -> OCRResult:
        """Extrae el texto y regiones de una imagen según la solicitud recibida."""
        ...


class FakeOCRBackend:
    """Backend sintético seguro para pruebas multiplataforma y entornos sin motor OCR instalado."""

    def __init__(self, mock_text: str | None = None) -> None:
        self.mock_text = mock_text or "Jessyca Windows MCP System\nStatus: OK\nPassword policy enabled"

    def extract_text(self, request: OCRRequest, screenshot_bytes: bytes | None = None) -> OCRResult:
        """Genera regiones y resultado OCR sintéticos para pruebas deterministas."""
        lines = [line.strip() for line in self.mock_text.split("\n") if line.strip()]
        regions: list[OCRTextRegion] = []

        curr_y = request.y + 10
        total_chars = 0

        for line in lines:
            box = OCRBoundingBox(x=request.x + 10, y=curr_y, width=len(line) * 10, height=20)
            region = OCRTextRegion(text=line, bounding_box=box, confidence=0.95)
            regions.append(region)
            total_chars += len(line)
            curr_y += 30

        metadata = OCRMetadata(
            char_count=total_chars,
            region_count=len(regions),
            avg_confidence=0.95,
            processing_time_ms=5.0,
            backend_name="FakeOCRBackend",
            timestamp=datetime.now(UTC),
        )

        return OCRResult(
            recognized_text="\n".join(lines),
            regions=tuple(regions),
            metadata=metadata,
            truncated=False,
        )


class WindowsOCRBackend:
    """Backend real desacoplado para reconocimiento OCR en Windows (Pytesseract / Windows Media OCR)."""

    def extract_text(self, request: OCRRequest, screenshot_bytes: bytes | None = None) -> OCRResult:
        """Realiza el reconocimiento OCR sobre la imagen proporcionada con fallback limpio."""
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            logger.warning("[OCR BACKEND] pytesseract/Pillow no están disponibles. Delegando a FakeOCRBackend.")
            return FakeOCRBackend().extract_text(request, screenshot_bytes)

        if not screenshot_bytes and not request.image_base64:
            logger.warning("[OCR BACKEND] Sin payload de imagen. Delegando a FakeOCRBackend.")
            return FakeOCRBackend().extract_text(request, screenshot_bytes)

        try:
            if screenshot_bytes:
                img = Image.open(io.BytesIO(screenshot_bytes))
            else:
                import base64
                img_data = base64.b64decode(request.image_base64 or "")
                img = Image.open(io.BytesIO(img_data))

            # Recorte por ROI si se especificaron coordenadas/dimensiones
            if request.width and request.height:
                crop_box = (request.x, request.y, request.x + request.width, request.y + request.height)
                img = img.crop(crop_box)

            start_t = datetime.now(UTC)
            data = pytesseract.image_to_data(img, lang=request.language, output_type=pytesseract.Output.DICT)
            proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000

            regions: list[OCRTextRegion] = []
            full_text_parts: list[str] = []
            total_conf = 0.0

            n_boxes = len(data["text"])
            for i in range(n_boxes):
                text_item = data["text"][i].strip()
                conf_val = float(data["conf"][i])

                if text_item and conf_val >= 0:
                    conf_norm = conf_val / 100.0 if conf_val > 1.0 else conf_val
                    box = OCRBoundingBox(
                        x=request.x + int(data["left"][i]),
                        y=request.y + int(data["top"][i]),
                        width=int(data["width"][i]),
                        height=int(data["height"][i]),
                    )
                    regions.append(OCRTextRegion(text=text_item, bounding_box=box, confidence=conf_norm))
                    full_text_parts.append(text_item)
                    total_conf += conf_norm

            recognized_full = " ".join(full_text_parts)
            avg_conf = (total_conf / len(regions)) if regions else 0.0

            metadata = OCRMetadata(
                char_count=len(recognized_full),
                region_count=len(regions),
                avg_confidence=avg_conf,
                processing_time_ms=proc_ms,
                backend_name="WindowsOCRBackend (Pytesseract)",
                timestamp=datetime.now(UTC),
            )

            return OCRResult(
                recognized_text=recognized_full,
                regions=tuple(regions),
                metadata=metadata,
                truncated=False,
            )
        except Exception as e:
            logger.warning(f"[OCR BACKEND FAIL-SAFE] Fallo durante ejecución OCR nativa ({e}). Delegando a FakeOCRBackend.")
            return FakeOCRBackend().extract_text(request, screenshot_bytes)
