"""Revisor y generador de resumen estructurado de permisos para Skills (skill_permission_reviewer.py - Fase 32).

Produce una representación estructurada, legible y explicable de los permisos, capacidades,
recursos del sistema y nivel de riesgo que solicita una Skill externa antes de su instalación.

INVARIANTE:
El usuario o el sistema pueden rechazar la instalación de forma fundamentada tras revisar este objeto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.security_architecture import SecurityLevel
from skills.skill_models import SkillManifest
from skills.skill_package import SkillPackage
from skills.skill_signature import SignatureStatus


@dataclass(frozen=True)
class SkillPermissionReview:
    """Revisión estructurada e inmutable de permisos y capacidades de una Skill."""

    skill_id: str
    name: str
    version: str
    author: str
    capabilities: tuple[str, ...]
    tools: tuple[str, ...]
    agents: tuple[str, ...]
    models: tuple[str, ...]
    filesystem_access: str  # "None", "Read-Only", "Read-Write"
    network_access: bool
    browser_access: bool
    system_access: bool
    risk_level: SecurityLevel
    permissions: tuple[str, ...]
    signature_status: SignatureStatus
    is_approved_for_install: bool
    warnings: tuple[str, ...] = ()
    rejection_reasons: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "capabilities": list(self.capabilities),
            "tools": list(self.tools),
            "agents": list(self.agents),
            "models": list(self.models),
            "filesystem_access": self.filesystem_access,
            "network_access": self.network_access,
            "browser_access": self.browser_access,
            "system_access": self.system_access,
            "risk_level": str(self.risk_level),
            "permissions": list(self.permissions),
            "signature_status": str(self.signature_status),
            "is_approved_for_install": self.is_approved_for_install,
            "warnings": list(self.warnings),
            "rejection_reasons": list(self.rejection_reasons),
            "details": self.details,
        }

    def to_markdown_summary(self) -> str:
        """Genera un reporte en Markdown legible para inspección en interfaces de usuario."""
        status_icon = "✅ AUTORIZABLE" if self.is_approved_for_install else "❌ RECHAZADA"
        lines = [
            f"### Revisión de Seguridad: {self.name} (`{self.skill_id}@{self.version}`)",
            f"- **Estado de Instalabilidad**: {status_icon}",
            f"- **Nivel de Riesgo**: `{self.risk_level}`",
            f"- **Firma Digital**: `{self.signature_status}`",
            f"- **Acceso al Sistema de Archivos**: `{self.filesystem_access}`",
            f"- **Acceso a Red / Internet**: `{'Sí' if self.network_access else 'No'}`",
            f"- **Acceso a Navegador Web**: `{'Sí' if self.browser_access else 'No'}`",
            f"- **Acceso a APIs de Sistema**: `{'Sí' if self.system_access else 'No'}`",
            f"- **Herramientas Requeridas**: `{', '.join(self.tools) or 'Ninguna'}`",
            f"- **Agentes Requeridos**: `{', '.join(self.agents) or 'Ninguno'}`",
            f"- **Modelos Requeridos**: `{', '.join(self.models) or 'Ninguno'}`",
        ]
        if self.warnings:
            lines.append(f"- **Advertencias**: {', '.join(self.warnings)}")
        if self.rejection_reasons:
            lines.append(f"- **Motivos de Rechazo**: {', '.join(self.rejection_reasons)}")
        return "\n".join(lines)


class SkillPermissionReviewer:
    """Generador de revisiones de permisos para paquetes de Skills."""

    @classmethod
    def review_package(
        cls,
        package: SkillPackage,
        signature_status: SignatureStatus = SignatureStatus.UNSIGNED,
        security_violations: tuple[str, ...] = (),
        security_warnings: tuple[str, ...] = (),
    ) -> SkillPermissionReview:
        """Construye un análisis detallado de los accesos y permisos solicitados."""
        manifest: SkillManifest = package.manifest

        caps_lower = [c.lower() for c in manifest.capabilities]
        perms_lower = [p.lower() for p in manifest.permissions]

        # Determinar acceso a filesystem
        has_fs_write = any("write" in c or "create" in c or "modify" in c for c in caps_lower + perms_lower)
        has_fs_read = any("read" in c or "search" in c or "filesystem" in c for c in caps_lower + perms_lower)

        if has_fs_write:
            fs_access = "Read-Write"
        elif has_fs_read:
            fs_access = "Read-Only"
        else:
            fs_access = "None"

        # Determinar acceso a red
        net_access = any("network" in c or "internet" in c or "http" in c or "web" in c for c in caps_lower)

        # Determinar acceso a navegador
        browser_access = any("browser" in c for c in caps_lower) or any("browser" in t for t in manifest.required_tools)

        # Determinar acceso a sistema/OS
        sys_access = any("system" in c or "hardware" in c or "windows" in c for c in caps_lower)

        # Motivos de rechazo
        rejections: list[str] = list(security_violations)
        warnings: list[str] = list(security_warnings)

        if signature_status == SignatureStatus.INVALID_SIGNATURE:
            rejections.append("La firma digital del paquete es inválida o ha sido manipulada.")

        is_approved = len(rejections) == 0

        return SkillPermissionReview(
            skill_id=manifest.id,
            name=manifest.name,
            version=manifest.version,
            author=manifest.author,
            capabilities=manifest.capabilities,
            tools=manifest.required_tools,
            agents=manifest.required_agents,
            models=manifest.required_models,
            filesystem_access=fs_access,
            network_access=net_access,
            browser_access=browser_access,
            system_access=sys_access,
            risk_level=manifest.risk_level,
            permissions=manifest.permissions,
            signature_status=signature_status,
            is_approved_for_install=is_approved,
            warnings=tuple(warnings),
            rejection_reasons=tuple(rejections),
        )
