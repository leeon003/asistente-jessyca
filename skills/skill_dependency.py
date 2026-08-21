"""Validador formal y análisis de grafo de dependencias de Skills (skill_dependency.py - Fase 32).

Verifica la satisfacción de dependencias entre Skills, detecta ciclos (dependencias circulares),
dependencias ausentes, deshabilitadas o incompatibles, y previene la instalación arbitraria de paquetes externos.

INVARIANTE DE SEGURIDAD:
Prohibida la ejecución silenciosa de comandos como 'pip install <desconocido>'.
Toda dependencia de terceros debe ser validada o provista por el entorno base aislado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger
from skills.skill_models import (
    SkillManifest,
    SkillStatus,
)
from skills.skill_registry import SkillRegistry, get_skill_registry

logger = get_logger("jessyca.skills.dependency")


@dataclass(frozen=True)
class DependencyValidationResult:
    """Resultado formal inmutable de la validación de dependencias."""

    is_valid: bool
    reason: str
    missing_dependencies: tuple[str, ...] = ()
    incompatible_dependencies: tuple[str, ...] = ()
    circular_dependencies: tuple[str, ...] = ()
    disabled_dependencies: tuple[str, ...] = ()
    resolved_dependencies: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "reason": self.reason,
            "missing_dependencies": list(self.missing_dependencies),
            "incompatible_dependencies": list(self.incompatible_dependencies),
            "circular_dependencies": list(self.circular_dependencies),
            "disabled_dependencies": list(self.disabled_dependencies),
            "resolved_dependencies": list(self.resolved_dependencies),
            "details": self.details,
        }


class SkillDependencyValidator:
    """Validador de dependencias y analizador topológico de Skills."""

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self.registry = registry or get_skill_registry()

    def validate_dependencies(
        self,
        manifest: SkillManifest,
        all_candidate_manifests: dict[str, SkillManifest] | None = None,
    ) -> DependencyValidationResult:
        """Valida que todas las dependencias declaradas existan, sean compatibles y no formen ciclos."""
        missing: list[str] = []
        incompatible: list[str] = []
        disabled: list[str] = []
        resolved: list[str] = []

        declared_deps = manifest.dependencies  # {skill_id: min_version}
        candidate_map = all_candidate_manifests or {}

        installed_versions = self.registry.get_installed_versions()

        for dep_id, required_min_ver in declared_deps.items():
            dep_id_clean = dep_id.strip()

            # 1. Comprobar si está en los candidatos o ya instalada en registry
            if dep_id_clean in candidate_map:
                dep_manifest = candidate_map[dep_id_clean]
                actual_ver = dep_manifest.version
            elif dep_id_clean in installed_versions:
                actual_ver = installed_versions[dep_id_clean]
                # Comprobar estado de habilitación
                status = self.registry.get_status(dep_id_clean)
                if status == SkillStatus.DISABLED:
                    disabled.append(f"{dep_id_clean}@{actual_ver}")
            else:
                missing.append(f"{dep_id_clean} (min: {required_min_ver})")
                continue

            # 2. Comprobar versión mínima requerida
            if not self._is_version_ge(actual_ver, required_min_ver):
                incompatible.append(
                    f"{dep_id_clean}: versión instalada {actual_ver} no satisface requerimiento >= {required_min_ver}"
                )
            else:
                resolved.append(f"{dep_id_clean}@{actual_ver}")

        # 3. Detección de ciclos / Dependencias circulares
        circular = self._detect_circular_dependencies(manifest, candidate_map)

        if missing or incompatible or circular or disabled:
            err_parts = []
            if missing:
                err_parts.append(f"Dependencias ausentes: {missing}")
            if incompatible:
                err_parts.append(f"Versiones incompatibles: {incompatible}")
            if circular:
                err_parts.append(f"Dependencia circular detectada: {' -> '.join(circular)}")
            if disabled:
                err_parts.append(f"Dependencias deshabilitadas: {disabled}")

            reason = "Fallo de validación de dependencias: " + "; ".join(err_parts)
            logger.warning(f"[DEPENDENCY VALIDATION FAILED] Skill '{manifest.id}': {reason}")
            return DependencyValidationResult(
                is_valid=False,
                reason=reason,
                missing_dependencies=tuple(missing),
                incompatible_dependencies=tuple(incompatible),
                circular_dependencies=tuple(circular),
                disabled_dependencies=tuple(disabled),
                resolved_dependencies=tuple(resolved),
            )

        return DependencyValidationResult(
            is_valid=True,
            reason="Todas las dependencias declaradas fueron resueltas y verificadas con éxito.",
            resolved_dependencies=tuple(resolved),
        )

    def _detect_circular_dependencies(
        self,
        root_manifest: SkillManifest,
        candidate_map: dict[str, SkillManifest],
    ) -> list[str]:
        """Detecta si existe un ciclo recursivo en el grafo de dependencias de Skills."""
        # Construir grafo adyacente simple {skill_id: set(deps)}
        adj: dict[str, set[str]] = {root_manifest.id: set(root_manifest.dependencies.keys())}

        for s_id, sm in candidate_map.items():
            adj[s_id] = set(sm.dependencies.keys())

        for reg_def in self.registry.list_skills():
            if reg_def.manifest:
                adj[reg_def.skill_id] = set(reg_def.manifest.dependencies.keys())

        visited: set[str] = set()
        rec_stack: list[str] = []

        def dfs(node: str) -> list[str] | None:
            visited.add(node)
            rec_stack.append(node)

            for neighbor in adj.get(node, set()):
                if neighbor not in visited:
                    res = dfs(neighbor)
                    if res:
                        return res
                elif neighbor in rec_stack:
                    # Ciclo encontrado
                    cycle_idx = rec_stack.index(neighbor)
                    return rec_stack[cycle_idx:] + [neighbor]

            rec_stack.pop()
            return None

        cycle = dfs(root_manifest.id)
        return cycle or []

    @staticmethod
    def _is_version_ge(actual: str, required_min: str) -> bool:
        """Compara si la versión actual es mayor o igual a la requerida."""
        def parse(v: str) -> tuple[int, ...]:
            clean = v.split("-")[0]
            return tuple(int(p) if p.isdigit() else 0 for p in clean.split("."))

        try:
            return parse(actual) >= parse(required_min)
        except Exception:
            return True
