"""Verificador de compatibilidad técnica y de arquitectura para Skills (skill_compatibility.py - Fases 32 y 33).

Evalúa si un paquete de Skill es compatible con la versión en ejecución de JESSYCA, el Skill Framework,
los agentes disponibles, modelos multimodales y herramientas del ecosistema.

INVARIANTE:
Cualquier incompatibilidad estructural o de versión produce INSTALLATION_BLOCKED.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger
from skills.skill_models import (
    ALLOWED_SKILL_CAPABILITIES,
    SkillManifest,
)
from skills.skill_version import SemVer

logger = get_logger("jessyca.skills.compatibility")

CURRENT_JESSYCA_VERSION: str = "3.0.0"
CURRENT_SKILL_FRAMEWORK_VERSION: str = "1.0.0"

KNOWN_SYSTEM_AGENTS: frozenset[str] = frozenset({
    "DesktopAgent",
    "SystemAgent",
    "BrowserAgent",
    "FileAgent",
    "VisionAgent",
    "PlannerAgent",
    "MemoryAgent",
    "SecurityAgent",
})

KNOWN_SYSTEM_MODELS: frozenset[str] = frozenset({
    "llama3.2:latest",
    "llama3.2:3b",
    "qwen3:8b",
    "qwen3-vl:4b",
    "qwen3-vl",
    "all-minilm:latest",
    "faster-whisper-base",
})


@dataclass(frozen=True)
class CompatibilityCheckResult:
    """Resultado inmutable de la verificación de compatibilidad de una Skill."""

    is_compatible: bool
    reason: str
    gaps: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    jessyca_version: str = CURRENT_JESSYCA_VERSION
    framework_version: str = CURRENT_SKILL_FRAMEWORK_VERSION
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_compatible": self.is_compatible,
            "reason": self.reason,
            "gaps": list(self.gaps),
            "warnings": list(self.warnings),
            "jessyca_version": self.jessyca_version,
            "framework_version": self.framework_version,
            "details": self.details,
        }


class SkillCompatibilityChecker:
    """Comprobador formal de compatibilidad para paquetes de Skills."""

    @classmethod
    def check_compatibility(
        cls,
        manifest: SkillManifest,
        available_agents: set[str] | None = None,
        available_models: set[str] | None = None,
        jessyca_version: str = CURRENT_JESSYCA_VERSION,
        framework_version: str = CURRENT_SKILL_FRAMEWORK_VERSION,
    ) -> CompatibilityCheckResult:
        """Comprueba la compatibilidad integral de un manifiesto con el entorno actual."""
        gaps: list[str] = []
        warnings: list[str] = []

        curr_sys_semver = SemVer.parse(jessyca_version)
        curr_fw_semver = SemVer.parse(framework_version)

        # 1. Comprobar versión mínima y máxima del sistema JESSYCA
        try:
            min_sys = SemVer.parse(manifest.min_system_version)
            if curr_sys_semver < min_sys:
                gaps.append(
                    f"Versión de JESSYCA incompatible: el sistema ejecuta v{jessyca_version}, pero la skill requiere v{manifest.min_system_version} o superior."
                )
        except Exception as exc:
            gaps.append(f"Formato de 'min_system_version' inválido en manifest: {exc}")

        if manifest.max_system_version:
            try:
                max_sys = SemVer.parse(manifest.max_system_version)
                if curr_sys_semver > max_sys:
                    gaps.append(
                        f"Versión de JESSYCA incompatible: el sistema ejecuta v{jessyca_version}, superando el límite máximo soportado v{manifest.max_system_version}."
                    )
            except Exception as exc:
                gaps.append(f"Formato de 'max_system_version' inválido en manifest: {exc}")

        # 2. Comprobar versión de Skill Framework
        if manifest.min_framework_version:
            try:
                min_fw = SemVer.parse(manifest.min_framework_version)
                if curr_fw_semver < min_fw:
                    gaps.append(
                        f"Versión de Skill Framework incompatible: el entorno ejecuta v{framework_version}, pero la skill requiere v{manifest.min_framework_version} o superior."
                    )
            except Exception as exc:
                gaps.append(f"Formato de 'min_framework_version' inválido en manifest: {exc}")

        if manifest.max_framework_version:
            try:
                max_fw = SemVer.parse(manifest.max_framework_version)
                if curr_fw_semver > max_fw:
                    gaps.append(
                        f"Versión de Skill Framework incompatible: el entorno ejecuta v{framework_version}, superando el límite máximo soportado v{manifest.max_framework_version}."
                    )
            except Exception as exc:
                gaps.append(f"Formato de 'max_framework_version' inválido en manifest: {exc}")

        # 3. Comprobar capabilities declaradas
        for cap in manifest.capabilities:
            cap_clean = cap.strip().lower()
            if cap_clean not in ALLOWED_SKILL_CAPABILITIES:
                # Si no está en las estándar, advertir o bloquear si es malformada
                if not re.match(r"^[a-zA-Z0-9_\-\.]+$", cap_clean):
                    gaps.append(f"Capacidad declarada con formato no válido: '{cap}'.")
                else:
                    warnings.append(f"Capacidad personalizada no nativa: '{cap}'.")

        # 4. Comprobar agentes requeridos
        active_agents = available_agents if available_agents is not None else set(KNOWN_SYSTEM_AGENTS)
        for req_agent in manifest.required_agents:
            if req_agent not in active_agents:
                matching = [a for a in active_agents if a.lower() == req_agent.lower()]
                if not matching:
                    gaps.append(f"Agente requerido no disponible en el sistema: '{req_agent}'.")

        # 5. Comprobar modelos requeridos
        active_models = available_models if available_models is not None else set(KNOWN_SYSTEM_MODELS)
        for req_model in manifest.required_models:
            req_clean = req_model.lower().split(":")[0]
            matched = any(req_clean == m.lower().split(":")[0] for m in active_models)
            if not matched:
                warnings.append(f"Modelo de IA recomendado/requerido no detectado localmente: '{req_model}'.")

        # 6. Determinar veredicto final
        if gaps:
            reason = f"Instalación bloqueada por incompatibilidad de entorno: {'; '.join(gaps)}"
            logger.warning(f"[COMPATIBILITY BLOCKED] Skill '{manifest.id}': {reason}")
            return CompatibilityCheckResult(
                is_compatible=False,
                reason=reason,
                gaps=tuple(gaps),
                warnings=tuple(warnings),
                jessyca_version=jessyca_version,
                framework_version=framework_version,
            )

        return CompatibilityCheckResult(
            is_compatible=True,
            reason="La Skill es 100% compatible con el entorno de JESSYCA 3.0.",
            gaps=(),
            warnings=tuple(warnings),
            jessyca_version=jessyca_version,
            framework_version=framework_version,
        )
