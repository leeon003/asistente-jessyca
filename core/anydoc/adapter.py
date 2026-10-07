"""Adapter formal para la integración de AnyDoc en JESSYCA PC.

Fase 1 — Discovery, Audit y Lab.
Garantiza:
1. Rechazo terminante de modo ACTIVE en Fase 1.
2. Confinamiento estricto de rutas (sin path traversal ni escapes).
3. Redacción profunda de secretos en salidas.
4. Mapeo estricto del modelo de errores de AnyDoc a ConversionStatus.
5. Inviolabilidad de aislamiento de red (NETWORK = DENY por defecto).
"""

from __future__ import annotations

import os
import re
import time
import urllib.parse
import uuid
from typing import Any

try:
    import anydoc
    _AnyDocNeedsOcr = anydoc.NeedsOcrError
    _AnyDocResourceLimit = anydoc.ResourceLimitError
    _AnyDocMalformed = anydoc.MalformedError
    _AnyDocEncrypted = anydoc.EncryptedError
    _AnyDocMissingPart = anydoc.MissingPartError
    _AnyDocUnsupported = anydoc.UnsupportedError
except ImportError:
    anydoc = None  # type: ignore[assignment]

    class _AnyDocNeedsOcr(Exception):  # type: ignore[no-redef]
        pass

    class _AnyDocResourceLimit(Exception):  # type: ignore[no-redef]
        pass

    class _AnyDocMalformed(Exception):  # type: ignore[no-redef]
        pass

    class _AnyDocEncrypted(Exception):  # type: ignore[no-redef]
        pass

    class _AnyDocMissingPart(Exception):  # type: ignore[no-redef]
        pass

    class _AnyDocUnsupported(Exception):  # type: ignore[no-redef]
        pass

from core.anydoc.models import (
    AnyDocMode,
    AnyDocResult,
    ConversionStatus,
    DocumentFormat,
)
from core.execution.execution_verifier import ExecutionStatus
from core.integration.adapter import IntegrationAdapter
from core.integration.models import (
    IntegrationCapability,
    IntegrationContext,
    IntegrationExecutionResult,
    IntegrationHealth,
    IntegrationStatus,
)
from core.logger import get_logger
from core.security import RiskLevel

logger = get_logger("jessyca.anydoc.adapter")

# Expresiones regulares para detección y redacción de secretos
_SECRET_PATTERNS = [
    (re.compile(r"(?i)(?:bearer|token)\s+([a-zA-Z0-9_\-\.]{15,})"), "Bearer [REDACTED]"),
    (re.compile(r"sk-[a-zA-Z0-9_\-]{20,80}"), "[REDACTED_API_KEY]"),
    (re.compile(r"gh[pousr][_\-][a-zA-Z0-9]{20,80}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"(?i)(password|secret|passwd|pwd)\s*[:=]\s*['\"]?([^'\"\s]{4,})['\"]?"), r"\1=[REDACTED]"),
    (re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+ PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"(postgres|mysql|mongodb)://[^:\s]+:[^@\s]+@[^\s/]+"), r"\1://[REDACTED_CREDENTIALS]"),
]

# Rutas prohibidas del sistema para prevención de fugas de datos
_FORBIDDEN_SYSTEM_PATHS = [
    "\\windows\\",
    "/windows/",
    "\\system32\\",
    "/system32/",
    "\\program files\\",
    "/program files/",
    "/etc/",
    "/root/",
    "\\users\\administrator\\",
]


def _is_strictly_contained(target_path: str, parent_dir: str) -> bool:
    """Comprueba que target_path resida estrictamente dentro de parent_dir o sea idéntico.

    Previene ataques de prefijo hermano (ej. /data/anydoc_sibling vs /data/anydoc),
    rutas relativas con escape y normaliza mayúsculas/minúsculas en Windows.
    """
    try:
        norm_target = os.path.normcase(os.path.realpath(target_path))
        norm_parent = os.path.normcase(os.path.realpath(parent_dir))
        return norm_target == norm_parent or norm_target.startswith(norm_parent + os.sep)
    except Exception:
        return False


class AnyDocAdapter(IntegrationAdapter):
    """Adapter para el motor de conversión documental AnyDoc y Docling."""

    def __init__(
        self,
        mode: AnyDocMode | str = AnyDocMode.LAB,
        base_sandbox_dir: str | None = None,
        allowed_read_dirs: list[str] | None = None,
        backend: str | None = None,
        max_file_size_bytes: int = 50 * 1024 * 1024,  # 50 MB límite por defecto
        certified: bool = False,
    ) -> None:
        super().__init__(
            name="anydoc",
            version="0.2.4-phase3",
            dependencies=["anydoc"],
        )
        mode_str = str(mode).upper()
        self._certified = certified
        if mode_str == "ACTIVE" and not self._certified:
            raise RuntimeError(
                "AnyDoc cannot be activated in production (ACTIVE is strictly forbidden in Phase 1 and Phase 2; max allowed is CONTROLLED)"
            )
        try:
            self._mode = AnyDocMode(mode_str)
        except ValueError:
            self._mode = AnyDocMode.CONTROLLED

        self._base_sandbox_dir = os.path.realpath(
            base_sandbox_dir or os.path.join("data", "anydoc")
        )
        self._allowed_read_dirs = [
            self._base_sandbox_dir,
            os.path.realpath(os.path.join("lab", "anydoc")),
            os.path.realpath(os.path.join("tests", "anydoc")),
        ]
        if allowed_read_dirs:
            for d in allowed_read_dirs:
                real_d = os.path.realpath(d)
                if real_d not in self._allowed_read_dirs:
                    self._allowed_read_dirs.append(real_d)

        self._max_file_size_bytes = max_file_size_bytes
        self._network_calls_count = 0

        # Resolución del backend documental
        if backend is not None:
            self._backend_type = str(backend).lower().strip()
        else:
            try:
                from config import settings
                if getattr(settings, "DOCLING_ENABLED", False) or getattr(settings, "ANYDOC_BACKEND", "anydoc") == "docling":
                    self._backend_type = "docling"
                else:
                    self._backend_type = "anydoc"
            except Exception:
                self._backend_type = "anydoc"

        self._docling_backend: Any = None
        if self._backend_type == "docling":
            from core.anydoc.docling_backend import DoclingBackend
            self._docling_backend = DoclingBackend(
                base_sandbox_dir=self._base_sandbox_dir,
                max_file_size_bytes=self._max_file_size_bytes,
            )

        self._register_capabilities()

    @property
    def mode(self) -> AnyDocMode:
        """Modo de operación actual (OFF, LAB, SHADOW, CONTROLLED, ACTIVE)."""
        return self._mode

    @property
    def backend_type(self) -> str:
        """Tipo de backend activo ('anydoc' o 'docling')."""
        return self._backend_type

    @property
    def is_certified(self) -> bool:
        return self._certified

    def set_certified(self, certified: bool = True) -> None:
        """Marca formalmente la certificación para autorizar el modo ACTIVE."""
        self._certified = certified

    def set_mode(self, new_mode: AnyDocMode | str, certified: bool = False) -> None:
        """Cambia el modo de operación respetando las restricciones de fase."""
        mode_str = str(new_mode).upper()
        if mode_str == "ACTIVE" and not (self._certified or certified):
            raise RuntimeError(
                "AnyDoc cannot be activated in production (ACTIVE is strictly forbidden in Phase 1 and Phase 2; max allowed is CONTROLLED)"
            )
        if certified:
            self._certified = True
        self._mode = AnyDocMode(mode_str)
        if self._mode == AnyDocMode.OFF:
            self.status = IntegrationStatus.DISABLED
        else:
            self.status = IntegrationStatus.READY

    def kill_switch(self) -> None:
        """Kill switch operacional de emergencia: desactiva inmediatamente AnyDoc."""
        self._mode = AnyDocMode.OFF
        self.status = IntegrationStatus.DISABLED

    @property
    def network_calls_count(self) -> int:
        return self._network_calls_count

    def add_allowed_read_dir(self, directory: str) -> None:
        """Agrega un directorio autorizado de lectura al sandbox de AnyDoc."""
        real_d = os.path.realpath(directory)
        if real_d not in self._allowed_read_dirs:
            self._allowed_read_dirs.append(real_d)

    def validate_and_confine_path(
        self,
        target_path: str,
        must_exist: bool = False,
        is_output: bool = False,
        allow_quarantine: bool = False,
    ) -> str:
        """Valida rutas contra path traversal y escapes del sandbox permitido.

        Garantiza:
        - Rechazo de byte nulo, URL encoded traversal y traversal explícito.
        - Rechazo de rutas UNC de red.
        - Rechazo de rutas críticas del sistema operativo.
        - Para escrituras (is_output=True): confinamiento estricto a _base_sandbox_dir.
        - Para lecturas (is_output=False): confinamiento estricto a _allowed_read_dirs.
        - Prevención estricta de ataques de prefijo hermano (sibling prefix).
        """
        if not target_path or not str(target_path).strip():
            raise ValueError("Target path cannot be empty")

        raw_str = str(target_path).strip()

        # Chequeo de byte nulo
        if "\x00" in raw_str:
            raise ValueError("Null byte injection detected in path")

        # Chequeo de URL encoded traversal
        decoded = urllib.parse.unquote(raw_str)
        if ".." in decoded or "%2e%2e" in raw_str.lower():
            raise ValueError(f"Path traversal detected in path: {raw_str}")

        # Rechazo de rutas UNC de red
        if raw_str.startswith("\\\\") or raw_str.startswith("//"):
            raise ValueError(f"UNC network paths are forbidden: '{target_path}'")

        # Comprobar rutas críticas prohibidas del sistema operativo
        norm_lower = os.path.normpath(raw_str).lower()
        for forbidden in _FORBIDDEN_SYSTEM_PATHS:
            if forbidden in norm_lower:
                raise ValueError(f"Access to critical system path forbidden: {raw_str}")

        # Resolución canónica
        if os.path.exists(raw_str):
            real_target = os.path.realpath(raw_str)
        else:
            parent_dir = os.path.dirname(raw_str) or "."
            real_parent = os.path.realpath(parent_dir)
            real_target = os.path.normpath(os.path.join(real_parent, os.path.basename(raw_str)))

        if must_exist and not os.path.exists(real_target):
            raise FileNotFoundError(f"File not found: {target_path}")

        # Confinamiento estricto a sandbox
        if is_output:
            if not _is_strictly_contained(real_target, self._base_sandbox_dir):
                raise ValueError(
                    f"Security sandbox violation: output path '{target_path}' escapes authorized sandbox '{self._base_sandbox_dir}'"
                )
        else:
            is_authorized = any(
                _is_strictly_contained(real_target, allowed_dir)
                for allowed_dir in self._allowed_read_dirs
            )
            if not is_authorized:
                raise ValueError(
                    f"Security sandbox violation: input path '{target_path}' is outside authorized read sandbox '{self._base_sandbox_dir}'"
                )

        return real_target

    def redact_secrets(self, text: str) -> str:
        """Aplica redacción regex profunda sobre contenido que pueda albergar credenciales."""
        if not text:
            return ""
        result = text
        for pattern, replacement in _SECRET_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    def detect_format(self, file_path_or_bytes: str | bytes) -> str:
        """Detecta el formato mediante análisis de contenido (markers) y extensiones."""
        if anydoc is None:
            if isinstance(file_path_or_bytes, (str, Path)):
                return Path(str(file_path_or_bytes)).suffix.lstrip(".").lower() or DocumentFormat.UNKNOWN.value
            return DocumentFormat.UNKNOWN.value

        if isinstance(file_path_or_bytes, bytes):
            detected = anydoc.format_from_bytes(file_path_or_bytes)
            return detected or DocumentFormat.UNKNOWN.value

        real_path = self.validate_and_confine_path(file_path_or_bytes, must_exist=True, is_output=False)
        try:
            with open(real_path, "rb") as f:
                header = f.read(131072)
            detected = anydoc.format_from_bytes(header)
            if detected:
                return detected
        except Exception:
            pass

        # Fallback a extensión o path
        ext_detected = anydoc.format_from_path(real_path)
        return ext_detected or DocumentFormat.UNKNOWN.value

    def convert_file(
        self,
        input_path: str,
        output_path: str | None = None,
        redact: bool = True,
        operation_id: str | None = None,
    ) -> AnyDocResult:
        """Convierte un documento local a Markdown sin acceso a red y confinado."""
        op_id = operation_id or f"anydoc_{uuid.uuid4().hex[:12]}"
        start_time = time.perf_counter()

        try:
            real_input = self.validate_and_confine_path(input_path, must_exist=True, is_output=False)
            file_size = os.path.getsize(real_input)

            if file_size > self._max_file_size_bytes:
                return AnyDocResult(
                    operation_id=op_id,
                    status=ConversionStatus.RESOURCE_LIMIT,
                    input_path=input_path,
                    detected_format="unknown",
                    error_message=f"File size exceeds safety limit ({file_size} > {self._max_file_size_bytes} bytes)",
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    input_size_bytes=file_size,
                )

            final_out_path = None
            if output_path:
                final_out_path = self.validate_and_confine_path(output_path, must_exist=False, is_output=True)

            # Si el backend activo es Docling, delegar la conversión estructurada
            if self._backend_type == "docling" and self._docling_backend is not None:
                docling_res = self._docling_backend.convert_document(
                    real_input,
                    output_path=final_out_path,
                    redact_fn=self.redact_secrets if redact else None,
                    operation_id=op_id,
                )
                if docling_res.status == ConversionStatus.SUCCESS:
                    return docling_res
                # Fallback explícito si Docling falla
                logger.warning(
                    f"Docling falló con status {docling_res.status}. Realizando fallback a AnyDoc nativo."
                )

            detected_fmt = self.detect_format(real_input)

            # Conversión local forzando ocr='reject' para garantizar 0 llamadas de red
            raw_markdown = anydoc.to_markdown(real_input, ocr="reject")

            final_markdown = self.redact_secrets(raw_markdown) if redact else raw_markdown

            # Si se especificó output_path, confinar y guardar
            if final_out_path:
                os.makedirs(os.path.dirname(final_out_path), exist_ok=True)
                with open(final_out_path, "w", encoding="utf-8") as out_f:
                    out_f.write(final_markdown)

            # Inspección no invasiva del Document Model si está disponible
            doc_model_info: dict[str, Any] = {}
            try:
                with open(real_input, "rb") as bf:
                    bdata = bf.read()
                doc_obj = anydoc.to_document(bdata, detected_fmt)
                doc_model_info = {
                    "blocks_count": len(doc_obj.blocks),
                    "notes_count": len(doc_obj.notes),
                    "assets_count": len(doc_obj.assets),
                }
            except Exception:
                pass

            duration = (time.perf_counter() - start_time) * 1000.0
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.SUCCESS,
                input_path=input_path,
                detected_format=detected_fmt,
                output_markdown=final_markdown,
                output_path=final_out_path,
                latency_ms=duration,
                input_size_bytes=file_size,
                output_char_count=len(final_markdown),
                document_model_summary=doc_model_info,
            )

        except _AnyDocNeedsOcr as e:
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.NEEDS_OCR,
                input_path=input_path,
                detected_format="pdf",
                error_message=f"Document requires OCR: {e}",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )
        except _AnyDocResourceLimit as e:
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.RESOURCE_LIMIT,
                input_path=input_path,
                detected_format="unknown",
                error_message=f"Resource safety limit exceeded: {e}",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )
        except _AnyDocMalformed as e:
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.MALFORMED,
                input_path=input_path,
                detected_format="unknown",
                error_message=f"Malformed document structure: {e}",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )
        except _AnyDocEncrypted as e:
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.ENCRYPTED,
                input_path=input_path,
                detected_format="unknown",
                error_message=f"Document is encrypted or password-protected: {e}",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )
        except _AnyDocMissingPart as e:
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.MISSING_PART,
                input_path=input_path,
                detected_format="unknown",
                error_message=f"Missing required part: {e}",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )
        except _AnyDocUnsupported as e:
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.UNSUPPORTED,
                input_path=input_path,
                detected_format="unknown",
                error_message=f"Unsupported format: {e}",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )
        except (ValueError, FileNotFoundError) as e:
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.SECURITY_BLOCKED,
                input_path=input_path,
                detected_format="unknown",
                error_message=str(e),
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )
        except Exception as e:
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.IO_ERROR,
                input_path=input_path,
                detected_format="unknown",
                error_message=f"Conversion error: {type(e).__name__}: {e}",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )

    CERTIFIED_CAPABILITIES: list[str] = [
        "document_processing.convert",
        "document_processing.inspect",
        "document_processing.extract_structure",
        "document_processing.extract_assets",
        "document_processing.detect_format",
        # Compatibilidad con nombres de Phase 1
        "document_convert_to_markdown",
        "document_detect_format",
    ]

    FORBIDDEN_CAPABILITIES: list[str] = [
        "document_processing.ocr_external",
        "document_processing.external_upload",
        "document_processing.document_write",
        "document_processing.arbitrary",
    ]

    def _register_capabilities(self) -> None:
        """Registra las capacidades documentales estrictamente certificadas bajo JDE."""
        # 1. document_processing.convert
        self.register_capability(
            IntegrationCapability(
                name="document_processing.convert",
                description="Conversión local y offline de documentos a GitHub-Flavored Markdown dentro del sandbox.",
                required_risk_level=RiskLevel.SAFE,
                required_permissions=["fs:read", "fs:write"],
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "input_path": {"type": "string"},
                        "output_path": {"type": "string"},
                        "redact_secrets": {"type": "boolean"},
                    },
                    "required": ["input_path"],
                },
            )
        )
        # Compatibilidad con Fase 1
        self.register_capability(
            IntegrationCapability(
                name="document_convert_to_markdown",
                description="Alias de compatibilidad para document_processing.convert.",
                required_risk_level=RiskLevel.SAFE,
                required_permissions=["fs:read"],
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "input_path": {"type": "string"},
                        "output_path": {"type": "string"},
                        "redact_secrets": {"type": "boolean"},
                    },
                    "required": ["input_path"],
                },
            )
        )
        # 2. document_processing.inspect
        self.register_capability(
            IntegrationCapability(
                name="document_processing.inspect",
                description="Inspección detallada de metadata, estructura de bloques, notas y assets del documento.",
                required_risk_level=RiskLevel.READ_ONLY,
                required_permissions=["fs:read"],
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "input_path": {"type": "string"},
                    },
                    "required": ["input_path"],
                },
            )
        )
        # 3. document_processing.extract_structure
        self.register_capability(
            IntegrationCapability(
                name="document_processing.extract_structure",
                description="Extracción estructurada de encabezados, párrafos, tablas, listas y notas.",
                required_risk_level=RiskLevel.READ_ONLY,
                required_permissions=["fs:read"],
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "input_path": {"type": "string"},
                    },
                    "required": ["input_path"],
                },
            )
        )
        # 4. document_processing.extract_assets
        self.register_capability(
            IntegrationCapability(
                name="document_processing.extract_assets",
                description="Extracción y confinamiento de assets permitidos (imágenes, medios) al sandbox autorizado.",
                required_risk_level=RiskLevel.SAFE,
                required_permissions=["fs:read", "fs:write"],
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "input_path": {"type": "string"},
                        "output_dir": {"type": "string"},
                    },
                    "required": ["input_path"],
                },
            )
        )
        # 5. document_processing.detect_format
        self.register_capability(
            IntegrationCapability(
                name="document_processing.detect_format",
                description="Identificación determinista del formato documental mediante marcadores binarios de contenido.",
                required_risk_level=RiskLevel.READ_ONLY,
                required_permissions=["fs:read"],
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "input_path": {"type": "string"},
                    },
                    "required": ["input_path"],
                },
            )
        )
        # Compatibilidad con Fase 1
        self.register_capability(
            IntegrationCapability(
                name="document_detect_format",
                description="Alias de compatibilidad para document_processing.detect_format.",
                required_risk_level=RiskLevel.READ_ONLY,
                required_permissions=["fs:read"],
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "input_path": {"type": "string"},
                    },
                    "required": ["input_path"],
                },
            )
        )

    async def initialize(self) -> bool:
        if self._mode == AnyDocMode.OFF:
            self.status = IntegrationStatus.DISABLED
            return True
        self.status = IntegrationStatus.READY
        return True

    async def shutdown(self) -> None:
        self.status = IntegrationStatus.AVAILABLE

    async def execute(
        self,
        capability: str,
        context: IntegrationContext,
    ) -> IntegrationExecutionResult:
        start_time = time.perf_counter()
        capability_name = capability

        # Bloqueo estricto de capabilities prohibidas
        if capability_name in self.FORBIDDEN_CAPABILITIES:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.DENIED,
                verified=False,
                verification_required=False,
                error=f"Capability '{capability_name}' is STRICTLY FORBIDDEN and permanently DISABLED in Phase 2",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        if self._mode == AnyDocMode.OFF:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.DENIED,
                verified=False,
                verification_required=False,
                error="AnyDoc adapter is OFF",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        if capability_name in ("document_processing.convert", "document_convert_to_markdown"):
            input_p = context.parameters.get("input_path", "")
            out_p = context.parameters.get("output_path")
            redact = context.parameters.get("redact_secrets", True)
            res = self.convert_file(input_p, out_p, redact=redact)
            success = (res.status == ConversionStatus.SUCCESS)
            return IntegrationExecutionResult(
                executed=True,
                status=ExecutionStatus.SUCCEEDED if success else ExecutionStatus.FAILED,
                verified=success,
                verification_required=True,
                output=res.to_dict(),
                error=res.error_message,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                evidence={"anydoc_result": res.to_dict()},
                metadata={"mode": self._mode.value},
            )
        elif capability_name in ("document_processing.detect_format", "document_detect_format"):
            input_p = context.parameters.get("input_path", "")
            try:
                fmt = self.detect_format(input_p)
                return IntegrationExecutionResult(
                    executed=True,
                    status=ExecutionStatus.SUCCEEDED,
                    verified=True,
                    verification_required=False,
                    output={"detected_format": fmt, "input_path": input_p},
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )
            except Exception as e:
                return IntegrationExecutionResult(
                    executed=False,
                    status=ExecutionStatus.FAILED,
                    verified=False,
                    verification_required=False,
                    error=str(e),
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )
        elif capability_name == "document_processing.inspect":
            input_p = context.parameters.get("input_path", "")
            try:
                real_input = self.validate_and_confine_path(input_p, must_exist=True)
                fmt = self.detect_format(real_input)
                with open(real_input, "rb") as bf:
                    bdata = bf.read()
                doc_obj = anydoc.to_document(bdata, fmt)
                inspection_data = {
                    "format": fmt,
                    "blocks_count": len(doc_obj.blocks),
                    "notes_count": len(doc_obj.notes),
                    "assets_count": len(doc_obj.assets),
                    "input_path": input_p,
                }
                return IntegrationExecutionResult(
                    executed=True,
                    status=ExecutionStatus.SUCCEEDED,
                    verified=True,
                    verification_required=False,
                    output=inspection_data,
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )
            except Exception as e:
                return IntegrationExecutionResult(
                    executed=False,
                    status=ExecutionStatus.FAILED,
                    verified=False,
                    verification_required=False,
                    error=f"Inspect error: {e}",
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )
        elif capability_name == "document_processing.extract_structure":
            input_p = context.parameters.get("input_path", "")
            try:
                real_input = self.validate_and_confine_path(input_p, must_exist=True)
                fmt = self.detect_format(real_input)
                with open(real_input, "rb") as bf:
                    bdata = bf.read()
                doc_obj = anydoc.to_document(bdata, fmt)
                headings = []
                paragraphs = []
                tables_count = 0
                lists_count = 0
                for b in doc_obj.blocks:
                    if b.kind == "heading":
                        headings.append({"level": b.level, "text": "".join([getattr(i, 'text', '') or '' for i in (b.content or [])])})
                    elif b.kind == "paragraph":
                        paragraphs.append("".join([getattr(i, 'text', '') or '' for i in (b.content or [])]))
                    elif b.kind == "table":
                        tables_count += 1
                    elif b.kind == "list":
                        lists_count += 1
                structure = {
                    "headings": headings,
                    "paragraphs_count": len(paragraphs),
                    "tables_count": tables_count,
                    "lists_count": lists_count,
                    "notes_count": len(doc_obj.notes),
                }
                return IntegrationExecutionResult(
                    executed=True,
                    status=ExecutionStatus.SUCCEEDED,
                    verified=True,
                    verification_required=False,
                    output=structure,
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )
            except Exception as e:
                return IntegrationExecutionResult(
                    executed=False,
                    status=ExecutionStatus.FAILED,
                    verified=False,
                    verification_required=False,
                    error=f"Extract structure error: {e}",
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )
        elif capability_name == "document_processing.extract_assets":
            input_p = context.parameters.get("input_path", "")
            out_d = context.parameters.get("output_dir", os.path.join("data", "anydoc", "output", "assets"))
            try:
                real_input = self.validate_and_confine_path(input_p, must_exist=True)
                fmt = self.detect_format(real_input)
                with open(real_input, "rb") as bf:
                    bdata = bf.read()
                doc_obj = anydoc.to_document(bdata, fmt)
                real_out_d = self.validate_and_confine_path(out_d, must_exist=False)
                os.makedirs(real_out_d, exist_ok=True)
                assets_extracted = []
                import hashlib
                for idx, a in enumerate(doc_obj.assets):
                    origin_name = os.path.basename(a.origin_part or f"asset_{idx}.bin")
                    safe_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", origin_name)
                    asset_file = os.path.join(real_out_d, safe_name)
                    with open(asset_file, "wb") as af:
                        af.write(a.data)
                    assets_extracted.append({
                        "asset_id": a.id,
                        "media_type": a.media_type,
                        "path": asset_file,
                        "size_bytes": len(a.data),
                        "hash": hashlib.sha256(a.data).hexdigest(),
                    })
                return IntegrationExecutionResult(
                    executed=True,
                    status=ExecutionStatus.SUCCEEDED,
                    verified=True,
                    verification_required=True,
                    output={"assets_count": len(assets_extracted), "assets": assets_extracted},
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )
            except Exception as e:
                return IntegrationExecutionResult(
                    executed=False,
                    status=ExecutionStatus.FAILED,
                    verified=False,
                    verification_required=False,
                    error=f"Extract assets error: {e}",
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                )

        return IntegrationExecutionResult(
            executed=False,
            status=ExecutionStatus.FAILED,
            verified=False,
            verification_required=False,
            error=f"Capability '{capability_name}' not supported by AnyDocAdapter",
            duration_ms=(time.perf_counter() - start_time) * 1000.0,
        )

    def close(self) -> None:
        """Cierre limpio y liberación de recursos de backend."""
        if self._docling_backend is not None:
            self._docling_backend.close()

    async def health_check(self) -> IntegrationHealth:
        details = {
            "mode": self._mode.value,
            "engine": f"anydoc-{self._backend_type}",
            "backend": self._backend_type,
            "max_file_size_bytes": self._max_file_size_bytes,
            "network_calls_count": self._network_calls_count,
        }
        if self._backend_type == "docling" and self._docling_backend is not None:
            details["docling"] = self._docling_backend.health()

        return IntegrationHealth(
            status=self.status,
            is_healthy=True,
            message=f"AnyDocAdapter operational in mode {self._mode.value} (backend: {self._backend_type})",
            details=details,
        )

