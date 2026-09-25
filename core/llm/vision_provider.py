"""Proveedor de análisis visual multimodal (Fase 76.x - Unificación canónica con core.vision).

Re-exporta la implementación canónica y robusta de VisionProvider desde core.vision.ollama_vision_provider,
eliminando duplicidad de código y manteniendo retrocompatibilidad total con core/llm/ y skills/.
"""

from __future__ import annotations

from typing import Any

from core.vision.ollama_vision_provider import OllamaVisionProvider
from core.vision.vision_provider import (
    DEFAULT_VISION_MODEL,
    VISION_SYSTEM_PROMPT,
    extract_vision_json,
)
from core.vision.vision_result import VisionAnalysis, VisionObservation


class VisionProvider(OllamaVisionProvider):
    """Proveedor desacoplado para análisis visual de capturas de pantalla de Windows (Fase 76.x).

    Hereda de la implementación canónica core.vision.ollama_vision_provider.OllamaVisionProvider,
    manteniendo compatibilidad total con core/llm/ y el ecosistema de Skills.
    """

    def __init__(
        self,
        provider: Any | None = None,
        sanitizer: Any | None = None,
        default_model: str = DEFAULT_VISION_MODEL,
        fallback_confidence: float = 0.7,
    ) -> None:
        super().__init__(
            provider=provider,
            sanitizer=sanitizer,
            default_model=default_model,
            fallback_confidence=fallback_confidence,
        )


# Alias privado para retrocompatibilidad
_extraer_json_vision = extract_vision_json

__all__ = [
    "DEFAULT_VISION_MODEL",
    "VISION_SYSTEM_PROMPT",
    "OllamaVisionProvider",
    "VisionAnalysis",
    "VisionObservation",
    "VisionProvider",
    "_extraer_json_vision",
]
