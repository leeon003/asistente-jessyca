"""Modelos de datos y contratos estructurados para la integración de AnyDoc.

Fase 2 — Integración Controlada y Procesamiento Documental Gobernado.
Principios:
1. MODO: OFF, LAB, SHADOW y CONTROLLED son válidos. ACTIVE permanece estrictamente prohibido.
2. SUBORDINACIÓN: AnyDoc es un motor de conversión documental; no es autoridad decisoria.
3. CONTRATO INMUTABLE: AnyDocTaskContract con sello criptográfico inmutable SHA-256 (seal).
4. VERIFICACIÓN FÍSICA: Diferenciación taxativa entre CLAIMED_SUCCESS y VERIFIED_SUCCESS.
5. SANDBOX ESTRICTO: data/anydoc/{input,output,cache,quarantine} con cero escapes de ruta.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.security import RiskLevel


class AnyDocMode(StrEnum):
    """Modos de operación permitidos para AnyDoc en JESSYCA PC."""

    OFF = "OFF"                  # Deshabilitado por completo
    LAB = "LAB"                  # Modo laboratorio aislado para pruebas y desarrollo
    SHADOW = "SHADOW"            # Modo sombra: genera propuestas y telemetría sin efectos colaterales
    CONTROLLED = "CONTROLLED"    # Modo controlado bajo JDE (Fase 2)
    ACTIVE = "ACTIVE"            # Modo producción (PROHIBIDO EN FASE 2)


class DocumentFormat(StrEnum):
    """Formatos soportados nativamente por Firecrawl AnyDoc."""

    DOC = "doc"
    DOCX = "docx"
    DOCM = "docm"
    PPT = "ppt"
    PPTX = "pptx"
    PPS = "pps"
    PPSX = "ppsx"
    XLS = "xls"
    XLSX = "xlsx"
    XLSM = "xlsm"
    XLSB = "xlsb"
    ODT = "odt"
    ODS = "ods"
    ODP = "odp"
    RTF = "rtf"
    EPUB = "epub"
    CSV = "csv"
    PDF = "pdf"
    UNKNOWN = "unknown"


class ConversionStatus(StrEnum):
    """Estados del resultado de una conversión con AnyDoc."""

    SUCCESS = "SUCCESS"
    NEEDS_OCR = "NEEDS_OCR"
    UNSUPPORTED = "UNSUPPORTED"
    MALFORMED = "MALFORMED"
    ENCRYPTED = "ENCRYPTED"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    MISSING_PART = "MISSING_PART"
    IO_ERROR = "IO_ERROR"
    SECURITY_BLOCKED = "SECURITY_BLOCKED"
    TIMEOUT = "TIMEOUT"
    CLAIMED_SUCCESS = "CLAIMED_SUCCESS"
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    DENIED = "DENIED"


@dataclass(frozen=True)
class AnyDocTaskContract:
    """Contrato inmutable formal de tarea documental emitido y sellado bajo decisión JDE."""

    task_id: str
    decision_id: str
    operation_id: str
    input_path: str
    input_format: str
    output_path: str
    operation: str = "document_processing.convert"
    allowed_actions: list[str] = field(default_factory=lambda: ["read", "convert"])
    forbidden_actions: list[str] = field(default_factory=lambda: ["ocr_external", "network_outbound", "arbitrary_write"])
    max_input_size: int = 50 * 1024 * 1024       # 50 MB límite por defecto
    max_output_size: int = 100 * 1024 * 1024    # 100 MB límite por defecto
    timeout_seconds: float = 30.0
    network_policy: str = "DENY"
    requires_review: bool = False
    risk_level: RiskLevel = RiskLevel.SAFE
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def compute_fingerprint(self, input_hash: str, anydoc_version: str = "0.2.4") -> str:
        """Calcula la huella criptográfica canónica SHA-256 para idempotencia."""
        payload = {
            "input_hash": input_hash.strip(),
            "operation": self.operation.strip(),
            "allowed_actions": sorted(self.allowed_actions),
            "anydoc_version": anydoc_version.strip(),
            "input_format": self.input_format.strip(),
            "output_path": self.output_path.strip(),
            "requires_review": self.requires_review,
        }
        raw_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw_bytes).hexdigest()

    def compute_seal(self) -> str:
        """Calcula el sello inmutable para prevenir manipulación post-autorización JDE."""
        seal_payload = (
            f"{self.task_id}:{self.decision_id}:{self.input_path}:{self.output_path}:"
            f"{self.operation}:{self.risk_level.value}:{self.network_policy}:"
            f"{','.join(sorted(self.allowed_actions))}:{','.join(sorted(self.forbidden_actions))}"
        )
        return hashlib.sha256(seal_payload.encode("utf-8")).hexdigest()

    def verify_seal(self, expected_seal: str) -> bool:
        """Verifica la integridad del contrato contra alteraciones de parámetros."""
        return self.compute_seal() == expected_seal

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "decision_id": self.decision_id,
            "operation_id": self.operation_id,
            "input_path": self.input_path,
            "input_format": self.input_format,
            "output_path": self.output_path,
            "operation": self.operation,
            "allowed_actions": self.allowed_actions,
            "forbidden_actions": self.forbidden_actions,
            "max_input_size": self.max_input_size,
            "max_output_size": self.max_output_size,
            "timeout_seconds": self.timeout_seconds,
            "network_policy": self.network_policy,
            "requires_review": self.requires_review,
            "risk_level": self.risk_level.value,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class AnyDocProposal:
    """Propuesta estructurada de procesamiento documental hacia el JDE."""

    proposal_id: str
    decision_id: str
    operation_id: str
    input_path: str
    format: str
    output_path: str | None = None
    operation: str = "document_processing.convert"
    risk_level: RiskLevel = RiskLevel.SAFE
    network_required: bool = False
    requires_review: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "decision_id": self.decision_id,
            "operation_id": self.operation_id,
            "input_path": self.input_path,
            "format": self.format,
            "output_path": self.output_path,
            "operation": self.operation,
            "risk_level": self.risk_level.value,
            "network_required": self.network_required,
            "requires_review": self.requires_review,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass
class AnyDocReceipt:
    """Recibo formal emitido y firmado tras la ejecución gobernada de una tarea documental."""

    receipt_id: str
    decision_id: str
    operation_id: str
    task_id: str
    input_hash: str
    output_hash: str | None
    capability: str
    risk_level: str
    verified: bool
    status: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "decision_id": self.decision_id,
            "operation_id": self.operation_id,
            "task_id": self.task_id,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "capability": self.capability,
            "risk_level": self.risk_level,
            "verified": self.verified,
            "status": self.status,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class AnyDocResult:
    """Resultado formal estructurado de una operación AnyDoc."""

    operation_id: str
    status: ConversionStatus
    input_path: str
    detected_format: str
    output_markdown: str | None = None
    output_path: str | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    error_message: str | None = None
    latency_ms: float = 0.0
    input_size_bytes: int = 0
    output_char_count: int = 0
    verified: bool = False
    side_effects: int = 0
    receipt: AnyDocReceipt | None = None
    document_model_summary: dict[str, Any] = field(default_factory=dict)
    extracted_structure: dict[str, Any] = field(default_factory=dict)
    extracted_assets: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "status": self.status.value,
            "input_path": self.input_path,
            "detected_format": self.detected_format,
            "output_markdown_length": len(self.output_markdown) if self.output_markdown else 0,
            "output_path": self.output_path,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "error_message": self.error_message,
            "latency_ms": self.latency_ms,
            "input_size_bytes": self.input_size_bytes,
            "output_char_count": self.output_char_count,
            "verified": self.verified,
            "side_effects": self.side_effects,
            "receipt": self.receipt.to_dict() if self.receipt else None,
            "document_model_summary": self.document_model_summary,
            "extracted_structure": self.extracted_structure,
            "extracted_assets_count": len(self.extracted_assets),
            "metadata": self.metadata,
        }
