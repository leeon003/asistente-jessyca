"""Enrutador de intenciones a Skills (skill_router.py - Fase 28.0).

Determina deterministamente la Skill óptima para satisfacer una intención del usuario
según afinidad de palabras clave, capacidades declaradas y etiquetas.

INVARIANTE DE SEGURIDAD ABSOLUTA:
SKILL ROUTER != AUTHORIZATION (El enrutador solo resuelve la Skill candidata; no autoriza la ejecución).
"""

from __future__ import annotations

import threading
from typing import ClassVar

from core.logger import get_logger
from skills.skill_models import (
    SkillDefinition,
    SkillStatus,
)
from skills.skill_registry import SkillRegistry, get_skill_registry

logger = get_logger("jessyca.skills.router")


class SkillRouter:
    """Enrutador determinista de intenciones hacia Skills registradas."""

    _instance: ClassVar[SkillRouter | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self._lock = threading.RLock()
        self.registry = registry or get_skill_registry()

    @classmethod
    def get_instance(cls) -> SkillRouter:
        """Obtiene la instancia singleton global del enrutador de skills."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = SkillRouter()
            return cls._instance

    def route_intent(self, intent: str) -> tuple[SkillDefinition | None, float, str]:
        """Resuelve la Skill adecuada para la intención del usuario.

        :param intent: Texto de la orden o intención del usuario.
        :return: Tupla (SkillDefinition | None, confianza [0.0 - 1.0], razon explicativa).
        """
        intent_clean = intent.strip().lower()
        if not intent_clean:
            return None, 0.0, "Intención vacía."

        with self._lock:
            all_skills = self.registry.list_skills()
            skills = [
                s for s in all_skills
                if self.registry.get_status(s.skill_id) not in (SkillStatus.DISABLED, SkillStatus.INVALID, SkillStatus.FAILED)
            ]
            if not skills:
                return None, 0.0, "No hay skills habilitadas registradas en el catálogo."

            # 1. Coincidencia exacta por skill_id o name
            for sk in skills:
                if intent_clean == sk.skill_id.lower() or intent_clean == sk.name.lower():
                    return sk, 1.0, f"Coincidencia exacta con skill '{sk.skill_id}'."

            # 2. Puntuación por palabras clave en nombre, descripción y etiquetas
            best_skill: SkillDefinition | None = None
            best_score = 0.0
            intent_tokens = set(intent_clean.replace(".", " ").replace("_", " ").replace("-", " ").split())

            for sk in skills:
                sk_tokens = set(
                    f"{sk.skill_id} {sk.name} {sk.description} {' '.join(sk.tags)} {' '.join(sk.capabilities)}"
                    .lower()
                    .replace(".", " ")
                    .replace("_", " ")
                    .replace("-", " ")
                    .split()
                )

                common = intent_tokens.intersection(sk_tokens)
                if common:
                    score = len(common) / max(len(intent_tokens), 1)
                    if score > best_score:
                        best_score = score
                        best_skill = sk

            if best_skill and best_score >= 0.20:
                confidence = min(0.95, max(0.50, best_score))
                return best_skill, confidence, f"Afinidad semántica con '{best_skill.skill_id}' (score: {best_score:.2f})."

            return None, 0.0, "Ninguna skill coincidió con la intención proporcionada."


def get_skill_router() -> SkillRouter:
    """Acceso helper al singleton global de SkillRouter."""
    return SkillRouter.get_instance()
