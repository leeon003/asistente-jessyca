"""Generador estructurado de reportes de cambio y diferencias de Skills (skill_diff.py - Fase 33).

Permite comparar dos versiones de un SkillManifest para detectar:
- Incrementos SemVer (MAJOR, MINOR, PATCH, DOWNGRADE, SAME).
- Capabilities añadidas, eliminadas o modificadas.
- Tools nuevas o retiradas.
- Permisos nuevos o retirados.
- Dependencias añadidas, retiradas o con versiones actualizadas.
- Alteración de nivel de riesgo (ELEVATED, REDUCED, UNCHANGED).
- Cambios rompientes (breaking changes).
- Requerimiento de confirmación del usuario según las políticas de seguridad.

INVARIANTE:
Antes de activar una nueva versión, se debe generar y evaluar un SkillChangeReport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.security_architecture import SecurityLevel
from skills.skill_compatibility import CompatibilityCheckResult
from skills.skill_models import SkillManifest
from skills.skill_signature import SignatureStatus
from skills.skill_version import SemVer, VersionBumpType

# Mapeo numérico para comparar niveles de severidad de riesgo
RISK_LEVEL_WEIGHT: dict[SecurityLevel, int] = {
    SecurityLevel.SAFE: 0,
    SecurityLevel.LOW: 1,
    SecurityLevel.MEDIUM: 2,
    SecurityLevel.HIGH: 3,
    SecurityLevel.CRITICAL: 4,
}


@dataclass(frozen=True)
class SkillChangeReport:
    """Reporte estructurado e inmutable de diferencias entre versiones de una Skill."""

    skill_id: str
    old_version: str | None
    new_version: str
    bump_type: VersionBumpType
    changed_capabilities: dict[str, list[str]]  # {"added": [...], "removed": [...], "retained": [...]}
    new_tools: tuple[str, ...]
    removed_tools: tuple[str, ...]
    new_permissions: tuple[str, ...]
    removed_permissions: tuple[str, ...]
    new_dependencies: dict[str, str]
    removed_dependencies: tuple[str, ...]
    updated_dependencies: dict[str, tuple[str, str]]  # dep_id -> (old_min, new_min)
    old_risk_level: SecurityLevel | None
    new_risk_level: SecurityLevel
    risk_change: str  # "ELEVATED", "REDUCED", "UNCHANGED"
    is_breaking: bool
    requires_user_confirmation: bool
    compatibility: CompatibilityCheckResult | None = None
    signature_status: SignatureStatus = SignatureStatus.UNSIGNED
    integrity_valid: bool = True
    rejection_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "bump_type": str(self.bump_type),
            "changed_capabilities": self.changed_capabilities,
            "new_tools": list(self.new_tools),
            "removed_tools": list(self.removed_tools),
            "new_permissions": list(self.new_permissions),
            "removed_permissions": list(self.removed_permissions),
            "new_dependencies": self.new_dependencies,
            "removed_dependencies": list(self.removed_dependencies),
            "updated_dependencies": {
                k: [v[0], v[1]] for k, v in self.updated_dependencies.items()
            },
            "old_risk_level": str(self.old_risk_level) if self.old_risk_level else None,
            "new_risk_level": str(self.new_risk_level),
            "risk_change": self.risk_change,
            "is_breaking": self.is_breaking,
            "requires_user_confirmation": self.requires_user_confirmation,
            "compatibility": self.compatibility.to_dict() if self.compatibility else None,
            "signature_status": str(self.signature_status),
            "integrity_valid": self.integrity_valid,
            "rejection_reasons": list(self.rejection_reasons),
            "warnings": list(self.warnings),
            "created_at": self.created_at,
        }


class SkillDiffer:
    """Comparador formal de especificaciones y manifiestos de Skills."""

    @classmethod
    def compare(
        cls,
        old_manifest: SkillManifest | None,
        new_manifest: SkillManifest,
        signature_status: SignatureStatus = SignatureStatus.UNSIGNED,
        integrity_valid: bool = True,
        compatibility_result: CompatibilityCheckResult | None = None,
    ) -> SkillChangeReport:
        """Compara un manifiesto existente con el nuevo para emitir el SkillChangeReport."""
        skill_id = new_manifest.id
        new_ver_str = new_manifest.version
        old_ver_str = old_manifest.version if old_manifest else None

        # 1. Determinar Tipo de Incremento SemVer
        if old_manifest:
            try:
                new_semver = SemVer.parse(new_ver_str)
                old_semver = SemVer.parse(old_ver_str or "0.0.0")
                bump_type = new_semver.bump_type_from(old_semver)
            except Exception:
                bump_type = VersionBumpType.MAJOR
        else:
            bump_type = VersionBumpType.MAJOR

        # 2. Capabilities diff
        old_caps = set(old_manifest.capabilities) if old_manifest else set()
        new_caps = set(new_manifest.capabilities)
        added_caps = sorted(new_caps - old_caps)
        removed_caps = sorted(old_caps - new_caps)
        retained_caps = sorted(new_caps & old_caps)

        changed_capabilities = {
            "added": added_caps,
            "removed": removed_caps,
            "retained": retained_caps,
        }

        # 3. Required Tools diff
        old_tools = set(old_manifest.required_tools) if old_manifest else set()
        new_tools = set(new_manifest.required_tools)
        added_tools = tuple(sorted(new_tools - old_tools))
        removed_tools = tuple(sorted(old_tools - new_tools))

        # 4. Permissions diff
        old_perms = set(old_manifest.permissions) if old_manifest else set()
        new_perms = set(new_manifest.permissions)
        added_perms = tuple(sorted(new_perms - old_perms))
        removed_perms = tuple(sorted(old_perms - new_perms))

        # 5. Dependencies diff
        old_deps = old_manifest.dependencies if old_manifest else {}
        new_deps = new_manifest.dependencies
        added_deps: dict[str, str] = {}
        removed_deps: list[str] = []
        updated_deps: dict[str, tuple[str, str]] = {}

        for k, v in new_deps.items():
            if k not in old_deps:
                added_deps[k] = v
            elif old_deps[k] != v:
                updated_deps[k] = (old_deps[k], v)

        for k in old_deps:
            if k not in new_deps:
                removed_deps.append(k)

        # 6. Risk Level comparison
        old_risk = old_manifest.risk_level if old_manifest else None
        new_risk = new_manifest.risk_level

        if old_risk is None:
            risk_change = "UNCHANGED"
        else:
            old_w = RISK_LEVEL_WEIGHT.get(old_risk, 0)
            new_w = RISK_LEVEL_WEIGHT.get(new_risk, 0)
            if new_w > old_w:
                risk_change = "ELEVATED"
            elif new_w < old_w:
                risk_change = "REDUCED"
            else:
                risk_change = "UNCHANGED"

        # 7. Breaking Changes detection
        is_breaking = False
        reasons: list[str] = []
        warnings: list[str] = []

        if bump_type == VersionBumpType.MAJOR:
            is_breaking = True
        if removed_tools:
            is_breaking = True
            warnings.append(f"Herramientas eliminadas respecto a versión previa: {removed_tools}")
        if removed_caps:
            is_breaking = True
            warnings.append(f"Capacidades eliminadas respecto a versión previa: {removed_caps}")
        if risk_change == "ELEVATED":
            warnings.append(f"Nivel de riesgo elevado: de {old_risk} a {new_risk}")

        # 8. User Confirmation Requirement
        # Requiere confirmación si:
        # - Hay breaking change
        # - Hay elevación de riesgo
        # - Hay permisos nuevos
        # - La nueva versión tiene riesgo HIGH o CRITICAL
        # - Es un downgrade
        requires_user_confirmation = bool(
            is_breaking
            or risk_change == "ELEVATED"
            or added_perms
            or new_risk in (SecurityLevel.HIGH, SecurityLevel.CRITICAL)
            or bump_type == VersionBumpType.DOWNGRADE
        )

        if bump_type == VersionBumpType.DOWNGRADE:
            warnings.append(f"Operación de degradación (downgrade) detectada: v{old_ver_str} -> v{new_ver_str}")

        if not integrity_valid:
            reasons.append("Violación de integridad de paquete detectada.")

        if signature_status == SignatureStatus.INVALID_SIGNATURE:
            reasons.append("Firma digital corrupta o inválida.")

        if compatibility_result and not compatibility_result.is_compatible:
            reasons.append(f"Incompatibilidad de entorno: {compatibility_result.reason}")

        return SkillChangeReport(
            skill_id=skill_id,
            old_version=old_ver_str,
            new_version=new_ver_str,
            bump_type=bump_type,
            changed_capabilities=changed_capabilities,
            new_tools=added_tools,
            removed_tools=removed_tools,
            new_permissions=added_perms,
            removed_permissions=removed_perms,
            new_dependencies=added_deps,
            removed_dependencies=tuple(sorted(removed_deps)),
            updated_dependencies=updated_deps,
            old_risk_level=old_risk,
            new_risk_level=new_risk,
            risk_change=risk_change,
            is_breaking=is_breaking,
            requires_user_confirmation=requires_user_confirmation,
            compatibility=compatibility_result,
            signature_status=signature_status,
            integrity_valid=integrity_valid,
            rejection_reasons=tuple(reasons),
            warnings=tuple(warnings),
        )
