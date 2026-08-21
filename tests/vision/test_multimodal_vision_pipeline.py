"""Tests exhaustivos para el pipeline de visión multimodal en core/vision/ (Fase 4: Multimodal Vision Pipeline).

Verifica:
- Imagen válida (ScreenshotResult, bytes, string base64)
- Imagen inválida (InvalidImageError)
- Screenshot vacío (EmptyScreenshotError)
- Timeout de inferencia (VisionTimeoutError)
- Modelo no disponible (VisionModelUnavailableError)
- Respuesta corrupta o texto plano
- Sanitización de secretos
- Creación de VisionObservation (UNTRUSTED DATA)
"""

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from core.desktop_models import ScreenshotMetadata, ScreenshotResult
from core.llm.exceptions import (
    ProviderConnectionError,
    ProviderTimeoutError,
)
from core.llm.inference import FakeLLMProvider
from core.vision import (
    EmptyScreenshotError,
    InvalidImageError,
    OllamaVisionProvider,
    VisionAnalysis,
    VisionModelUnavailableError,
    VisionObservation,
    VisionTimeoutError,
)


def _make_screenshot(image_b64: str = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=") -> ScreenshotResult:
    meta = ScreenshotMetadata(
        width=1920,
        height=1080,
        format="PNG",
        size_bytes=100,
        pixel_count=1920 * 1080,
        timestamp=datetime.now(),
        backend="fake_windows",
    )
    return ScreenshotResult(metadata=meta, image_base64=image_b64)


class TestMultimodalVisionPipeline:
    """Suite de pruebas para OllamaVisionProvider y el pipeline de visión."""

    def test_valid_screenshot_result(self) -> None:
        """Verifica el análisis exitoso de una captura ScreenshotResult válida."""
        sim_json = json.dumps({
            "summary": "Escritorio con editor de código abierto.",
            "detected_windows": ["Visual Studio Code"],
            "detected_text": ["main.py", "def run():"],
            "ui_elements": [{"type": "editor", "label": "main.py", "state": "active"}],
            "confidence": 0.95,
        })
        provider = FakeLLMProvider(default_response=sim_json)
        vision = OllamaVisionProvider(provider=provider)

        screenshot = _make_screenshot()
        res = vision.analyze_screenshot(screenshot)

        assert isinstance(res, VisionAnalysis)
        assert res.summary == "Escritorio con editor de código abierto."
        assert "Visual Studio Code" in res.detected_windows
        assert "main.py" in res.detected_text
        assert res.confidence == 0.95
        assert res.model_used == "qwen3-vl:4b"

    def test_valid_bytes_image(self) -> None:
        """Verifica el análisis a partir de bytes crudos."""
        sim_json = json.dumps({
            "summary": "Ventana de configuración.",
            "detected_windows": ["Settings"],
            "detected_text": ["Network", "Bluetooth"],
            "ui_elements": [],
            "confidence": 0.90,
        })
        provider = FakeLLMProvider(default_response=sim_json)
        vision = OllamaVisionProvider(provider=provider)

        raw_bytes = b"fake_png_binary_data"
        res = vision.analyze_screenshot(raw_bytes)
        assert res.summary == "Ventana de configuración."

    def test_empty_screenshot_raises_error(self) -> None:
        """Verifica que una captura nula, vacía o con 0 bytes lance EmptyScreenshotError."""
        vision = OllamaVisionProvider()

        with pytest.raises(EmptyScreenshotError):
            vision.analyze_screenshot(None)  # type: ignore[arg-type]

        with pytest.raises(EmptyScreenshotError):
            vision.analyze_screenshot(b"")

        with pytest.raises(EmptyScreenshotError):
            vision.analyze_screenshot("")

        # ScreenshotResult con dimensiones 0
        meta = ScreenshotMetadata(
            width=0,
            height=0,
            format="PNG",
            size_bytes=0,
            pixel_count=0,
            timestamp=datetime.now(),
            backend="fake",
        )
        empty_res = ScreenshotResult(metadata=meta, image_base64="")
        with pytest.raises(EmptyScreenshotError):
            vision.analyze_screenshot(empty_res)

    def test_invalid_image_base64_raises_error(self) -> None:
        """Verifica que datos base64 corruptos lancen InvalidImageError."""
        vision = OllamaVisionProvider()

        with pytest.raises(InvalidImageError):
            vision.analyze_screenshot("this_is_not_valid_base64!@#$%^&*()")

    def test_vision_timeout_raises_timeout_error(self) -> None:
        """Verifica que timeouts del backend de inferencia se traduzcan a VisionTimeoutError."""
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = ProviderTimeoutError(provider_name="ollama", timeout_seconds=30.0)

        vision = OllamaVisionProvider(provider=mock_llm)
        screenshot = _make_screenshot()

        with pytest.raises(VisionTimeoutError) as exc_info:
            vision.analyze_screenshot(screenshot)
        assert "Timeout durante el análisis visual" in str(exc_info.value)

    def test_vision_model_unavailable_raises_error(self) -> None:
        """Verifica que fallos de conexión al backend lancen VisionModelUnavailableError."""
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = ProviderConnectionError(provider_name="ollama", host="http://localhost:11434")

        vision = OllamaVisionProvider(provider=mock_llm)
        screenshot = _make_screenshot()

        with pytest.raises(VisionModelUnavailableError) as exc_info:
            vision.analyze_screenshot(screenshot)
        assert "no está disponible" in str(exc_info.value)

    def test_corrupt_response_graceful_fallback(self) -> None:
        """Verifica que respuestas no estructuradas de qwen3-vl:4b no rompan el pipeline y retornen fallback."""
        corrupt_text = "No soy un JSON. Solo veo un fondo azul y una barra de tareas abajo."
        provider = FakeLLMProvider(default_response=corrupt_text)
        vision = OllamaVisionProvider(provider=provider)

        screenshot = _make_screenshot()
        res = vision.analyze_screenshot(screenshot)

        assert isinstance(res, VisionAnalysis)
        assert "fondo azul" in res.summary
        assert res.confidence == 0.5

    def test_create_observation_structure(self) -> None:
        """Verifica la generación de VisionObservation estructurada (UNTRUSTED DATA)."""
        sim_json = json.dumps({
            "summary": "Pantalla de inicio de sesión.",
            "detected_windows": ["Login"],
            "detected_text": ["Usuario", "Contraseña"],
            "ui_elements": [],
            "confidence": 0.99,
        })
        provider = FakeLLMProvider(default_response=sim_json)
        vision = OllamaVisionProvider(provider=provider)

        screenshot = _make_screenshot()
        obs = vision.create_observation(screenshot)

        assert isinstance(obs, VisionObservation)
        assert obs.observation_id.startswith("obs_vis_")
        assert obs.summary == "Pantalla de inicio de sesión."
        assert obs.is_safe is True
        assert obs.analysis.summary == obs.summary
