"""Modelos inmutables para el pipeline de visión multimodal (Fase 76.x - Unificación canónica).

Re-exporta VisionAnalysis y VisionObservation desde core.vision.vision_result para
mantener un único punto de definición y total retrocompatibilidad en core/llm/.
"""

from __future__ import annotations

from core.vision.vision_result import VisionAnalysis, VisionObservation

__all__ = [
    "VisionAnalysis",
    "VisionObservation",
]
