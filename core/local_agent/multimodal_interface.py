"""Procesador y Frontera Multimodal (multimodal_interface.py - Fase 45).

Normaliza, valida y sanitiza entradas de múltiples modalidades:
- Texto plano y comandos conversacionales
- Capturas de pantalla (Desktop / Screen inspection)
- Imágenes adjuntas (OCR, visión local)
- Archivos locales y adjuntos
- Contexto web y DOM de navegador

INVARIANTE DE SEGURIDAD:
Todo dato de imagen, pantalla, archivo o navegador es tratado como UNTRUSTED DATA.
"""

from __future__ import annotations

from typing import Any

from core.local_agent.local_agent_models import JessycaRequest
from core.logger import get_logger

logger = get_logger("jessyca.local_agent.multimodal")

# Límites de seguridad para payloads multimodales
MAX_IMAGE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_ATTACHMENTS_COUNT = 10


class MultimodalProcessor:
    """Procesador de validación e ingestión para solicitudes multimodales."""

    @staticmethod
    def process_request(request: JessycaRequest) -> tuple[bool, str | None, dict[str, Any]]:
        """Valida y extrae el contexto multimodal de una petición entrante.

        Returns:
            (is_valid, error_message, processed_context)
        """
        context: dict[str, Any] = {
            "modality": str(request.modality),
            "has_images": len(request.images) > 0,
            "has_screen": request.screen_capture is not None,
            "has_files": len(request.file_attachments) > 0,
            "has_browser": len(request.browser_context) > 0,
        }

        # 1. Validación de Imágenes
        if request.images:
            if len(request.images) > MAX_ATTACHMENTS_COUNT:
                return False, f"Demasiadas imágenes adjuntas ({len(request.images)} > {MAX_ATTACHMENTS_COUNT}).", {}
            for idx, img_bytes in enumerate(request.images):
                if len(img_bytes) > MAX_IMAGE_SIZE_BYTES:
                    return False, f"Imagen #{idx+1} excede el tamaño máximo permitido (20MB).", {}
            context["images_count"] = len(request.images)

        # 2. Validación de Captura de Pantalla
        if request.screen_capture is not None:
            if len(request.screen_capture) > MAX_IMAGE_SIZE_BYTES:
                return False, "La captura de pantalla excede el tamaño máximo permitido (20MB).", {}
            context["screen_size_bytes"] = len(request.screen_capture)

        # 3. Validación de Archivos Adjuntos
        if request.file_attachments:
            if len(request.file_attachments) > MAX_ATTACHMENTS_COUNT:
                return False, f"Demasiados archivos adjuntos ({len(request.file_attachments)} > {MAX_ATTACHMENTS_COUNT}).", {}
            # Comprobar caracteres nulos
            for path in request.file_attachments:
                if "\x00" in path:
                    return False, "Ruta de archivo contiene caracteres nulos prohibidos.", {}
            context["files"] = list(request.file_attachments)

        # 4. Validación de Contexto de Navegador
        if request.browser_context:
            context["browser_url"] = request.browser_context.get("url", "")
            context["browser_title"] = request.browser_context.get("title", "")

        return True, None, context
