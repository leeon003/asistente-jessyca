"""Servicio seguro de extracción de texto OCR desde el escritorio (OCRService - Subetapa 08.2).

GARANTÍA ABSOLUTA DE PRIVACIDAD:
El AuditLogger y el EventBus reciben ÚNICAMENTE METADATOS del proceso OCR (conteo de caracteres,
conteo de regiones, confianza promedio, tiempo de procesamiento, backend).
NUNCA registran datos binarios de la imagen, Base64 ni el texto completo del OCR con secretos.
"""

from __future__ import annotations

from datetime import UTC, datetime

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.desktop_models import OCRMetadata, OCRRequest, OCRResult
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.ocr_sanitizer import OCRTextSanitizer
from core.ocr_security import OCRSecurityManager
from tools.desktop.ocr_backend import IOCRBackend, WindowsOCRBackend

logger = get_logger("jessyca.tools.desktop.ocr_service")


class OCRService:
    """Servicio de procesamiento y sanitización segura de reconocimiento OCR."""

    def __init__(
        self,
        backend: IOCRBackend | None = None,
        security_manager: OCRSecurityManager | None = None,
        sanitizer: OCRTextSanitizer | None = None,
    ) -> None:
        settings = AppSettings()
        self.backend = backend or WindowsOCRBackend()
        self.security_manager = security_manager or OCRSecurityManager()
        self.sanitizer = sanitizer or OCRTextSanitizer()
        self.max_regions = settings.OCR_MAX_REGIONS
        self.max_text_length = settings.OCR_MAX_TEXT_LENGTH
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def process_ocr(
        self,
        request: OCRRequest,
        screenshot_bytes: bytes | None = None,
        request_id: str | None = None,
    ) -> OCRResult:
        """Valida, ejecuta el backend OCR, sanitiza el texto y acota los resultados."""
        req_id = request_id or "ocr-req-unknown"
        start_time = datetime.now(UTC)

        self.event_bus.publish("desktop:ocr_requested", {"request_id": req_id, "language": request.language})

        # 1. Validación de parámetros con OCRSecurityManager (FAIL-SAFE DENY)
        validated_req = self.security_manager.validate_request(request)
        self.event_bus.publish("desktop:ocr_validated", {"request_id": req_id, "validated": True})

        # 2. Extracción OCR mediante backend desacoplado
        self.event_bus.publish("desktop:ocr_started", {"request_id": req_id})
        raw_result = self.backend.extract_text(validated_req, screenshot_bytes)

        # 3. Sanitización de texto reconocido y regiones para redacción de secretos
        clean_text, text_redactions = self.sanitizer.sanitize_text(raw_result.recognized_text)
        clean_regions, region_redactions = self.sanitizer.sanitize_regions(raw_result.regions)

        total_redactions = text_redactions + region_redactions

        # 4. Enforzamiento de límites de regiones y longitud de texto
        truncated = False
        final_regions = list(clean_regions)

        if len(final_regions) > self.max_regions:
            final_regions = final_regions[: self.max_regions]
            truncated = True

        if len(clean_text) > self.max_text_length:
            clean_text = clean_text[: self.max_text_length] + " ... [OCR_TEXT_TRUNCATED]"
            truncated = True

        duration = (datetime.now(UTC) - start_time).total_seconds() * 1000

        sanitized_metadata = OCRMetadata(
            char_count=len(clean_text),
            region_count=len(final_regions),
            avg_confidence=raw_result.metadata.avg_confidence,
            processing_time_ms=duration,
            backend_name=raw_result.metadata.backend_name,
            timestamp=datetime.now(UTC),
        )

        final_result = OCRResult(
            recognized_text=clean_text,
            regions=tuple(final_regions),
            metadata=sanitized_metadata,
            truncated=truncated,
        )

        # 5. Auditoría y eventos (ÚNICAMENTE METADATOS, CERO RAW TEXT / CERO BASE64 DE IMAGEN)
        audit_meta = sanitized_metadata.to_dict()
        audit_meta["redactions_count"] = total_redactions
        audit_meta["truncated"] = truncated

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.OCR_SUCCEEDED,
                request_id=req_id,
                tool_name="windows.desktop",
                operation="ocr_screen",
                duration_ms=duration,
                reason="Extracción OCR ejecutada y sanitizada exitosamente.",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("desktop:ocr_completed", {"request_id": req_id, "metadata": audit_meta})
        return final_result
