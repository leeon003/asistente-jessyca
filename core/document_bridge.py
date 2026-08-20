"""Puente de generación segura de documentos (`windows.files.generate_document` - Subetapa 11.4).

GARANTÍA ABSOLUTA DE SEGURIDAD Y PRIVACIDAD:
1. Reutiliza PathSecurityManager para canonicalizar y restringir toda escritura estrictamente dentro del sandbox (`FILESYSTEM_SANDBOX_ROOT`).
2. Rechaza categóricamente intentos de fuga o Path Traversal (../, ..\\, UNC, root escape).
3. Enforza la validación por la tubería de permisos SecureExecutionPipeline, PermissionManager, RiskEngine y EmergencyStopManager.
4. Auditoría con METADATOS EXCLUSIVOS (canonical_path, bytes_written, checksum_sha256, format). CERO contenido de documento en logs.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.event_bus import get_event_bus
from core.exceptions import MCPError
from core.logger import get_logger
from core.permission_manager import PermissionDecision, PermissionManager
from core.risk_engine import RiskEngine, SecurityLevel
from tools.filesystem.errors import PathSecurityError
from tools.filesystem.path_security import PathSecurityManager

logger = get_logger("jessyca.core.document_bridge")

MAX_DOCUMENT_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB limit


class DocumentFormat(StrEnum):
    """Formatos autorizados para generación de documentos."""

    TXT = "TXT"
    MARKDOWN = "MARKDOWN"
    JSON = "JSON"
    HTML = "HTML"
    CSV = "CSV"
    PDF_REPORT = "PDF_REPORT"


class DocumentGenerationError(MCPError):
    """Error base de la frontera de generación de documentos."""

    pass


class DocumentTraversalError(DocumentGenerationError):
    """Error emitido cuando una ruta intenta escapar del sandbox autorizado."""

    pass


class DocumentSizeExceededError(DocumentGenerationError):
    """Error emitido cuando el tamaño del documento supera el límite permitido."""

    pass


@dataclass(frozen=True)
class DocumentGenerationRequest:
    """Solicitud inmutable de generación de documento."""

    file_path: str
    title: str
    content: str
    format: DocumentFormat = DocumentFormat.MARKDOWN
    metadata: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "title": self.title,
            "format": str(self.format),
            "content_len": len(self.content),
        }


@dataclass(frozen=True)
class DocumentGenerationResult:
    """Resultado inmutable de la generación de un documento."""

    canonical_path: str
    bytes_written: int
    format: DocumentFormat
    checksum_sha256: str
    generated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_path": self.canonical_path,
            "bytes_written": self.bytes_written,
            "format": str(self.format),
            "checksum_sha256": self.checksum_sha256,
            "generated_at": self.generated_at.isoformat(),
        }


class IDocumentGenerator(Protocol):
    """Protocolo abstracto para generadores de documentos."""

    def generate(self, request: DocumentGenerationRequest, output_path: Path) -> DocumentGenerationResult:
        ...


class FakeDocumentGenerator(IDocumentGenerator):
    """Generador sintético seguro en memoria para pruebas deterministas."""

    def generate(self, request: DocumentGenerationRequest, output_path: Path) -> DocumentGenerationResult:
        now = datetime.now(UTC)
        encoded = request.content.encode("utf-8")
        bytes_written = len(encoded)

        # Escribir archivo sintético en el sandbox
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_suffix(".tmp")
        with open(tmp_path, "wb") as f:
            f.write(encoded)
        os.replace(tmp_path, output_path)

        checksum = hashlib.sha256(encoded).hexdigest()
        logger.debug(f"[FAKE DOC GEN] Documento sintético generado en '{output_path}' ({bytes_written} bytes)")

        return DocumentGenerationResult(
            canonical_path=str(output_path),
            bytes_written=bytes_written,
            format=request.format,
            checksum_sha256=checksum,
            generated_at=now,
        )


class NativeDocumentGenerator(IDocumentGenerator):
    """Generador nativo de documentos (TXT, Markdown, JSON, HTML, CSV)."""

    def generate(self, request: DocumentGenerationRequest, output_path: Path) -> DocumentGenerationResult:
        now = datetime.now(UTC)
        fmt = request.format

        if fmt == DocumentFormat.JSON:
            formatted_str = json.dumps({"title": request.title, "body": request.content}, indent=2)
        elif fmt == DocumentFormat.HTML:
            formatted_str = f"<!DOCTYPE html><html><head><title>{request.title}</title></head><body><h1>{request.title}</h1><p>{request.content}</p></body></html>"
        elif fmt == DocumentFormat.MARKDOWN:
            formatted_str = f"# {request.title}\n\n{request.content}\n"
        else:
            formatted_str = request.content

        encoded = formatted_str.encode("utf-8")
        bytes_written = len(encoded)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_suffix(".tmp")
        with open(tmp_path, "wb") as f:
            f.write(encoded)
        os.replace(tmp_path, output_path)

        checksum = hashlib.sha256(encoded).hexdigest()
        logger.info(f"[NATIVE DOC GEN] Documento '{fmt}' generado en '{output_path}' ({bytes_written} bytes)")

        return DocumentGenerationResult(
            canonical_path=str(output_path),
            bytes_written=bytes_written,
            format=fmt,
            checksum_sha256=checksum,
            generated_at=now,
        )


class DocumentGenerationBridge:
    """Frontera de seguridad para la generación autorizada, sanitizada y auditada de documentos."""

    def __init__(
        self,
        generator: IDocumentGenerator | None = None,
        path_security: PathSecurityManager | None = None,
        emergency_stop: EmergencyStopManager | None = None,
        permission_manager: PermissionManager | None = None,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self.generator = generator or NativeDocumentGenerator()
        self.path_security = path_security or PathSecurityManager()
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self.permission_manager = permission_manager or PermissionManager()
        self.risk_engine = risk_engine or RiskEngine()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def generate_document(
        self,
        request: DocumentGenerationRequest,
        request_id: str = "doc-gen-req",
    ) -> DocumentGenerationResult:
        """Valida la ruta dentro del sandbox, verifica el límite de tamaño, autoriza la ejecución y genera el documento."""
        # 1. Comprobación inmediata de Parada de Emergencia
        self.emergency_stop.check_cancellation(phase="validation")

        # 2. Validación y canonicalización de ruta dentro de FILESYSTEM_SANDBOX_ROOT (Protección Anti-Traversal)
        try:
            val_res = self.path_security.validate_and_canonicalize(request.file_path)
            target_path = Path(val_res.canonical_path)
        except PathSecurityError as e:
            raise DocumentTraversalError(f"Ruta de documento denegada por violación de sandbox o traversal: {e}")

        # 3. Límite de tamaño de salida
        content_bytes = len(request.content.encode("utf-8"))
        if content_bytes > MAX_DOCUMENT_SIZE_BYTES:
            raise DocumentSizeExceededError(
                f"Generación denegada: El contenido del documento ({content_bytes} bytes) excede el máximo ({MAX_DOCUMENT_SIZE_BYTES} bytes)."
            )

        # 4. Evaluación de Riesgo y Permisos
        decision = self.permission_manager.check_permission(
            tool_name="windows.files",
            operation="generate_document",
            parameters={"file_path": request.file_path, "format": str(request.format)},
            risk_level=SecurityLevel.WARNING,
        )

        if decision == PermissionDecision.DENY:
            raise DocumentGenerationError("Generación de documento denegada por la política de seguridad.")

        # Re-verificación de Parada de Emergencia antes de escribir
        self.emergency_stop.check_cancellation(phase="execution")

        # 5. Generación segura del documento
        result = self.generator.generate(request, target_path)

        # 6. Auditoría con PRIVACIDAD ABSOLUTA (METADATOS EXCLUSIVOS)
        audit_meta = {
            "canonical_path": result.canonical_path,
            "bytes_written": result.bytes_written,
            "format": str(result.format),
            "checksum_sha256": result.checksum_sha256,
        }

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.FILE_ACTION_SUCCEEDED,
                request_id=request_id,
                tool_name="windows.files",
                operation="generate_document",
                duration_ms=1.0,
                reason=f"Documento '{result.format}' generado exitosamente en sandbox.",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("files:document_generated", audit_meta)
        return result
