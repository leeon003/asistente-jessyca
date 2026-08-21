"""Proveedor de análisis visual multimodal (VisionProvider - Fase 4: Multimodal Vision Pipeline).

Conecta la captura de pantalla de Windows (ScreenshotResult) con modelos de visión multimodal
(específicamente qwen3-vl:4b) para extraer observaciones estructuradas y sanitizadas del escritorio.

GARANTÍA DE SEGURIDAD (INVARIANTE ARQUITECTÓNICA):
1. La salida de VisionAnalysis es estrictamente UNTRUSTED DATA.
2. Todo el texto detectado es sanitizado con OCRTextSanitizer para redactar credenciales y secretos.
3. NO ejecuta herramientas ni modifica permisos en el sistema operativo.
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from typing import Any

from core.desktop_models import ScreenshotResult
from core.llm.exceptions import InferenceError
from core.llm.inference import InferenceRequest, LLMProvider, OllamaProvider
from core.llm.vision_models import VisionAnalysis, VisionObservation
from core.logger import get_logger
from core.ocr_sanitizer import OCRTextSanitizer

logger = get_logger("jessyca.llm.vision")

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


def _extraer_json_vision(texto: str) -> dict[str, Any] | None:
    """Intenta extraer un diccionario JSON válido del texto retornado por el modelo de visión."""
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
    md_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', texto_limpio, re.DOTALL)
    if md_match:
        try:
            data = json.loads(md_match.group(1))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    # 3. Primer objeto JSON entre llaves
    match = re.search(r'\{.*\}', texto_limpio, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return None


class VisionProvider:
    """Proveedor desacoplado para análisis visual de capturas de pantalla de Windows."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        sanitizer: OCRTextSanitizer | None = None,
        default_model: str = DEFAULT_VISION_MODEL,
    ) -> None:
        self._provider = provider or OllamaProvider()
        self._sanitizer = sanitizer or OCRTextSanitizer()
        self.default_model = default_model

    def analyze_screenshot(
        self,
        screenshot: ScreenshotResult | str | bytes,
        prompt: str | None = None,
        request_id: str | None = None,
    ) -> VisionAnalysis:
        """Procesa una captura de pantalla y retorna un análisis estructurado inmutable."""
        # 1. Extraer y normalizar la cadena Base64 de la imagen
        image_b64 = self._extract_base64_image(screenshot)
        if not image_b64:
            raise InferenceError("La captura de pantalla no contiene datos de imagen válidos.")

        # 2. Construir la solicitud multimodal tipada
        user_prompt = prompt or "Describe la interfaz de usuario y las ventanas visibles en esta captura de pantalla."
        req = InferenceRequest(
            prompt=user_prompt,
            system_prompt=VISION_SYSTEM_PROMPT,
            model_name=self.default_model,
            images=(image_b64,),
            temperature=0.1,
        )

        logger.debug(f"[VISION PROVIDER] Enviando imagen a modelo multimodal '{self.default_model}' (req: {request_id})")

        # 3. Ejecutar inferencia
        res = self._provider.generate(req)
        raw_text = res.content.strip()

        # 4. Parsear respuesta estructurada
        parsed = _extraer_json_vision(raw_text)

        if parsed is not None:
            raw_summary = str(parsed.get("summary", raw_text[:200]))
            raw_windows = parsed.get("detected_windows") or []
            raw_texts = parsed.get("detected_text") or []
            raw_elements = parsed.get("ui_elements") or []
            confidence = float(parsed.get("confidence", 0.95))
        else:
            raw_summary = raw_text
            raw_windows = []
            raw_texts = []
            raw_elements = []
            confidence = 0.7

        # 5. Sanitizar textos detectados para proteger credenciales y secretos
        sanitized_summary, _ = self._sanitizer.sanitize_text(raw_summary)
        sanitized_windows = tuple(
            self._sanitizer.sanitize_text(str(w))[0] for w in raw_windows if isinstance(w, (str, int))
        )
        sanitized_texts = tuple(
            self._sanitizer.sanitize_text(str(t))[0] for t in raw_texts if isinstance(t, (str, int))
        )

        ui_elements_list: list[dict[str, Any]] = []
        if isinstance(raw_elements, list):
            for el in raw_elements:
                if isinstance(el, dict):
                    clean_label, _ = self._sanitizer.sanitize_text(str(el.get("label", "")))
                    clean_el = {
                        "type": str(el.get("type", "unknown")),
                        "label": clean_label,
                        "state": str(el.get("state", "unknown")),
                    }
                    ui_elements_list.append(clean_el)

        return VisionAnalysis(
            summary=sanitized_summary,
            detected_windows=sanitized_windows,
            detected_text=sanitized_texts,
            ui_elements=tuple(ui_elements_list),
            confidence=confidence,
            model_used=self.default_model,
            raw_response=raw_text,
            duration_ms=res.duration_ms,
        )

    def create_observation(
        self,
        analysis: VisionAnalysis,
        request_id: str | None = None,
    ) -> VisionObservation:
        """Convierte el análisis visual en una observación estructurada lista para el Orquestador/Brain."""
        obs_id = request_id or f"vis-obs-{uuid.uuid4().hex[:8]}"
        return VisionObservation(
            observation_id=obs_id,
            summary=analysis.summary,
            analysis=analysis,
            is_safe=True,
            metadata={
                "model_used": analysis.model_used,
                "duration_ms": analysis.duration_ms,
                "windows_count": len(analysis.detected_windows),
                "text_count": len(analysis.detected_text),
            },
        )

    def _extract_base64_image(self, screenshot: ScreenshotResult | str | bytes) -> str:
        """Extrae de forma segura la representación en cadena Base64 de la imagen."""
        if isinstance(screenshot, ScreenshotResult):
            if screenshot.image_base64:
                return screenshot.image_base64.strip()
            return ""
        if isinstance(screenshot, str):
            return screenshot.strip()
        if isinstance(screenshot, bytes):
            return base64.b64encode(screenshot).decode("utf-8")
        return ""
