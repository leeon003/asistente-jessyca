"""Implementación concreta de visión multimodal con Ollama y qwen3-vl:4b (core/vision/ollama_vision_provider.py - Fase 4).

Conecta la captura de pantalla de Windows (ScreenshotResult) con el modelo multimodal qwen3-vl:4b
mediante OllamaProvider y extrae observaciones estructuradas con sanitización de secretos.
"""

from __future__ import annotations

import base64
import time
import uuid
from typing import Any

from core.desktop_models import ScreenshotResult
from core.llm.exceptions import (
    ProviderConnectionError,
    ProviderTimeoutError,
)
from core.llm.inference import InferenceRequest, LLMProvider, OllamaProvider
from core.logger import get_logger
from core.ocr_sanitizer import OCRTextSanitizer
from core.vision.vision_exceptions import (
    EmptyScreenshotError,
    InvalidImageError,
    VisionError,
    VisionModelUnavailableError,
    VisionTimeoutError,
)
from core.vision.vision_provider import (
    DEFAULT_VISION_MODEL,
    VISION_SYSTEM_PROMPT,
    IVisionProvider,
    extract_vision_json,
)
from core.vision.vision_result import VisionAnalysis, VisionObservation

logger = get_logger("jessyca.vision.ollama")


class OllamaVisionProvider(IVisionProvider):
    """Proveedor de análisis visual multimodal respaldado por Ollama y qwen3-vl:4b."""

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
        """Analiza una captura de pantalla y retorna un VisionAnalysis sanitizado."""
        # 1. Validar y normalizar la imagen a base64
        base64_img = self._prepare_image_base64(screenshot)

        # 2. Preparar el prompt del usuario
        user_prompt = (
            prompt.strip()
            if prompt and prompt.strip()
            else "Describe lo que ves en la pantalla e identifica ventanas y elementos de UI relevantes."
        )

        req = InferenceRequest(
            prompt=user_prompt,
            system_prompt=VISION_SYSTEM_PROMPT,
            model_name=self.default_model,
            images=(base64_img,),
            temperature=0.1,
        )

        # 3. Invocar al proveedor multimodal
        t_start = time.perf_counter()
        try:
            resp = self._provider.generate(req)
        except ProviderTimeoutError as te:
            raise VisionTimeoutError(
                message=f"Timeout durante el análisis visual con {self.default_model}: {te}",
                code="VISION_TIMEOUT",
            ) from te
        except ProviderConnectionError as ce:
            raise VisionModelUnavailableError(
                message=f"El backend de visión en Ollama ({self.default_model}) no está disponible: {ce}",
                code="VISION_MODEL_UNAVAILABLE",
            ) from ce
        except Exception as e:
            raise VisionError(
                message=f"Fallo durante la inferencia del modelo de visión {self.default_model}: {e}",
                code="VISION_INFERENCE_ERROR",
            ) from e

        duration_ms = (time.perf_counter() - t_start) * 1000.0

        if not resp.success:
            if "not found" in (resp.error_message or "").lower() or "pull" in (resp.error_message or "").lower():
                raise VisionModelUnavailableError(
                    message=f"El modelo de visión '{self.default_model}' no está instalado en Ollama: {resp.error_message}",
                    code="VISION_MODEL_NOT_INSTALLED",
                )
            raise VisionError(
                message=f"El modelo de visión retornó error: {resp.error_message}",
                code="VISION_PROVIDER_ERROR",
            )

        # 4. Parsear y estructurar la respuesta JSON
        parsed_data = extract_vision_json(resp.content)
        if not parsed_data:
            logger.warning(f"[VISION] No se pudo extraer JSON estructurado de {self.default_model}. Generando fallback descriptivo.")
            # Sanitizar el texto plano antes de emitir el análisis
            san_raw = self._sanitizer.sanitize_text(resp.content)
            clean_summary = san_raw[0] if isinstance(san_raw, tuple) else san_raw
            return VisionAnalysis(
                summary=clean_summary[:500] if clean_summary else "Análisis visual no estructurado",
                detected_windows=(),
                detected_text=(),
                ui_elements=(),
                confidence=0.5,
                model_used=self.default_model,
                raw_response=resp.content,
                duration_ms=duration_ms,
            )

        # 5. Sanitizar textos detectados para proteger credenciales y secretos
        raw_summary = str(parsed_data.get("summary", "Sin resumen disponible"))
        san_sum = self._sanitizer.sanitize_text(raw_summary)
        clean_summary = san_sum[0] if isinstance(san_sum, tuple) else san_sum

        sanitized_texts: list[str] = []
        for t in parsed_data.get("detected_text", []):
            san_t = self._sanitizer.sanitize_text(str(t))
            clean_t = san_t[0] if isinstance(san_t, tuple) else san_t
            if clean_t:
                sanitized_texts.append(clean_t)

        detected_windows = tuple(str(w) for w in parsed_data.get("detected_windows", []))
        raw_ui = parsed_data.get("ui_elements", [])
        ui_elements: list[dict[str, Any]] = []
        if isinstance(raw_ui, list):
            for item in raw_ui:
                if isinstance(item, dict):
                    ui_elements.append(dict(item))

        confidence = float(parsed_data.get("confidence", 0.9))

        return VisionAnalysis(
            summary=clean_summary,
            detected_windows=detected_windows,
            detected_text=tuple(sanitized_texts),
            ui_elements=tuple(ui_elements),
            confidence=max(0.0, min(1.0, confidence)),
            model_used=self.default_model,
            raw_response=resp.content,
            duration_ms=duration_ms,
        )

    def create_observation(
        self,
        screenshot: ScreenshotResult | str | bytes,
        prompt: str | None = None,
    ) -> VisionObservation:
        """Crea una observación formal estructurada a partir de una captura de pantalla."""
        analysis = self.analyze_screenshot(screenshot=screenshot, prompt=prompt)
        obs_id = f"obs_vis_{uuid.uuid4().hex[:8]}"

        return VisionObservation(
            observation_id=obs_id,
            summary=analysis.summary,
            analysis=analysis,
            is_safe=True,
            metadata={"model": self.default_model, "duration_ms": analysis.duration_ms},
        )

    def _prepare_image_base64(self, screenshot: ScreenshotResult | str | bytes) -> str:
        """Valida y convierte la entrada de captura a una cadena Base64 limpia."""
        if screenshot is None:
            raise EmptyScreenshotError("La captura de pantalla suministrada es None.", code="EMPTY_SCREENSHOT")

        # 1. Si es ScreenshotResult
        if isinstance(screenshot, ScreenshotResult):
            if screenshot.metadata and (screenshot.metadata.width <= 0 or screenshot.metadata.height <= 0):
                raise EmptyScreenshotError(
                    f"Dimensiones de captura inválidas: {screenshot.metadata.width}x{screenshot.metadata.height}.",
                    code="EMPTY_SCREENSHOT",
                )
            if not screenshot.image_base64:
                raise EmptyScreenshotError("El objeto ScreenshotResult no contiene datos Base64.", code="EMPTY_SCREENSHOT")
            return self._validate_base64(screenshot.image_base64)

        # 2. Si es bytes crudos
        if isinstance(screenshot, bytes):
            if len(screenshot) == 0:
                raise EmptyScreenshotError("El buffer de bytes de la imagen está vacío.", code="EMPTY_SCREENSHOT")
            return base64.b64encode(screenshot).decode("utf-8")

        # 3. Si es string
        if isinstance(screenshot, str):
            clean_str = screenshot.strip()
            if not clean_str:
                raise EmptyScreenshotError("La cadena de imagen está vacía.", code="EMPTY_SCREENSHOT")
            return self._validate_base64(clean_str)

        raise InvalidImageError(f"Tipo de imagen no soportado: {type(screenshot)}", code="INVALID_IMAGE_TYPE")

    def _validate_base64(self, b64_str: str) -> str:
        """Verifica que la cadena sea base64 válida."""
        clean = b64_str.strip()
        # Eliminar prefijo data:image/...;base64, si existe
        if "," in clean and clean.startswith("data:image"):
            clean = clean.split(",", 1)[1]

        try:
            decoded = base64.b64decode(clean, validate=True)
            if len(decoded) == 0:
                raise EmptyScreenshotError("La imagen Base64 decodificada tiene 0 bytes.", code="EMPTY_SCREENSHOT")
        except Exception as e:
            raise InvalidImageError(f"Formato Base64 inválido o corrupto: {e}", code="INVALID_BASE64") from e

        return clean


# Alias para conveniencia y retrocompatibilidad
VisionProvider = OllamaVisionProvider
