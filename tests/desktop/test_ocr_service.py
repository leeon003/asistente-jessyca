"""Pruebas del servicio OCRService y redacción de secretos en texto (Subetapa 08.2)."""

from __future__ import annotations

from core.desktop_models import OCRRequest
from tools.desktop.ocr_backend import FakeOCRBackend
from tools.desktop.ocr_service import OCRService


def test_ocr_service_processes_and_sanitizes_recognized_text() -> None:
    # Backend que devuelve un secreto expuesto en pantalla
    mock_secret_text = "System Admin Panel\npassword=MySuperSecretPass999;\napi_key=sk_live_12345;"
    backend = FakeOCRBackend(mock_text=mock_secret_text)
    service = OCRService(backend=backend)

    req = OCRRequest(width=800, height=600)
    result = service.process_ocr(req, request_id="ocr-test-req-1")

    # 1. El texto reconocido NUNCA debe incluir las contraseñas/llaves crudas
    assert "MySuperSecretPass999" not in result.recognized_text
    assert "sk_live_12345" not in result.recognized_text
    assert "[REDACTED]" in result.recognized_text

    # 2. Las regiones individuales también deben estar sanitizadas
    for reg in result.regions:
        assert "MySuperSecretPass999" not in reg.text
        assert "sk_live_12345" not in reg.text
