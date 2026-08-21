"""Verificador de compatibilidad técnica y de arquitectura para Skills (skill_compatibility.py - Fase 32).

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
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_compatible": self.is_compatible,
            "reason": self.reason,
            "gaps": list(self.gaps),
            "warnings": list(self.warnings),
            "jessyca_version": self.jessyca_version,
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
    ) -> CompatibilityCheckResult:
        """Comprueba la compatibilidad integral de un manifiesto con el entorno actual."""
        gaps: list[str] = []
        warnings: list[str] = []

        # 1. Comprobar versión mínima del sistema JESSYCA (SemVer comparison)
        min_sys_ver = manifest.min_system_version
        if not cls._is_version_compatible(CURRENT_JESSYCA_VERSION, min_sys_ver):
            gaps.append(
                f"Versión de JESSYCA incompatible: el sistema ejecuta v{CURRENT_JESSYCA_VERSION}, pero la skill requiere v{min_sys_ver} o superior."
            )

        # 2. Comprobar capabilities declaradas
        for cap in manifest.capabilities:
            cap_clean = cap.strip().lower()
            if cap_clean not in ALLOWED_SKILL_CAPABILITIES:
                # Si no está en las estándar, advertir o bloquear si es malformada
                if not re.match(r"^[a-zA-Z0-9_\-\.]+$", cap_clean):
                    gaps.append(f"Capacidad declarada con formato no válido: '{cap}'.")
                else:
                    warnings.append(f"Capacidad personalizada no nativa: '{cap}'.")

        # 3. Comprobar agentes requeridos
        active_agents = available_agents if available_agents is not None else set(KNOWN_SYSTEM_AGENTS)
        for req_agent in manifest.required_agents:
            if req_agent not in active_agents:
                # Comprobar tolerancia por mayúsculas/minúsculas
                matching = [a for a in active_agents if a.lower() == req_agent.lower()]
                if not matching:
                    gaps.append(f"Agente requerido no disponible en el sistema: '{req_agent}'.")

        # 4. Comprobar modelos requeridos
        active_models = available_models if available_models is not None else set(KNOWN_SYSTEM_MODELS)
        for req_model in manifest.required_models:
            # Tolerancia de nombres de modelos (ej: llama3.2 vs llama3.2:latest)
            req_clean = req_model.lower().split(":")[0]
            matched = any(req_clean == m.lower().split(":")[0] for m in active_models)
            if not matched:
                warnings.append(f"Modelo de IA recomendado/requerido no detectado localmente: '{req_model}'.")

        # 5. Determinar veredicto final
        if gaps:
            reason = f"Instalación bloqueada por incompatibilidad de entorno: {'; '.join(gaps)}"
            logger.warning(f"[COMPATIBILITY BLOCKED] Skill '{manifest.id}': {reason}")
            return CompatibilityCheckResult(
                is_compatible=False,
                reason=reason,
                gaps=tuple(gaps),
                warnings=tuple(warnings),
            )

        return CompatibilityCheckResult(
            is_compatible=True,
            reason="La Skill es 100% compatible con el entorno de JESSYCA 3.0.",
            gaps=(),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _is_version_compatible(current: str, required_min: str) -> bool:
        """Compara versiones SemVer simples (major.minor.patch)."""
        def parse(v: str) -> tuple[int, ...]:
            clean = v.split("-")[0]
            parts = clean.split(".")
            return tuple(int(p) if p.isdigit() else 0 for p in parts)

        try:
            curr_parts = parse(current)
            req_parts = parse(required_min)
            return curr_parts >= req_parts
        except Exception:
            return True
