"""Modelos de datos para el repositorio y Marketplace de Skills (skill_repository_models.py - Fase 34).

Define:
- Estados de confianza formales (TrustStatus).
- Estados de verificación de firma del repositorio (SignatureTrustStatus).
- Metadatos de publicación de Skills (RepositorySkillEntry, SkillReputation).
- Tipos de reporte de seguridad y anomalías (SkillReportType, SkillReport).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.security_architecture import SecurityLevel


class TrustStatus(StrEnum):
    """Estados de confianza de una Skill en el Repositorio o Marketplace.

    INVARIANTE DE SEGURIDAD:
    - UNKNOWN jamás se auto-promueve a TRUSTED.
    - La reputación o popularidad NO modifica el TrustStatus.
    """

    TRUSTED = "TRUSTED"        # Firmada por autoridad oficial u organización de máxima confianza
    VERIFIED = "VERIFIED"      # Verificada por partner verificado o desarrollador auditado
    UNKNOWN = "UNKNOWN"        # Sin verificación formal previa o desarrollada por terceros no registrados
    REVOKED = "REVOKED"        # Revocada explícitamente por motivos de seguridad o vulnerabilidad
    INVALID = "INVALID"        # Metadatos, firma o integridad corruptos o fraudulentos


class SignatureTrustStatus(StrEnum):
    """Estados detallados de la firma en el repositorio."""

    VALID = "VALID"
    INVALID = "INVALID"
    MISSING = "MISSING"
    UNKNOWN_SIGNER = "UNKNOWN_SIGNER"
    REVOKED_SIGNER = "REVOKED_SIGNER"


@dataclass(frozen=True)
class SkillReputation:
    """Métricas de reputación de la comunidad (SOLAMENTE INFORMATIVAS).

    INVARIANTE DE SEGURIDAD:
    Las métricas de reputación NUNCA anulan la validación criptográfica, de integridad,
    del sandbox ni el análisis de dependencias.
    """

    downloads: int = 0
    rating: float = 0.0
    review_count: int = 0
    reports_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "downloads": self.downloads,
            "rating": self.rating,
            "review_count": self.review_count,
            "reports_count": self.reports_count,
        }


@dataclass(frozen=True)
class RepositorySkillEntry:
    """Entrada completa de metadatos de una Skill publicada en el Repositorio."""

    id: str
    name: str
    version: str
    description: str
    author: str
    category: str = "general"
    capabilities: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    required_agents: tuple[str, ...] = ()
    required_models: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    risk_level: SecurityLevel = SecurityLevel.SAFE
    dependencies: dict[str, str] = field(default_factory=dict)
    framework_version: str = "1.0.0"
    min_system_version: str = "3.0.0"
    max_system_version: str | None = None
    min_framework_version: str = "1.0.0"
    max_framework_version: str | None = None
    signer_id: str | None = None
    signature_hex: str | None = None
    package_sha256: str = ""
    download_url: str = ""
    release_date: str = ""
    changelog: str = ""
    trust_status: TrustStatus = TrustStatus.UNKNOWN
    reputation: SkillReputation = field(default_factory=SkillReputation)
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "category": self.category,
            "capabilities": list(self.capabilities),
            "required_tools": list(self.required_tools),
            "required_agents": list(self.required_agents),
            "required_models": list(self.required_models),
            "permissions": list(self.permissions),
            "risk_level": str(self.risk_level),
            "dependencies": dict(self.dependencies),
            "framework_version": self.framework_version,
            "min_system_version": self.min_system_version,
            "max_system_version": self.max_system_version,
            "min_framework_version": self.min_framework_version,
            "max_framework_version": self.max_framework_version,
            "signer_id": self.signer_id,
            "signature_hex": self.signature_hex,
            "package_sha256": self.package_sha256,
            "download_url": self.download_url,
            "release_date": self.release_date,
            "changelog": self.changelog,
            "trust_status": str(self.trust_status),
            "reputation": self.reputation.to_dict(),
            "tags": list(self.tags),
        }


class SkillReportType(StrEnum):
    """Categorías formales para reportar una Skill problemática."""

    SECURITY_REPORT = "SECURITY_REPORT"
    MALICIOUS_BEHAVIOR = "MALICIOUS_BEHAVIOR"
    BROKEN_SKILL = "BROKEN_SKILL"
    POLICY_VIOLATION = "POLICY_VIOLATION"


_SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+[a-z0-9_\-\.]{20,})"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*['\"]?[a-z0-9_\-]{16,}['\"]?)"),
    re.compile(r"(?i)(password\s*[:=]\s*['\"]?[^\s'\"]{6,}['\"]?)"),
    re.compile(r"(?i)(secret\s*[:=]\s*['\"]?[a-z0-9_\-]{16,}['\"]?)"),
    re.compile(r"(?i)(token\s*[:=]\s*['\"]?[a-z0-9_\-\.]{16,}['\"]?)"),
]


def redact_sensitive_data(text: str) -> str:
    """Sanitiza y ofusca tokens, contraseñas y claves de API antes del reporte."""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


@dataclass(frozen=True)
class SkillReport:
    """Reporte formal de seguridad o anomalía de una Skill.

    Aplica sanitización automática en detalles para prevenir fuga de credenciales.
    """

    skill_id: str
    version: str
    report_type: SkillReportType
    reporter_id: str
    description: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def get_sanitized_description(self) -> str:
        return redact_sensitive_data(self.description)

    def to_dict(self) -> dict[str, Any]:
        # Sanitizar valores de string dentro de details
        sanitized_details: dict[str, Any] = {}
        for k, v in self.details.items():
            if isinstance(v, str):
                sanitized_details[k] = redact_sensitive_data(v)
            else:
                sanitized_details[k] = v

        return {
            "skill_id": self.skill_id,
            "version": self.version,
            "report_type": str(self.report_type),
            "reporter_id": self.reporter_id,
            "description": self.get_sanitized_description(),
            "details": sanitized_details,
            "timestamp": self.timestamp,
        }
