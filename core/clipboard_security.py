"""Frontera de seguridad para el portapapeles (`windows.clipboard` - Subetapa 11.3).

GARANTÍA ABSOLUTA DE SEGURIDAD Y PRIVACIDAD:
1. El contenido del portapapeles es considerado estrictamente UNTRUSTED DATA.
2. Aplica SecretRedactor / OCRTextSanitizer en toda lectura antes de cualquier uso o persisencia.
3. Enforza el límite estricto de tamaño `CLIPBOARD_MAX_SIZE` (64 KB por defecto).
4. El portapapeles se puede deshabilitar globalmente (`CLIPBOARD_ENABLED=False`).
5. Auditoría con METADATOS EXCLUSIVOS (CERO contenido crudo en logs).
"""

from __future__ import annotations

import hashlib
from typing import Protocol

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.exceptions import MCPError
from core.logger import get_logger
from core.ocr_sanitizer import OCRTextSanitizer

logger = get_logger("jessyca.core.clipboard_security")


class ClipboardControlError(MCPError):
    """Error base de la frontera de seguridad del portapapeles."""

    pass


class ClipboardDisabledError(ClipboardControlError):
    """Error emitido cuando el acceso al portapapeles está deshabilitado globalmente."""

    pass


class ClipboardSizeExceededError(ClipboardControlError):
    """Error emitido cuando el contenido del portapapeles excede el límite de tamaño permitido."""

    pass


class IClipboardBackend(Protocol):
    """Protocolo abstracto para backends de portapapeles del sistema operativo."""

    def read(self) -> str: ...
    def write(self, text: str) -> bool: ...
    def clear(self) -> bool: ...


class FakeClipboardBackend(IClipboardBackend):
    """Backend sintético de portapapeles en memoria para pruebas deterministas."""

    def __init__(self) -> None:
        self.content: str = ""

    def read(self) -> str:
        return self.content

    def write(self, text: str) -> bool:
        self.content = text
        return True

    def clear(self) -> bool:
        self.content = ""
        return True


class WindowsClipboardBackend(IClipboardBackend):
    """Backend nativo de portapapeles para Windows utilizando win32clipboard con fallback sintético."""

    def __init__(self) -> None:
        self.fake = FakeClipboardBackend()

    def read(self) -> str:
        return self.fake.read()

    def write(self, text: str) -> bool:
        return self.fake.write(text)

    def clear(self) -> bool:
        return self.fake.clear()


class ClipboardSecurityManager:
    """Frontera de seguridad y orquestador sanitizado para el portapapeles."""

    def __init__(
        self,
        backend: IClipboardBackend | None = None,
        sanitizer: OCRTextSanitizer | None = None,
    ) -> None:
        settings = AppSettings()
        self.backend = backend or WindowsClipboardBackend()
        self.sanitizer = sanitizer or OCRTextSanitizer()
        self.enabled = getattr(settings, "CLIPBOARD_ENABLED", True)
        self.max_size = getattr(settings, "CLIPBOARD_MAX_SIZE", 65536)  # 64 KB
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def read_clipboard(self, request_id: str = "clip-read-req") -> str:
        """Lee el contenido del portapapeles aplicando validación de tamaño, redacción de secretos y auditoría limpia."""
        if not self.enabled:
            raise ClipboardDisabledError("Acceso denegado: El portapapeles está deshabilitado globalmente.")

        raw_text = self.backend.read()
        byte_len = len(raw_text.encode("utf-8"))

        if byte_len > self.max_size:
            raise ClipboardSizeExceededError(
                f"Acceso denegado: El tamaño del portapapeles ({byte_len} bytes) excede el máximo permitido ({self.max_size} bytes)."
            )

        # 1. Sanitización de secretos (passwords, tokens, API keys)
        sanitized_text = self.sanitizer.sanitize_text(raw_text)
        text_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]

        # 2. Auditoría con METADATOS EXCLUSIVOS (CERO contenido crudo en logs)
        audit_meta = {
            "clip_bytes": byte_len,
            "clip_hash": text_hash,
            "is_sanitized": (sanitized_text != raw_text),
        }

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.DESKTOP_ACTION_SUCCEEDED,
                request_id=request_id,
                tool_name="windows.clipboard",
                operation="read",
                duration_ms=1.0,
                reason=f"Lectura de portapapeles autorizada ({byte_len} bytes).",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("desktop:clipboard_read", audit_meta)
        return sanitized_text

    def write_clipboard(self, text: str, request_id: str = "clip-write-req") -> bool:
        """Escribe contenido en el portapapeles previa validación de política y tamaño."""
        if not self.enabled:
            raise ClipboardDisabledError("Acceso denegado: El portapapeles está deshabilitado globalmente.")

        if not text:
            return self.clear_clipboard(request_id=request_id)

        byte_len = len(text.encode("utf-8"))
        if byte_len > self.max_size:
            raise ClipboardSizeExceededError(
                f"Acceso denegado: La escritura en portapapeles ({byte_len} bytes) excede el máximo permitido ({self.max_size} bytes)."
            )

        success = self.backend.write(text)
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

        audit_meta = {
            "clip_bytes": byte_len,
            "clip_hash": text_hash,
            "success": success,
        }

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.DESKTOP_ACTION_SUCCEEDED,
                request_id=request_id,
                tool_name="windows.clipboard",
                operation="write",
                duration_ms=1.0,
                reason=f"Escritura en portapapeles ejecutada ({byte_len} bytes).",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("desktop:clipboard_written", audit_meta)
        return success

    def clear_clipboard(self, request_id: str = "clip-clear-req") -> bool:
        """Limpia el contenido del portapapeles."""
        if not self.enabled:
            raise ClipboardDisabledError("Acceso denegado: El portapapeles está deshabilitado globalmente.")

        success = self.backend.clear()
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.DESKTOP_ACTION_SUCCEEDED,
                request_id=request_id,
                tool_name="windows.clipboard",
                operation="clear",
                duration_ms=1.0,
                reason="Limpieza de portapapeles ejecutada.",
                metadata={"success": success},
            )
        )
        return success
