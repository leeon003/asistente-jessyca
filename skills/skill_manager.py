"""Gestor central del Skill Framework y ciclo de vida runtime (skill_manager.py - Fase 28.4).

Orquesta el ciclo completo de carga, activación, desactivación, descarga, verificación de dependencias
y ejecución gobernada de Skills.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. NINGUNA SKILL TIENE BYPASS DE SEGURIDAD.
2. TODAS LAS ACCIONES PASAN POR EL RUNTIME CON SECURITYPIPELINE Y SANDBOX.
3. PREVALENCIA DE PARADA DE EMERGENCIA Y RESPETO DE LÍMITES DE PRESUPUESTO.
"""

from __future__ import annotations

import threading
from typing import Any, ClassVar

from core.cancellation import CancellationToken
from core.control_plane.models import AgentBudget
from core.logger import get_logger
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillContext,
    SkillDefinition,
    SkillManifest,
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

    # ── 1. GESTIÓN DEL CICLO DE VIDA (LOAD, UNLOAD, ACTIVATE, DEACTIVATE) ──

    def load_skill(self, skill: BaseSkill, replace: bool = False) -> tuple[bool, str | None]:
        """Carga y valida una Skill en el catálogo."""
        with self._lock:
            return self.registry.register_skill(skill, replace=replace)

    def register_skill(self, skill: BaseSkill, replace: bool = False) -> tuple[bool, str | None]:
        """Alias retrocompatible de load_skill."""
        return self.load_skill(skill, replace=replace)

    def unload_skill(self, target: str) -> bool:
        """Descarga una Skill ('id' o 'id@version') del sistema."""
        with self._lock:
            return self.registry.unregister_skill(target)

    def unregister_skill(self, target: str) -> bool:
        """Alias retrocompatible de unload_skill."""
        return self.unload_skill(target)

    def list_skills(self) -> list[SkillDefinition]:
        """Lista las definiciones de las skills registradas."""
        with self._lock:
            return self.registry.list_skills()

    def activate_skill(self, target: str) -> bool:
        """Activa y habilita una Skill para su ejecución."""
        with self._lock:
            return self.registry.enable_skill(target)

    def deactivate_skill(self, target: str) -> bool:
        """Desactiva e inhabilita una Skill."""
        with self._lock:
            return self.registry.disable_skill(target)

    def get_skill_status(self, target: str) -> SkillStatus:
        """Consulta el estado actual de una Skill en el registro."""
        with self._lock:
            return self.registry.get_status(target)

    def get_active_version(self, skill_id: str) -> str | None:
        """Obtiene la versión activa instalada de una Skill."""
        with self._lock:
            return self.registry.get_installed_versions().get(skill_id)

    def get_known_good_versions(self, skill_id: str) -> list[str]:
        """Obtiene las versiones funcionales conocidas de una Skill."""
        with self._lock:
            return self.registry.get_known_good_versions(skill_id)

    def set_active_version(self, skill_id: str, version: str) -> bool:
        """Cambia atómicamente la versión activa de una Skill."""
        with self._lock:
            return self.registry.set_active_version(skill_id, version)

    def rollback_skill(
        self,
        skill_id: str,
        target_version: str | None = None,
        reason: str = "Rollback solicitado via SkillManager",
    ) -> bool:
        """Revierte una Skill a su versión previa funcional."""
        with self._lock:
            from skills.skill_updater import SkillUpdater
            updater = SkillUpdater(registry=self.registry)
            res = updater.rollback_skill(skill_id=skill_id, target_version=target_version, reason=reason)
            return res.success

    def verify_dependencies(self, manifest_or_def: SkillManifest | SkillDefinition) -> tuple[bool, str | None]:
        """Verifica si las dependencias de una Skill están satisfechas en el sistema."""
        with self._lock:
            installed = self.registry.get_installed_versions()
            deps = getattr(manifest_or_def, "dependencies", {})
            for dep_id, min_ver in deps.items():
                if dep_id not in installed:
                    return False, f"Dependencia faltante: '{dep_id}' (requerida >= {min_ver}) no está disponible."
            return True, None

    # ── 2. EJECUCIÓN GOBERNADA ──

    def execute_skill(
        self,
        skill_id: str,
        parameters: dict[str, Any] | None = None,
        session_id: str = "default_session",
        user: str = "user",
        cancellation_token: CancellationToken | None = None,
        metadata: dict[str, Any] | None = None,
        timeout_seconds: float = 60.0,
        budget: AgentBudget | None = None,
    ) -> SkillResult:
        """Ejecuta una Skill directamente por su identificador o versión."""
        with self._lock:
            skill = self.registry.lookup(skill_id)
            if not skill:
                logger.warning(f"[SKILL NOT FOUND] Skill '{skill_id}' no encontrada en el registro.")
                return SkillResult(
                    skill_id=skill_id,
                    success=False,
                    status=SkillStatus.FAILED,
                    error=f"La Skill '{skill_id}' no está registrada o disponible en el sistema.",
                    security_decision="NOT_FOUND",
                )

            # Verificar si la Skill está deshabilitada
            status = self.registry.get_status(skill_id)
            if status in (SkillStatus.DISABLED, SkillStatus.INVALID, SkillStatus.FAILED):
                logger.warning(f"[SKILL NOT ACTIVE] Skill '{skill_id}' no está activa (Status: {status}).")
                return SkillResult(
                    skill_id=skill_id,
                    success=False,
                    status=SkillStatus.FAILED,
                    error=f"La Skill '{skill_id}' no puede ejecutarse porque su estado es '{status}'.",
                    security_decision="SKILL_DISABLED",
                )

            context = SkillContext(
                skill_id=skill.skill_id,
                intent=f"execute_{skill.skill_id}",
                parameters=parameters or {},
                timeout_seconds=timeout_seconds,
                cancellation_token=cancellation_token,
                session_id=session_id,
                user=user,
                metadata=metadata or {},
            )
        return self.runtime.execute_skill(skill=skill, context=context, budget=budget)

    def execute_by_intent(
        self,
        intent: str,
        parameters: dict[str, Any] | None = None,
        session_id: str = "default_session",
        user: str = "user",
        cancellation_token: CancellationToken | None = None,
        metadata: dict[str, Any] | None = None,
        timeout_seconds: float = 60.0,
        budget: AgentBudget | None = None,
    ) -> SkillResult:
        """Enruta la intención del usuario hacia la Skill más idónea y la ejecuta."""
        with self._lock:
            skill_def, confidence, reason = self.router.route_intent(intent)
            if not skill_def or confidence < 0.2:
                logger.info(f"[SKILL ROUTE MISS] No se encontró skill idónea para '{intent}': {reason}")
                return SkillResult(
                    skill_id="none",
                    success=False,
                    status=SkillStatus.FAILED,
                    error=f"No se encontró una Skill adecuada para satisfacer la intención '{intent}'.",
                    security_decision="NO_SKILL_MATCHED",
                    metadata={"route_reason": reason, "confidence": confidence},
                )

            logger.info(
                f"[SKILL ROUTED] Intención '{intent}' -> Skill '{skill_def.skill_id}' (Confianza: {confidence:.2f})"
            )
            target_skill_id = skill_def.skill_id
        return self.execute_skill(
            skill_id=target_skill_id,
            parameters=parameters,
            session_id=session_id,
            user=user,
            cancellation_token=cancellation_token,
            metadata=metadata,
            timeout_seconds=timeout_seconds,
            budget=budget,
        )


def get_skill_manager() -> SkillManager:
    """Acceso helper al singleton global de SkillManager."""
    return SkillManager.get_instance()
