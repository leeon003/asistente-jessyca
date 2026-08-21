"""Gestor central del Skill Framework Foundation (skill_manager.py - Fase 28.0).

Orquesta el ciclo completo de descubrimiento, validación, enrutamiento y ejecución segura de Skills.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. NINGUNA SKILL TIENE BYPASS DE SEGURIDAD.
2. TODAS LAS ACCIONES PASAN POR EL RUNTIME CON SECURITYPIPELINE.
3. PREVALENCIA DE PARADA DE EMERGENCIA.
"""

from __future__ import annotations

import threading
from typing import Any, ClassVar

from core.cancellation import CancellationToken
from core.logger import get_logger
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillContext,
    SkillDefinition,
    SkillResult,
    SkillStatus,
)
from skills.skill_registry import SkillRegistry, get_skill_registry
from skills.skill_router import SkillRouter, get_skill_router
from skills.skill_runtime import SkillRuntime

logger = get_logger("jessyca.skills.manager")


class SkillManager:
    """Coordinador central del Skill Framework de JESSYCA."""

    _instance: ClassVar[SkillManager | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        router: SkillRouter | None = None,
        runtime: SkillRuntime | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.registry = registry or get_skill_registry()
        self.router = router or get_skill_router()
        self.runtime = runtime or SkillRuntime()

    @classmethod
    def get_instance(cls) -> SkillManager:
        """Obtiene la instancia singleton global del gestor de skills."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = SkillManager()
            return cls._instance

    def register_skill(self, skill: BaseSkill) -> tuple[bool, str | None]:
        """Registra una Skill en el ecosistema."""
        with self._lock:
            return self.registry.register_skill(skill)

    def unregister_skill(self, skill_id: str) -> bool:
        """Elimina una Skill del ecosistema."""
        with self._lock:
            return self.registry.unregister_skill(skill_id)

    def execute_skill(
        self,
        skill_id: str,
        parameters: dict[str, Any] | None = None,
        session_id: str = "default_session",
        user: str = "user",
        cancellation_token: CancellationToken | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SkillResult:
        """Ejecuta una Skill directamente por su identificador."""
        with self._lock:
            skill = self.registry.get_skill(skill_id)
            if not skill:
                logger.warning(f"[SKILL NOT FOUND] Skill '{skill_id}' no encontrada en el registro.")
                return SkillResult(
                    skill_id=skill_id,
                    success=False,
                    status=SkillStatus.FAILED,
                    error=f"La Skill '{skill_id}' no está registrada en el sistema.",
                    security_decision="NOT_FOUND",
                )

            context = SkillContext(
                skill_id=skill_id,
                intent=f"execute_{skill_id}",
                parameters=parameters or {},
                session_id=session_id,
                user=user,
                cancellation_token=cancellation_token,
                metadata=metadata or {},
            )
            return self.runtime.execute_skill(skill=skill, context=context)

    def execute_by_intent(
        self,
        intent: str,
        parameters: dict[str, Any] | None = None,
        session_id: str = "default_session",
        user: str = "user",
        cancellation_token: CancellationToken | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SkillResult:
        """Descubre, enruta y ejecuta la Skill óptima para una intención del usuario."""
        with self._lock:
            skill_def, confidence, reason = self.router.route_intent(intent)
            if not skill_def:
                logger.info(f"[SKILL ROUTE FAILED] No se encontró skill para la intención '{intent}': {reason}")
                return SkillResult(
                    skill_id="",
                    success=False,
                    status=SkillStatus.FAILED,
                    error=f"No se encontró una Skill adecuada para: '{intent}'. Motivo: {reason}",
                    security_decision="NO_SKILL_MATCH",
                )

            logger.info(
                f"[SKILL SELECTED] Intención '{intent}' -> Skill '{skill_def.skill_id}' (confianza: {confidence:.2f})"
            )
            skill = self.registry.get_skill(skill_def.skill_id)
            if not skill:
                return SkillResult(
                    skill_id=skill_def.skill_id,
                    success=False,
                    status=SkillStatus.FAILED,
                    error=f"La definición de la Skill '{skill_def.skill_id}' existe pero su instancia no está cargada.",
                    security_decision="NOT_LOADED",
                )

            context = SkillContext(
                skill_id=skill_def.skill_id,
                intent=intent,
                parameters=parameters or {},
                session_id=session_id,
                user=user,
                cancellation_token=cancellation_token,
                metadata=metadata or {},
            )
            return self.runtime.execute_skill(skill=skill, context=context)

    def list_skills(self) -> list[SkillDefinition]:
        """Retorna la lista de todas las definiciones de skills registradas."""
        return self.registry.list_skills()

    def reset(self) -> None:
        """Limpia el gestor para aislamiento de pruebas."""
        with self._lock:
            self.registry.reset()


def get_skill_manager() -> SkillManager:
    """Acceso helper al singleton global de SkillManager."""
    return SkillManager.get_instance()
