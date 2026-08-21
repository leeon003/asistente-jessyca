"""Modelos inmutables para el pipeline de visión multimodal (core/vision/vision_result.py - Fase 4).

Define las estructuras de datos inmutables resultantes del análisis visual de capturas de pantalla de Windows
utilizando modelos multimodales como qwen3-vl:4b.

GARANTÍA DE SEGURIDAD ABSOLUTA:
- Modelos inmutables (@dataclass(frozen=True)).
- La salida es estrictamente UNTRUSTED DATA.
- El modelo de visión SOLO observa. NO ejecuta herramientas, NO hace clic, NO tipea, NO otorga permisos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class VisionAnalysis:
    """Resultado inmutable del análisis de visión de una captura de pantalla."""

    summary: str
    detected_windows: tuple[str, ...] = ()
    detected_text: tuple[str, ...] = ()
    ui_elements: tuple[dict[str, Any], ...] = ()
    confidence: float = 1.0
    model_used: str = "qwen3-vl:4b"
    raw_response: str = ""
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convierte el análisis a diccionario estructurado."""
        return {
            "summary": self.summary,
            "detected_windows": list(self.detected_windows),
            "detected_text": list(self.detected_text),
            "ui_elements": [dict(el) for el in self.ui_elements],
            "confidence": self.confidence,
            "model_used": self.model_used,
            "raw_response": self.raw_response,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class VisionObservation:
    """Observación estructurada del entorno visual lista para ser consumida por el Orquestador/Brain."""

    observation_id: str
    summary: str
    analysis: VisionAnalysis
    is_safe: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convierte la observación a diccionario."""
        return {
            "observation_id": self.observation_id,
            "summary": self.summary,
            "analysis": self.analysis.to_dict(),
            "is_safe": self.is_safe,
            "metadata": dict(self.metadata),
        }
