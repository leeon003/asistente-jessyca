"""Validador estricto de manifiestos, definiciones y capacidades de Skills (skill_validator.py - Fase 28.1).

Garantiza la integridad sintáctica, cumplimiento SemVer, consistencia de herramientas y
bloqueo de permisos prohibidos y privilege escalation en Skills y Manifests.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. UN MANIFIESTO NO OTORGA PERMISOS POR SÍ MISMO.
2. RECHAZA PROHIBICIONES DE SEGURIDAD (security.override, admin.grant, kernel.bypass, *).
3. ANTI-DEGRADACIÓN DE RIESGO: Operaciones destructivas no pueden declararse como SAFE.
4. ENTRYPOINT SEGURO: Sin path traversal ni rutas absolutas.
"""

from __future__ import annotations

import re

from core.exceptions import MCPError
from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.skill_models import (
    ALLOWED_SKILL_CAPABILITIES,
    SEMVER_REGEX,
    SKILL_ID_REGEX,
    SkillDefinition,
    SkillManifest,
)

logger = get_logger("jessyca.skills.validator")

FORBIDDEN_SKILL_PERMISSIONS: set[str] = {
    "security.override",
    "kernel.bypass",
    "system.unrestricted",
    "admin.grant",
    "emergency_stop.bypass",
    "risk_engine.modify",
    "permission_manager.override",
    "*",
}

SECURITY_TAMPERING_KEYWORDS: set[str] = {
    "__proto__",
    "constructor",
    "emergencystopmanager",
    "securitypipeline",
    "riskengine",
    "permissionmanager",
    "confirmationmanager",
}


class SkillValidationError(MCPError):
    """Error emitido cuando una Skill viola las reglas de validación estructural o de seguridad."""

    pass


class SkillValidator:
    """Validador central de seguridad e integridad para el Skill Framework."""

    @staticmethod
    def validate(definition: SkillDefinition) -> tuple[bool, str | None]:
        """Valida una SkillDefinition antes de su registro o carga en el sistema."""
        # 1. Validar ID de la Skill
        if not definition.skill_id or not SKILL_ID_REGEX.match(definition.skill_id):
            return False, f"Identificador de skill inválido: '{definition.skill_id}'. Debe contener solo caracteres alfanuméricos, guiones o puntos."

        # 2. Validar Versión SemVer
        if not definition.version or not SEMVER_REGEX.match(definition.version):
            return False, f"Versión '{definition.version}' de la skill '{definition.skill_id}' no cumple con el formato SemVer (ej: 1.0.0)."

        # 3. Validar Nombre y Descripción
        if not definition.name or not definition.name.strip():
            return False, f"La skill '{definition.skill_id}' debe tener un nombre no vacío."

        # 4. Validar Permisos Prohibidos
        for perm in definition.required_permissions:
            p_clean = perm.strip().lower()
            if p_clean in FORBIDDEN_SKILL_PERMISSIONS:
                return False, f"La skill '{definition.skill_id}' solicita el permiso prohibido '{perm}'. Operación denegada por seguridad inmutable."

        # 5. Validar Consistencia de Riesgo
        desc_lower = (definition.description + " " + definition.name).lower()
        if any(k in desc_lower for k in ("delete", "format", "destroy", "purge", "wipe")):
            if definition.risk_level in (SecurityLevel.SAFE, SecurityLevel.LOW):
                return False, f"La skill '{definition.skill_id}' contiene operaciones destructivas pero declara risk_level SAFE/LOW. Intento de degradación de riesgo rechazado."

        return True, None

    @classmethod
    def validate_manifest(
        cls,
        manifest: SkillManifest,
        installed_skills: dict[str, str] | None = None,
    ) -> tuple[bool, str | None]:
        """Valida rigurosamente un SkillManifest antes de autorizar la carga de la Skill (Fase 28.1)."""
        installed = installed_skills or {}

        # 1. Identificador de la Skill
        if not manifest.id or not SKILL_ID_REGEX.match(manifest.id):
            return False, f"Identificador de manifest inválido: '{manifest.id}'. Debe ser alfanumérico con guiones o puntos."

        # 2. Nombre
        if not manifest.name or not manifest.name.strip():
            return False, f"El manifest '{manifest.id}' carece de nombre válido."

        # 3. Versión SemVer
        if not manifest.version or not SEMVER_REGEX.match(manifest.version):
            return False, f"Versión '{manifest.version}' del manifest '{manifest.id}' no cumple con SemVer (ej: 1.0.0)."

        # 4. Descripción y Autor
        if not manifest.description or not manifest.description.strip():
            return False, f"El manifest '{manifest.id}' carece de descripción requerida."

        if not manifest.author or not manifest.author.strip():
            return False, f"El manifest '{manifest.id}' carece de autor requerido."

        # 5. Entrypoint seguro (prevenir path traversal y rutas absolutas)
        ep = manifest.entrypoint.strip()
        if not ep or ep.startswith("/") or ep.startswith("\\") or ":" in ep or ".." in ep or "\x00" in ep:
            return False, f"Entrypoint inseguro o con path traversal detectado en manifest '{manifest.id}': '{manifest.entrypoint}'."

        # 6. Capacidades declaradas y reconocidas
        if not manifest.capabilities:
            return False, f"El manifest '{manifest.id}' debe declarar al menos una capacidad válida en 'capabilities'."

        seen_caps: set[str] = set()
        for cap in manifest.capabilities:
            cap_clean = cap.strip().lower()
            if cap_clean in seen_caps:
                return False, f"Capacidad duplicada detectada en manifest '{manifest.id}': '{cap}'."
            if cap_clean not in ALLOWED_SKILL_CAPABILITIES:
                return False, f"Capacidad desconocida o no permitida en manifest '{manifest.id}': '{cap}'."
            seen_caps.add(cap_clean)

        # 7. Formato de herramientas requeridas
        for tool in manifest.required_tools:
            if not tool or not SKILL_ID_REGEX.match(tool.strip()):
                return False, f"Herramienta requerida inválida o desconocida en manifest '{manifest.id}': '{tool}'."

        # 8. Permisos prohibidos y privilege escalation
        for perm in manifest.permissions:
            p_clean = perm.strip().lower()
            if p_clean in FORBIDDEN_SKILL_PERMISSIONS:
                return False, f"Intento de escalada de privilegios: Permiso prohibido '{perm}' en manifest '{manifest.id}'."

        # 9. Detección de manipulación de seguridad en metadatos
        combined_meta = f"{manifest.id} {manifest.name} {manifest.description} {manifest.author}".lower()
        for kw in SECURITY_TAMPERING_KEYWORDS:
            if kw in combined_meta:
                return False, f"Intento malicioso de manipulación de seguridad detectado con palabra clave '{kw}' en manifest '{manifest.id}'."

        # 10. Consistencia de nivel de riesgo
        desc_lower = (manifest.description + " " + manifest.name).lower()
        if any(k in desc_lower for k in ("delete", "format", "destroy", "purge", "wipe")):
            if manifest.risk_level in (SecurityLevel.SAFE, SecurityLevel.LOW):
                return False, f"Degradación de riesgo inválida: La skill '{manifest.id}' realiza acciones destructivas pero declara riesgo SAFE/LOW."

        # 11. Dependencias
        for dep_id, min_ver in manifest.dependencies.items():
            if dep_id not in installed:
                return False, f"Dependencia faltante: La skill '{manifest.id}' requiere '{dep_id}' (>= {min_ver}) pero no está disponible."

            inst_ver = installed[dep_id]
            if not cls._is_version_compatible(inst_ver, min_ver):
                return False, f"Versión incompatible de dependencia '{dep_id}': Instalada '{inst_ver}' < Requerida '{min_ver}'."

        return True, None

    @staticmethod
    def _is_version_compatible(installed_version: str, required_version: str) -> bool:
        """Compara versiones SemVer simples (major.minor.patch)."""
        try:
            inst_parts = [int(p) for p in re.split(r"[-.]", installed_version)[:3] if p.isdigit()]
            req_parts = [int(p) for p in re.split(r"[-.]", required_version)[:3] if p.isdigit()]
            return inst_parts >= req_parts
        except Exception:
            return installed_version == required_version
