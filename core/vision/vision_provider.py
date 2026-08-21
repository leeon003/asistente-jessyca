"""Abstracción y contrato base para proveedores de visión multimodal (core/vision/vision_provider.py - Fase 4).

Define el protocolo y clase base para análisis de imágenes y capturas de pantalla de Windows.

GARANTÍA DE SEGURIDAD ABSOLUTA:
1. La salida es estrictamente UNTRUSTED DATA.
2. Todo el texto detectado es sanitizado con OCRTextSanitizer para redactar credenciales y secretos.
3. El modelo SOLO observa. NO ejecuta herramientas ni modifica permisos en el sistema operativo.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol, runtime_checkable

from core.desktop_models import ScreenshotResult
from core.logger import get_logger
from core.vision.vision_result import VisionAnalysis, VisionObservation

logger = get_logger("jessyca.vision.provider")

DEFAULT_VISION_MODEL = "qwen3-vl:4b"

VISION_SYSTEM_PROMPT = (
    "Eres el módulo de visión multimodal de JESSYCA para Windows. "
    "Analiza la captura de pantalla provista y describe los elementos visuales de la interfaz de usuario. "
    "Responde con un JSON estructurado con los siguientes campos:\n"
    "{\n"
    '  "summary": "Breve resumen descriptivo de lo que se observa en pantalla",\n'
    '  "detected_windows": ["Lista de títulos de ventanas visibles"],\n'
    '  "detected_text": ["Textos clave o botones visibles"],\n'
    '  "ui_elements": [{"type": "button|input|window|menu", "label": "nombre", "state": "active|inactive"}],\n'
    '  "confidence": 0.95\n'
    "}"
)


def extract_vision_json(texto: str) -> dict[str, Any] | None:
    """Extrae un diccionario JSON válido del texto retornado por el modelo de visión."""
    if not texto:
        return None
    texto_limpio = texto.strip()

    # 1. Intento directo
    try:
        data = json.loads(texto_limpio)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # 2. Bloque markdown ```json ... ```
    md_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto_limpio, re.DOTALL)
    if md_match:
        try:
            data = json.loads(md_match.group(1))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    # 3. Primer objeto JSON entre llaves
    match = re.search(r"\{.*\}", texto_limpio, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return None


@runtime_checkable
class IVisionProvider(Protocol):
    """Protocolo abstracto para proveedores de análisis visual multimodal."""

    def analyze_screenshot(
        self,
        screenshot: ScreenshotResult | str | bytes,
        prompt: str | None = None,
        request_id: str | None = None,
    ) -> VisionAnalysis:
        """Analiza una captura de pantalla y retorna un VisionAnalysis sanitizado."""
        ...

    def create_observation(
        self,
        screenshot: ScreenshotResult | str | bytes,
        prompt: str | None = None,
    ) -> VisionObservation:
        """Crea una observación formal estructurada a partir de una captura de pantalla."""
        ...
