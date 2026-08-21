"""Enrutador dinámico de modelos LLM (ModelRouter - Fase 2: Dynamic Model Router).

Selecciona deterministamente el perfil de modelo óptimo para una tarea dada según
sus capacidades, complejidad, latencia, VRAM y estado de disponibilidad.

GARANTÍA DE SEGURIDAD (INVARIANTE ARQUITECTÓNICA):
El ModelRouter:
  - NO ejecuta herramientas
  - NO concede permisos
  - NO modifica SecurityPolicy
  - NO ejecuta acciones del sistema operativo
Su responsabilidad se limita exclusivamente a resolver y retornar un ModelProfile válido.
"""

from __future__ import annotations

import threading
from typing import ClassVar

from core.llm.model_profile import ModelProfile
from core.llm.model_registry import ModelRegistry
from core.llm.routing_policy import RoutingContext, RoutingPolicy, TaskComplexity, TaskType
from core.logger import get_logger

logger = get_logger("jessyca.llm.router")


class ModelRouter:
    """Enrutador de selección dinámica y resolución de modelos LLM con soporte de fallback."""

    _instance: ClassVar[ModelRouter | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        policy: RoutingPolicy | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._registry = registry or ModelRegistry.get_instance()
        self._policy = policy or RoutingPolicy(registry=self._registry)

    @classmethod
    def get_instance(cls) -> ModelRouter:
        """Obtiene la instancia singleton global del enrutador."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = ModelRouter()
            return cls._instance

    def route(self, context: RoutingContext) -> ModelProfile:
        """Determina y retorna el perfil de modelo óptimo según el contexto proporcionado."""
        with self._lock:
            selected_profile = self._policy.evaluate(context)
            logger.debug(
                f"[MODEL ROUTER] Tarea '{context.task_type.value}' (complejidad: {context.complexity.value}) "
                f"enrutada al modelo: '{selected_profile.name}' (provider: {selected_profile.provider})"
            )
            return selected_profile

    def select_model_for_task(
        self,
        task_type: TaskType | str,
        complexity: TaskComplexity | str = TaskComplexity.MEDIUM,
        requires_vision: bool = False,
        requires_tools: bool = False,
        max_vram_mb: int | None = None,
        preferred_model_id: str | None = None,
    ) -> ModelProfile:
        """Método de conveniencia para enrutar directamente a partir de parámetros atómicos."""
        # Normalizar task_type
        if isinstance(task_type, str):
            try:
                resolved_task = TaskType(task_type.lower().strip())
            except ValueError:
                resolved_task = TaskType.ANALYSIS_VERIFICATION
        else:
            resolved_task = task_type

        # Normalizar complexity
        if isinstance(complexity, str):
            try:
                resolved_complexity = TaskComplexity(complexity.lower().strip())
            except ValueError:
                resolved_complexity = TaskComplexity.MEDIUM
        else:
            resolved_complexity = complexity

        context = RoutingContext(
            task_type=resolved_task,
            complexity=resolved_complexity,
            requires_vision=requires_vision,
            requires_tools=requires_tools,
            max_available_vram_mb=max_vram_mb,
            preferred_model_id=preferred_model_id,
        )
        return self.route(context)

    def get_fallback_model(
        self,
        attempted_model: str,
        context: RoutingContext | None = None,
    ) -> ModelProfile:
        """Resuelve un modelo de respaldo alternativo cuando el modelo intentado falla o no está disponible."""
        with self._lock:
            base_context = context or RoutingContext()
            # Agregar el modelo fallido a la lista de excluidos
            updated_excluded = tuple(set(base_context.excluded_model_ids) | {attempted_model.strip()})
            fallback_context = RoutingContext(
                task_type=base_context.task_type,
                complexity=base_context.complexity,
                requires_vision=base_context.requires_vision,
                requires_tools=base_context.requires_tools,
                max_latency_tolerance_ms=base_context.max_latency_tolerance_ms,
                max_available_vram_mb=base_context.max_available_vram_mb,
                preferred_model_id=None,  # No insistir en el preferido fallido
                excluded_model_ids=updated_excluded,
                metadata=base_context.metadata,
            )
            fallback_profile = self._policy.evaluate(fallback_context)
            logger.info(
                f"[MODEL ROUTER] Fallback activado para '{attempted_model}' -> Asignado '{fallback_profile.name}'"
            )
            return fallback_profile


def get_model_router() -> ModelRouter:
    """Función de acceso directo a la instancia global de ModelRouter."""
    return ModelRouter.get_instance()
