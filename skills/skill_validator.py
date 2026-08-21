"""Validador estricto de definiciones y capacidades de Skills (skill_validator.py - Fase 28.0).

Garantiza la integridad sintáctica, cumplimiento SemVer, consistencia de herramientas y
bloqueo de permisos prohibidos en Skills.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. UNA SKILL NUNCA PUEDE SOLICITAR PERMISOS PROHIBIDOS (security.override, admin.grant, kernel.bypass).
2. CONSISTENCIA DE RIESGO: Acciones destructivas no pueden declararse como SAFE.
"""

from __future__ import annotations

from core.exceptions import MCPError
from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.skill_models import (
    SEMVER_REGEX,
    SKILL_ID_REGEX,
    SkillDefinition,
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
        if "delete" in desc_lower or "format" in desc_lower or "destroy" in desc_lower:
            if definition.risk_level == SecurityLevel.SAFE:
                return False, f"La skill '{definition.skill_id}' contiene operaciones destructivas pero declara risk_level SAFE. Intento de degradación de riesgo rechazado."

        return True, None
