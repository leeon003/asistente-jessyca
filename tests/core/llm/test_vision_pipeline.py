"""Tests unitarios exhaustivos para el pipeline de visión multimodal con qwen3-vl:4b (Fase 4: Multimodal Vision Pipeline)."""

import json
from datetime import datetime

import pytest

from core.desktop_models import ScreenshotMetadata, ScreenshotResult
from core.llm.exceptions import InferenceError
from core.llm.inference import FakeLLMProvider
from core.llm.model_registry import ModelRegistry
from core.llm.vision_models import VisionAnalysis, VisionObservation
from core.llm.vision_provider import VisionProvider
from core.ocr_sanitizer import OCRTextSanitizer


def _crear_fake_screenshot(image_b64: str = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=") -> ScreenshotResult:
    """Helper para crear una instancia de ScreenshotResult para tests."""
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


class TestVisionPipeline:
    """Pruebas del pipeline de visión multimodal y sanitización."""

    def setup_method(self) -> None:
        ModelRegistry.reset_registry()

    def test_analyze_screenshot_structured_response(self) -> None:
        """Verifica el análisis exitoso de una captura procesada por qwen3-vl:4b."""
        simulated_response = json.dumps({
            "summary": "Escritorio de Windows con Notepad y Explorador abiertos.",
            "detected_windows": ["Bloc de notas - Sin título", "Explorador de archivos"],
            "detected_text": ["Archivo", "Edición", "Guardar", "Documentos"],
            "ui_elements": [
                {"type": "button", "label": "Guardar", "state": "active"},
                {"type": "window", "label": "Bloc de notas", "state": "active"},
            ],
            "confidence": 0.98,
        })

        fake_provider = FakeLLMProvider(default_response=simulated_response)
        vision_provider = VisionProvider(provider=fake_provider)

        screenshot = _crear_fake_screenshot()
        analysis = vision_provider.analyze_screenshot(screenshot, prompt="¿Qué hay en pantalla?")

        assert isinstance(analysis, VisionAnalysis)
        assert "Notepad" in analysis.summary
        assert "Bloc de notas - Sin título" in analysis.detected_windows
        assert "Guardar" in analysis.detected_text
        assert len(analysis.ui_elements) == 2
        assert analysis.confidence == 0.98
        assert analysis.model_used == "qwen3-vl:4b"

        # Verificar que FakeLLMProvider recibió la imagen
        assert len(fake_provider.call_history) == 1
        req = fake_provider.call_history[0]
        assert req.model_name == "qwen3-vl:4b"
        assert len(req.images) == 1
        assert req.images[0] == screenshot.image_base64

    def test_analyze_screenshot_sanitization_of_secrets(self) -> None:
        """Verifica que contraseñas y tokens detectados en la pantalla sean redactados automáticamente."""
        simulated_response = json.dumps({
            "summary": "Ventana con credencial: password=SecretPass123! y token=Bearer eyJhbGciOi...",
            "detected_windows": ["Consola de acceso - token=eyJhbGciOi..."],
            "detected_text": ["password=SecretPass123!", "Usuario: Admin"],
            "ui_elements": [
                {"type": "input", "label": "password=SecretPass123!", "state": "active"},
            ],
            "confidence": 0.95,
        })

        fake_provider = FakeLLMProvider(default_response=simulated_response)
        sanitizer = OCRTextSanitizer()
        vision_provider = VisionProvider(provider=fake_provider, sanitizer=sanitizer)

        screenshot = _crear_fake_screenshot()
        analysis = vision_provider.analyze_screenshot(screenshot)

        # Verificar que el secreto fue redactado
        assert "SecretPass123!" not in analysis.summary
        assert "[REDACTED_PASSWORD]" in analysis.summary or "[REDACTED" in analysis.summary
        assert "SecretPass123!" not in analysis.detected_text[0]

    def test_analyze_screenshot_from_bytes(self) -> None:
        """Verifica que el pipeline acepte directamente bytes crudos de imagen."""
        simulated_response = json.dumps({
            "summary": "Imagen procesada desde bytes.",
            "detected_windows": ["Calculadora"],
            "detected_text": ["1", "2", "+", "="],
            "ui_elements": [],
            "confidence": 0.90,
        })

        fake_provider = FakeLLMProvider(default_response=simulated_response)
        vision_provider = VisionProvider(provider=fake_provider)

        raw_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        analysis = vision_provider.analyze_screenshot(raw_bytes)

        assert analysis.summary == "Imagen procesada desde bytes."
        assert "Calculadora" in analysis.detected_windows

    def test_analyze_screenshot_empty_image_raises_error(self) -> None:
        """Verifica que una captura sin imagen lance InferenceError de forma determinista."""
        vision_provider = VisionProvider()
        empty_screenshot = ScreenshotResult(
            metadata=ScreenshotMetadata(
                width=100,
                height=100,
                format="PNG",
                size_bytes=0,
                pixel_count=10000,
                timestamp=datetime.now(),
                backend="fake",
            ),
            image_base64="",
        )

        with pytest.raises(InferenceError) as exc_info:
            vision_provider.analyze_screenshot(empty_screenshot)
        assert "no contiene datos de imagen" in str(exc_info.value)

    def test_create_observation_structure(self) -> None:
        """Verifica la generación de la estructura VisionObservation."""
        analysis = VisionAnalysis(
            summary="Escritorio limpio",
            detected_windows=("Explorador",),
            detected_text=("C:",),
            confidence=0.99,
        )

        vision_provider = VisionProvider()
        obs = vision_provider.create_observation(analysis, request_id="req-obs-123")

        assert isinstance(obs, VisionObservation)
        assert obs.observation_id == "req-obs-123"
        assert obs.summary == "Escritorio limpio"
        assert obs.is_safe is True
        assert obs.metadata["model_used"] == "qwen3-vl:4b"

    def test_analyze_screenshot_fallback_text_parsing(self) -> None:
        """Verifica que si el modelo responde con texto libre en lugar de JSON, se capture el summary."""
        raw_text_response = "Se observa una ventana de Google Chrome con una pestaña de YouTube reproduciendo un video."
        fake_provider = FakeLLMProvider(default_response=raw_text_response)
        vision_provider = VisionProvider(provider=fake_provider)

        screenshot = _crear_fake_screenshot()
        analysis = vision_provider.analyze_screenshot(screenshot)

        assert analysis.summary == raw_text_response
        assert analysis.confidence == 0.7
        assert analysis.detected_windows == ()
