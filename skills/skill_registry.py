"""Registro central thread-safe de habilidades (skill_registry.py - Fase 28.0).

Administra el catálogo de Skills disponibles, su indexación por capacidades y su validación.

INVARIANTE:
Solo skills debidamente validadas pueden ser registradas en el catálogo del sistema.
"""

from __future__ import annotations

import threading
from typing import ClassVar

from core.logger import get_logger
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillDefinition,
    SkillStatus,
)
from skills.skill_validator import SkillValidator

logger = get_logger("jessyca.skills.registry")


class SkillRegistry:
    """Catálogo central y registro de habilidades (Skills) de JESSYCA."""

    _instance: ClassVar[SkillRegistry | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, validator: SkillValidator | None = None) -> None:
        self._lock = threading.RLock()
        self.validator = validator or SkillValidator()
        self._skills: dict[str, BaseSkill] = {}
        self._definitions: dict[str, SkillDefinition] = {}
        self._statuses: dict[str, SkillStatus] = {}

    @classmethod
    def get_instance(cls) -> SkillRegistry:
        """Obtiene la instancia singleton global del registro de skills."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = SkillRegistry()
            return cls._instance

    def register_skill(self, skill: BaseSkill) -> tuple[bool, str | None]:
        """Valida y registra una instancia de Skill en el catálogo."""
        with self._lock:
            definition = skill.definition
            is_valid, error_msg = self.validator.validate(definition)
            if not is_valid:
                self._statuses[definition.skill_id] = SkillStatus.FAILED
                logger.warning(
                    f"[SKILL REGISTRATION REJECTED] Skill '{definition.skill_id}' rechazada: {error_msg}"
                )
                return False, error_msg

            # Si incluye manifest formal, validarlo
            if definition.manifest is not None:
                m_valid, m_error = self.validator.validate_manifest(
                    manifest=definition.manifest,
                    installed_skills=self.get_installed_versions(),
                )
                if not m_valid:
                    self._statuses[definition.skill_id] = SkillStatus.FAILED
                    logger.warning(
                        f"[SKILL MANIFEST REJECTED] Manifest de skill '{definition.skill_id}' rechazado: {m_error}"
                    )
                    return False, m_error

            self._skills[definition.skill_id] = skill
            self._definitions[definition.skill_id] = definition
            self._statuses[definition.skill_id] = SkillStatus.READY
            logger.info(f"[SKILL REGISTERED] Skill '{definition.skill_id}' v{definition.version} registrada con éxito (Status: READY).")
            return True, None

    def unregister_skill(self, skill_id: str) -> bool:
        """Desregistra una Skill del catálogo."""
        with self._lock:
            if skill_id in self._skills:
                del self._skills[skill_id]
                del self._definitions[skill_id]
                self._statuses[skill_id] = SkillStatus.UNLOADED
                logger.info(f"[SKILL UNREGISTERED] Skill '{skill_id}' desregistrada.")
                return True
            return False

    def get_status(self, skill_id: str) -> SkillStatus:
        """Obtiene el estado de ciclo de vida de la Skill."""
        with self._lock:
            return self._statuses.get(skill_id, SkillStatus.UNVALIDATED)

    def get_installed_versions(self) -> dict[str, str]:
        """Retorna un mapeo de skill_id -> version para chequeo de dependencias."""
        with self._lock:
            return {d.skill_id: d.version for d in self._definitions.values()}

    def get_skill(self, skill_id: str) -> BaseSkill | None:
        """Obtiene la instancia ejecutora de una Skill por su ID."""
        with self._lock:
            return self._skills.get(skill_id)

    def get_definition(self, skill_id: str) -> SkillDefinition | None:
        """Obtiene los metadatos declarativos de una Skill por su ID."""
        with self._lock:
            return self._definitions.get(skill_id)

    def list_skills(self) -> list[SkillDefinition]:
        """Lista todas las definiciones de skills registradas."""
        with self._lock:
            return list(self._definitions.values())

    def find_by_capability(self, capability: str) -> list[SkillDefinition]:
        """Busca skills que declaren una capacidad específica."""
        cap_clean = capability.strip().lower()
        with self._lock:
            return [
                d for d in self._definitions.values()
                if any(c.lower() == cap_clean for c in d.capabilities)
            ]

    def find_by_tag(self, tag: str) -> list[SkillDefinition]:
        """Busca skills que contengan una etiqueta específica."""
        tag_clean = tag.strip().lower()
        with self._lock:
            return [
                d for d in self._definitions.values()
                if any(t.lower() == tag_clean for t in d.tags)
            ]

    def reset(self) -> None:
        """Limpia el catálogo para aislamiento de pruebas."""
        with self._lock:
            self._skills.clear()
            self._definitions.clear()


def get_skill_registry() -> SkillRegistry:
    """Acceso helper al singleton global de SkillRegistry."""
    return SkillRegistry.get_instance()
