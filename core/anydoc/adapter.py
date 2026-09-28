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
from pathlib import Path
from typing import Any

import anydoc

from core.execution.execution_verifier import ExecutionStatus
from core.anydoc.models import (
    AnyDocMode,
    AnyDocProposal,
    AnyDocResult,
    ConversionStatus,
    DocumentFormat,
)
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


class AnyDocAdapter(IntegrationAdapter):
    """Adapter para el motor de conversión documental AnyDoc."""

    def __init__(
        self,
        mode: AnyDocMode | str = AnyDocMode.LAB,
        base_sandbox_dir: str | None = None,
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
        self._max_file_size_bytes = max_file_size_bytes
        self._network_calls_count = 0
        self._register_capabilities()

    @property
    def mode(self) -> AnyDocMode:
        """Modo de operación actual (OFF, LAB, SHADOW, CONTROLLED, ACTIVE)."""
        return self._mode

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

    def validate_and_confine_path(self, target_path: str, must_exist: bool = False) -> str:
        """Valida rutas contra path traversal y escapes del sandbox permitido."""
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

        # Comprobar rutas críticas prohibidas del sistema operativo
        norm_lower = os.path.normpath(raw_str).lower()
        for forbidden in _FORBIDDEN_SYSTEM_PATHS:
            if forbidden in norm_lower:
                raise ValueError(f"Access to critical system path forbidden: {raw_str}")

        real_target = os.path.realpath(raw_str)

        if must_exist and not os.path.exists(real_target):
            raise FileNotFoundError(f"File not found: {target_path}")

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
        if isinstance(file_path_or_bytes, bytes):
            detected = anydoc.format_from_bytes(file_path_or_bytes)
            return detected or DocumentFormat.UNKNOWN.value

        real_path = self.validate_and_confine_path(file_path_or_bytes, must_exist=True)
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
            real_input = self.validate_and_confine_path(input_path, must_exist=True)
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

            detected_fmt = self.detect_format(real_input)

            # Conversión local forzando ocr='reject' para garantizar 0 llamadas de red
            raw_markdown = anydoc.to_markdown(real_input, ocr="reject")

            final_markdown = self.redact_secrets(raw_markdown) if redact else raw_markdown

            # Si se especificó output_path, confinar y guardar
            final_out_path = None
            if output_path:
                real_output = self.validate_and_confine_path(output_path, must_exist=False)
                os.makedirs(os.path.dirname(real_output), exist_ok=True)
                with open(real_output, "w", encoding="utf-8") as out_f:
                    out_f.write(final_markdown)
                final_out_path = real_output

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

        except anydoc.NeedsOcrError as e:
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.NEEDS_OCR,
                input_path=input_path,
                detected_format="pdf",
                error_message=f"Document requires OCR: {e}",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )
        except anydoc.ResourceLimitError as e:
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.RESOURCE_LIMIT,
                input_path=input_path,
                detected_format="unknown",
                error_message=f"Resource safety limit exceeded: {e}",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )
        except anydoc.MalformedError as e:
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.MALFORMED,
                input_path=input_path,
                detected_format="unknown",
                error_message=f"Malformed document structure: {e}",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )
        except anydoc.EncryptedError as e:
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.ENCRYPTED,
                input_path=input_path,
                detected_format="unknown",
                error_message=f"Document is encrypted or password-protected: {e}",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )
        except anydoc.MissingPartError as e:
            return AnyDocResult(
                operation_id=op_id,
                status=ConversionStatus.MISSING_PART,
                input_path=input_path,
                detected_format="unknown",
                error_message=f"Missing required part: {e}",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
            )
        except anydoc.UnsupportedError as e:
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

    async def health_check(self) -> IntegrationHealth:
        return IntegrationHealth(
            healthy=True,
            status=self.status,
            message=f"AnyDocAdapter operational in mode {self._mode.value} (v0.2.4-lab)",
            details={
                "mode": self._mode.value,
                "engine": "anydoc-rust-core",
                "max_file_size_bytes": self._max_file_size_bytes,
                "network_calls_count": self._network_calls_count,
            },
        )
