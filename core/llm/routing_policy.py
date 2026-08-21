"""Políticas y criterios de enrutamiento dinámico para selección de modelos LLM (routing_policy.py - Fase 2).

Define los tipos de tareas, niveles de complejidad, contextos de enrutamiento y las reglas
deterministas de asignación de modelos con soporte para fallback seguro.

GARANTÍA DE SEGURIDAD:
Este módulo contiene ÚNICAMENTE lógica pura de selección y clasificación.
NO ejecuta herramientas, NO modifica permisos de seguridad, NO ejecuta acciones de sistema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.llm.model_profile import ModelProfile
from core.llm.model_registry import ModelRegistry


class TaskType(StrEnum):
    """Categorías funcionales de tareas para enrutamiento de modelos."""

    CLASSIFICATION = "classification"        # Clasificación rápida, detección de patrones
    SIMPLE_TASK = "simple_task"              # Órdenes directas de baja complejidad
    CONVERSATION = "conversation"            # Diálogo fluido, preguntas y respuestas generales
    REASONING = "reasoning"                  # Razonamiento deductivo / inductivo profundo
    PLANNING = "planning"                    # Descomposición de planes y secuencias de pasos
    ANALYSIS_VERIFICATION = "analysis"       # Análisis estructurado y verificación de intenciones
    VISION = "vision"                        # Procesamiento multimodal / análisis de imágenes


class TaskComplexity(StrEnum):
    """Niveles de complejidad computacional de una tarea."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class RoutingContext:
    """Contexto y restricciones declarativas para la selección de modelo."""

    task_type: TaskType = TaskType.ANALYSIS_VERIFICATION
    complexity: TaskComplexity = TaskComplexity.MEDIUM
    requires_vision: bool = False
    requires_tools: bool = False
    max_latency_tolerance_ms: float | None = None
    max_available_vram_mb: int | None = None
    preferred_model_id: str | None = None
    excluded_model_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class RoutingPolicy:
    """Reglas deterministas de evaluación y selección de perfiles de modelos según el contexto de la tarea."""

    # Prioridad por defecto de modelos según el tipo de tarea
    DEFAULT_TASK_AFFINITY: dict[TaskType, tuple[str, ...]] = {
        TaskType.CLASSIFICATION: ("llama3.2", "gemma4:e4b", "llama3.1"),
        TaskType.SIMPLE_TASK: ("llama3.2", "gemma4:e4b", "llama3.1"),
        TaskType.CONVERSATION: ("llama3.1", "llama3.2", "gemma4:e4b"),
        TaskType.REASONING: ("qwen3:8b", "gemma4:e4b", "llama3.1"),
        TaskType.PLANNING: ("qwen3:8b", "gemma4:e4b", "llama3.1"),
        TaskType.ANALYSIS_VERIFICATION: ("gemma4:e4b", "qwen3:8b", "llama3.1", "llama3.2"),
        TaskType.VISION: ("qwen3-vl:4b",),
    }

    # Modelo de respaldo seguro final del sistema
    SAFE_FALLBACK_MODEL = "gemma4:e4b"

    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self._registry = registry or ModelRegistry.get_instance()

    def evaluate(self, context: RoutingContext) -> ModelProfile:
        """Evalúa el contexto de la tarea y selecciona el perfil de modelo óptimo disponible.

        Aplica filtros de requerimientos estrictos (visión, estado habilitado, VRAM) y
        resuelve la mejor coincidencia según la afinidad declarada.
        """
        # 1. Si se requiere visión explícitamente, filtrar únicamente modelos multimodales
        if context.requires_vision or context.task_type == TaskType.VISION:
            candidate = self._find_vision_candidate(context)
            if candidate is not None:
                return candidate

        # 2. Si el usuario/llamador tiene un modelo preferido válido y disponible
        if context.preferred_model_id and context.preferred_model_id not in context.excluded_model_ids:
            try:
                preferred = self._registry.get(context.preferred_model_id)
                if self._is_model_eligible(preferred, context):
                    return preferred
            except Exception:
                pass

        # 3. Complejidad alta escala automáticamente a modelos con reasoning (qwen3:8b)
        effective_task = context.task_type
        if context.complexity == TaskComplexity.HIGH and effective_task not in (TaskType.VISION, TaskType.REASONING, TaskType.PLANNING):
            effective_task = TaskType.REASONING

        # 4. Iterar sobre la lista de afinidad de la tarea
        candidate_names = self.DEFAULT_TASK_AFFINITY.get(
            effective_task,
            (self.SAFE_FALLBACK_MODEL, "llama3.1", "llama3.2", "qwen3:8b")
        )

        for name in candidate_names:
            if name in context.excluded_model_ids:
                continue
            try:
                profile = self._registry.get(name)
                if self._is_model_eligible(profile, context):
                    return profile
            except Exception:
                continue

        # 5. Fallback general: buscar cualquier modelo habilitado en el registro que cumpla restricciones
        for profile in self._registry.list_models():
            if profile.name not in context.excluded_model_ids and self._is_model_eligible(profile, context):
                return profile

        # 6. Fallback final seguro e incondicional
        return self._registry.get(self.SAFE_FALLBACK_MODEL)

    def _find_vision_candidate(self, context: RoutingContext) -> ModelProfile | None:
        """Busca el primer modelo disponible con capacidad multimodal de visión."""
        for profile in self._registry.list_models():
            if profile.name in context.excluded_model_ids:
                continue
            if (profile.vision or profile.supports_vision) and self._is_model_eligible(profile, context, ignore_vision_check=True):
                return profile
        return None

    def _is_model_eligible(
        self,
        profile: ModelProfile,
        context: RoutingContext,
        ignore_vision_check: bool = False,
    ) -> bool:
        """Determina si un modelo cumple con los criterios de elegibilidad técnica del contexto."""
        if not profile.enabled:
            return False

        # Comprobar requerimiento de visión
        if not ignore_vision_check and context.requires_vision:
            if not (profile.vision or profile.supports_vision):
                return False

        # Comprobar restricción de VRAM si se especificó
        if context.max_available_vram_mb is not None and profile.vram_estimate_mb is not None:
            if profile.vram_estimate_mb > context.max_available_vram_mb:
                return False

        return True
