"""Registro central formal, multi-versión y thread-safe de habilidades (skill_registry.py - Fase 28.3).

Garantiza:
1. IDENTIDAD ÚNICA Y VERSIONADO: Coexistencia de versiones (ej: browser.search@1.0 y @1.1) sin conflictos silenciosos.
2. DISCOVERY MULTIDIMENSIONAL: Búsqueda por ID, capability, categoría, tool, agent y nivel de riesgo.
3. CICLO DE VIDA Y ESTADOS: REGISTERED, VALID, INVALID, ENABLED, DISABLED.
4. AISLAMIENTO DE SEGURIDAD: Registrar una Skill no concede autorización.

INVARIANTE DE SEGURIDAD ABSOLUTA:
Toda ejecución continúa pasando por SecurityPipeline (RiskEngine + PermissionManager).
"""

from __future__ import annotations

import re
import threading
from typing import ClassVar

from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillDefinition,
    SkillStatus,
)
from skills.skill_validator import SkillValidator

logger = get_logger("jessyca.skills.registry")


class SkillRegistryConflictError(Exception):
    """Error emitido ante intento de sobrescritura silenciosa o conflicto de versiones."""

    pass


class SkillRegistry:
    """Catálogo formal y registro central de habilidades (Skills) de JESSYCA."""

    _instance: ClassVar[SkillRegistry | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, validator: SkillValidator | None = None) -> None:
        self._lock = threading.RLock()
        self.validator = validator or SkillValidator()
        # _skills: {skill_id: {version: BaseSkill}}
        self._skills: dict[str, dict[str, BaseSkill]] = {}
        # _definitions: {skill_id: {version: SkillDefinition}}
        self._definitions: dict[str, dict[str, SkillDefinition]] = {}
        # _statuses: {skill_id: {version: SkillStatus}}
        self._statuses: dict[str, dict[str, SkillStatus]] = {}
        # _active_versions: {skill_id: latest_or_active_version}
        self._active_versions: dict[str, str] = {}

    @classmethod
    def get_instance(cls) -> SkillRegistry:
        """Obtiene la instancia singleton global del registro de skills."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = SkillRegistry()
            return cls._instance

    # ── 1. REGISTRO Y VALIDACIÓN ──

    def register_skill(self, skill: BaseSkill, replace: bool = False) -> tuple[bool, str | None]:
        """Valida y registra una instancia de Skill en el catálogo multi-versión."""
        with self._lock:
            definition = skill.definition
            skill_id = definition.skill_id
            version = definition.version

            # Detección de duplicados y conflictos silenciosos
            if skill_id in self._skills and version in self._skills[skill_id] and not replace:
                err_msg = (
                    f"Conflicto de versión: La Skill '{skill_id}@{version}' ya se encuentra registrada. "
                    "No se permiten sobrescrituras silenciosas."
                )
                logger.warning(f"[SKILL REGISTRATION CONFLICT] {err_msg}")
                return False, err_msg

            # 1. Validación estructural y de definición
            is_valid, error_msg = self.validator.validate(definition)
            if not is_valid:
                self._record_invalid_status(skill_id, version)
                logger.warning(
                    f"[SKILL REGISTRATION REJECTED] Skill '{skill_id}@{version}' inválida: {error_msg}"
                )
                return False, error_msg

            # 2. Validación de manifest formal si existe
            if definition.manifest is not None:
                m_valid, m_error = self.validator.validate_manifest(
                    manifest=definition.manifest,
                    installed_skills=self.get_installed_versions(),
                )
                if not m_valid:
                    self._record_invalid_status(skill_id, version)
                    logger.warning(
                        f"[SKILL MANIFEST REJECTED] Manifest de '{skill_id}@{version}' rechazado: {m_error}"
                    )
                    return False, m_error

            # Registro exitoso
            if skill_id not in self._skills:
                self._skills[skill_id] = {}
                self._definitions[skill_id] = {}
                self._statuses[skill_id] = {}

            self._skills[skill_id][version] = skill
            self._definitions[skill_id][version] = definition
            self._statuses[skill_id][version] = SkillStatus.READY
            self._update_active_version(skill_id, version)

            logger.info(
                f"[SKILL REGISTERED] Skill '{skill_id}@{version}' registrada con éxito (Status: READY)."
            )
            return True, None

    def _record_invalid_status(self, skill_id: str, version: str) -> None:
        if skill_id not in self._statuses:
            self._statuses[skill_id] = {}
        self._statuses[skill_id][version] = SkillStatus.INVALID

    def _update_active_version(self, skill_id: str, new_version: str) -> None:
        """Determina la versión activa más reciente mediante comparación SemVer."""
        current_active = self._active_versions.get(skill_id)
        if not current_active:
            self._active_versions[skill_id] = new_version
            return

        # Comparar semvers simples
        try:
            curr_parts = [int(p) for p in re.split(r"[-.]", current_active)[:3] if p.isdigit()]
            new_parts = [int(p) for p in re.split(r"[-.]", new_version)[:3] if p.isdigit()]
            if new_parts >= curr_parts:
                self._active_versions[skill_id] = new_version
        except Exception:
            self._active_versions[skill_id] = new_version

    # ── 2. LOOKUP FORMAL (POR ID O ID@VERSION) ──

    def lookup(self, target: str) -> BaseSkill | None:
        """Busca una instancia de Skill por 'id' (versión activa) o 'id@version' exacta."""
        with self._lock:
            if "@" in target:
                skill_id, version = target.split("@", 1)
                return self._skills.get(skill_id, {}).get(version)

            active_ver = self._active_versions.get(target)
            if active_ver:
                return self._skills.get(target, {}).get(active_ver)
            return None

    def lookup_definition(self, target: str) -> SkillDefinition | None:
        """Busca la definición de una Skill por 'id' o 'id@version'."""
        with self._lock:
            if "@" in target:
                skill_id, version = target.split("@", 1)
                return self._definitions.get(skill_id, {}).get(version)

            active_ver = self._active_versions.get(target)
            if active_ver:
                return self._definitions.get(target, {}).get(active_ver)
            return None

    # ── 3. CICLO DE VIDA: ENABLE / DISABLE / UNREGISTER ──

    def enable_skill(self, target: str) -> bool:
        """Habilita una Skill ('id' o 'id@version')."""
        with self._lock:
            if "@" in target:
                skill_id, version = target.split("@", 1)
                if skill_id in self._statuses and version in self._statuses[skill_id]:
                    self._statuses[skill_id][version] = SkillStatus.ENABLED
                    logger.info(f"[SKILL ENABLED] Skill '{target}' habilitada.")
                    return True
                return False

            if target in self._statuses:
                for ver in self._statuses[target]:
                    self._statuses[target][ver] = SkillStatus.ENABLED
                logger.info(f"[SKILL ENABLED] Todas las versiones de '{target}' habilitadas.")
                return True
            return False

    def disable_skill(self, target: str) -> bool:
        """Deshabilita una Skill ('id' o 'id@version') impidiendo su selección."""
        with self._lock:
            if "@" in target:
                skill_id, version = target.split("@", 1)
                if skill_id in self._statuses and version in self._statuses[skill_id]:
                    self._statuses[skill_id][version] = SkillStatus.DISABLED
                    logger.info(f"[SKILL DISABLED] Skill '{target}' deshabilitada.")
                    return True
                return False

            if target in self._statuses:
                for ver in self._statuses[target]:
                    self._statuses[target][ver] = SkillStatus.DISABLED
                logger.info(f"[SKILL DISABLED] Todas las versiones de '{target}' deshabilitadas.")
                return True
            return False

    def unregister_skill(self, target: str) -> bool:
        """Desregistra una Skill completa ('id') o una versión específica ('id@version')."""
        with self._lock:
            if "@" in target:
                skill_id, version = target.split("@", 1)
                if skill_id in self._skills and version in self._skills[skill_id]:
                    del self._skills[skill_id][version]
                    del self._definitions[skill_id][version]
                    del self._statuses[skill_id][version]
                    if self._active_versions.get(skill_id) == version:
                        remaining = list(self._skills[skill_id].keys())
                        if remaining:
                            self._active_versions[skill_id] = remaining[-1]
                        else:
                            del self._active_versions[skill_id]
                            del self._skills[skill_id]
                            del self._definitions[skill_id]
                            del self._statuses[skill_id]
                    logger.info(f"[SKILL UNREGISTERED] Versión '{target}' eliminada del registro.")
                    return True
                return False

            if target in self._skills:
                del self._skills[target]
                del self._definitions[target]
                del self._statuses[target]
                if target in self._active_versions:
                    del self._active_versions[target]
                logger.info(f"[SKILL UNREGISTERED] Skill '{target}' y todas sus versiones eliminadas.")
                return True
            return False

    def get_status(self, target: str) -> SkillStatus:
        """Obtiene el estado de una Skill ('id' o 'id@version')."""
        with self._lock:
            if "@" in target:
                skill_id, version = target.split("@", 1)
                return self._statuses.get(skill_id, {}).get(version, SkillStatus.UNVALIDATED)

            active_ver = self._active_versions.get(target)
            if active_ver:
                return self._statuses.get(target, {}).get(active_ver, SkillStatus.UNVALIDATED)
            return SkillStatus.UNVALIDATED

    # ── 4. DISCOVERY MULTIDIMENSIONAL ──

    def discover(
        self,
        id: str | None = None,
        capability: str | None = None,
        category: str | None = None,
        tool: str | None = None,
        agent: str | None = None,
        risk_level: SecurityLevel | str | None = None,
        only_enabled: bool = True,
    ) -> list[SkillDefinition]:
        """Búsqueda y filtrado multidimensional de Skills en el catálogo."""
        with self._lock:
            results: list[SkillDefinition] = []

            for skill_id, ver_dict in self._definitions.items():
                for version, def_obj in ver_dict.items():
                    # 1. Filtro por estado habilitado
                    if only_enabled:
                        status = self._statuses.get(skill_id, {}).get(version)
                        if status not in (SkillStatus.ENABLED, SkillStatus.READY):
                            continue

                    # 2. Filtro por ID / nombre
                    if id is not None:
                        id_clean = id.strip().lower()
                        if id_clean not in def_obj.skill_id.lower() and id_clean not in def_obj.name.lower():
                            continue

                    # 3. Filtro por Capability
                    if capability is not None:
                        cap_clean = capability.strip().lower()
                        has_cap = any(
                            c.lower() == cap_clean or cap_clean in c.lower()
                            for c in def_obj.capabilities
                        )
                        if not has_cap:
                            continue

                    # 4. Filtro por Categoría (primer segmento del skill_id)
                    if category is not None:
                        cat_clean = category.strip().lower()
                        sk_cat = def_obj.skill_id.split(".")[0].lower() if "." in def_obj.skill_id else def_obj.skill_id.lower()
                        if cat_clean != sk_cat:
                            continue

                    # 5. Filtro por Tool requerida
                    if tool is not None:
                        tool_clean = tool.strip().lower()
                        has_tool = any(t.lower() == tool_clean for t in def_obj.required_tools)
                        if not has_tool and def_obj.manifest:
                            has_tool = any(t.lower() == tool_clean for t in def_obj.manifest.required_tools)
                        if not has_tool:
                            continue

                    # 6. Filtro por Agent requerido
                    if agent is not None:
                        agent_clean = agent.strip().lower()
                        has_agent = False
                        if def_obj.manifest:
                            has_agent = any(a.lower() == agent_clean for a in def_obj.manifest.required_agents)
                        if not has_agent:
                            continue

                    # 7. Filtro por Nivel de Riesgo
                    if risk_level is not None:
                        req_risk_str = str(getattr(risk_level, "value", risk_level)).upper()
                        def_risk_str = str(getattr(def_obj.risk_level, "value", def_obj.risk_level)).upper()
                        if req_risk_str != def_risk_str:
                            continue

                    results.append(def_obj)

            return results

    # ── 5. MÉTODOS DE COMPATIBILIDAD ──

    def get_skill(self, skill_id: str) -> BaseSkill | None:
        """Alias retrocompatible de lookup."""
        return self.lookup(skill_id)

    def get_definition(self, skill_id: str) -> SkillDefinition | None:
        """Alias retrocompatible de lookup_definition."""
        return self.lookup_definition(skill_id)

    def list_skills(self) -> list[SkillDefinition]:
        """Lista las definiciones de la versión activa de cada skill."""
        with self._lock:
            res: list[SkillDefinition] = []
            for skill_id, active_ver in self._active_versions.items():
                def_obj = self._definitions.get(skill_id, {}).get(active_ver)
                if def_obj:
                    res.append(def_obj)
            return res

    def list_all_versions(self) -> list[SkillDefinition]:
        """Lista todas las definiciones de todas las versiones registradas."""
        with self._lock:
            res: list[SkillDefinition] = []
            for ver_dict in self._definitions.values():
                res.extend(ver_dict.values())
            return res

    def find_by_capability(self, capability: str) -> list[SkillDefinition]:
        """Busca skills por capacidad (compatibilidad previa)."""
        return self.discover(capability=capability, only_enabled=False)

    def find_by_tag(self, tag: str) -> list[SkillDefinition]:
        """Busca skills por tag."""
        tag_clean = tag.strip().lower()
        with self._lock:
            return [
                d for d in self.list_skills()
                if any(t.lower() == tag_clean for t in d.tags)
            ]

    def get_installed_versions(self) -> dict[str, str]:
        """Retorna un mapeo de skill_id -> versión activa instalada."""
        with self._lock:
            return dict(self._active_versions)

    def reset(self) -> None:
        """Limpia el catálogo para aislamiento de pruebas."""
        with self._lock:
            self._skills.clear()
            self._definitions.clear()
            self._statuses.clear()
            self._active_versions.clear()


def get_skill_registry() -> SkillRegistry:
    """Acceso helper al singleton global de SkillRegistry."""
    return SkillRegistry.get_instance()
