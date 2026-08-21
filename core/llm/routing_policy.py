"""Políticas y criterios de enrutamiento dinámico para selección de modelos LLM (routing_policy.py - Fase 25: Smart Model Routing 2.0).

Define los tipos de tareas, niveles de complejidad, contextos de enrutamiento y las reglas
deterministas de asignación de modelos con soporte para fallback seguro y scoring multi-factor.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. MODEL ROUTER != AUTHORIZATION
2. Capacidades declaradas son estrictas y no negociables (Vision requiere modelo con visión).
3. Fallback determinista y anti-thrashing de VRAM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.llm.model_profile import ModelProfile
from core.llm.model_registry import ModelRegistry
from core.llm.smart_routing_models import (
    ModelPerformanceTracker,
    ModelRoutingDecision,
    TaskComplexity,
    TaskType,
)

__all__ = [
    "RoutingContext",
    "RoutingPolicy",
    "TaskComplexity",
    "TaskType",
]


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

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        tracker: ModelPerformanceTracker | None = None,
    ) -> None:
        self._registry = registry or ModelRegistry.get_instance()
        self._tracker = tracker or ModelPerformanceTracker()

    def evaluate(self, context: RoutingContext) -> ModelProfile:
        """Evalúa el contexto y retorna directamente el ModelProfile seleccionado (retrocompatibilidad)."""
        decision = self.evaluate_smart(context)
        return decision.selected_model

    def evaluate_smart(self, context: RoutingContext) -> ModelRoutingDecision:
        """Evalúa el contexto mediante scoring multi-factor (TaskType, Complejidad, Capacidades, VRAM, Historial)."""
        # 1. Filtro estricto de visión
        if context.requires_vision or context.task_type == TaskType.VISION:
            vision_candidate = self._find_vision_candidate(context)
            if vision_candidate is not None:
                return ModelRoutingDecision(
                    selected_model=vision_candidate,
                    task_type=context.task_type,
                    complexity=context.complexity,
                    confidence=0.98,
                    reason=f"Requisito estricto de visión asignado a '{vision_candidate.name}'.",
                    candidate_scores={vision_candidate.name: 1.0},
                    fallback_chain=(),
                    vram_allocated_mb=vision_candidate.vram_estimate_mb or 3600,
                )

        # 2. Escalar tarea efectiva si la complejidad es alta
        effective_task = context.task_type
        if context.complexity == TaskComplexity.HIGH and effective_task not in (
            TaskType.VISION,
            TaskType.REASONING,
            TaskType.PLANNING,
        ):
            effective_task = TaskType.REASONING

        # 3. Filtrar modelos elegibles que cumplan requerimientos técnicos duros
        all_models = self._registry.list_models()
        eligible_models = [
            p for p in all_models
            if p.name not in context.excluded_model_ids and self._is_model_eligible(p, context)
        ]

        if not eligible_models:
            # Fallback seguro si ningún modelo cumple los filtros
            fallback_prof = self._registry.get(self.SAFE_FALLBACK_MODEL)
            return ModelRoutingDecision(
                selected_model=fallback_prof,
                task_type=context.task_type,
                complexity=context.complexity,
                confidence=0.50,
                reason="Ningún modelo cumplió los filtros técnicos. Fallback seguro asignado.",
                candidate_scores={self.SAFE_FALLBACK_MODEL: 0.5},
                fallback_chain=(),
                vram_allocated_mb=fallback_prof.vram_estimate_mb or 4000,
            )

        # 4. Calcular puntuación multi-factor por modelo elegible
        scored_models: list[tuple[ModelProfile, float, str]] = []
        scores_map: dict[str, float] = {}

        affinity_list = self.DEFAULT_TASK_AFFINITY.get(effective_task, (self.SAFE_FALLBACK_MODEL,))

        for profile in eligible_models:
            # A) Afinidad de tarea (0.40)
            if profile.name in affinity_list:
                pos = affinity_list.index(profile.name)
                s_affinity = max(0.20, 1.0 - (0.25 * pos))
            else:
                s_affinity = 0.10

            # B) Complejidad (0.20)
            if context.complexity == TaskComplexity.HIGH:
                s_comp = 1.0 if (profile.reasoning or "thinking" in profile.capabilities) else 0.40
            elif context.complexity == TaskComplexity.LOW:
                s_comp = 1.0 if (profile.vram_estimate_mb and profile.vram_estimate_mb <= 3500) else 0.70
            else:
                s_comp = 0.85

            # C) Rendimiento histórico (0.20)
            s_perf = self._tracker.get_success_rate(profile.name, context.task_type)

            # D) Eficiencia VRAM y Latencia (0.20)
            vram_est = profile.vram_estimate_mb or 4000
            s_vram = max(0.20, 1.0 - (vram_est / 12288.0))

            # E) Preferencia explícita (+0.25 bonus)
            s_pref = 0.25 if context.preferred_model_id and context.preferred_model_id == profile.name else 0.0

            total_score = (0.40 * s_affinity) + (0.20 * s_comp) + (0.20 * s_perf) + (0.20 * s_vram) + s_pref
            scores_map[profile.name] = total_score
            scored_models.append((profile, total_score, f"Affinity={s_affinity:.2f}, Comp={s_comp:.2f}, Perf={s_perf:.2f}, VRAM={s_vram:.2f}"))

        # 5. Ordenar candidatos por score descendente
        scored_models.sort(key=lambda x: x[1], reverse=True)
        top_model, top_score, breakdown_reason = scored_models[0]
        fallback_chain = tuple(m[0].name for m in scored_models[1:])

        # 6. Calcular confianza (0.60 a 0.99)
        confidence = min(0.99, max(0.60, top_score))

        return ModelRoutingDecision(
            selected_model=top_model,
            task_type=context.task_type,
            complexity=context.complexity,
            confidence=confidence,
            reason=f"Modelo '{top_model.name}' seleccionado para '{context.task_type.value}' ({breakdown_reason}).",
            candidate_scores=scores_map,
            fallback_chain=fallback_chain,
            vram_allocated_mb=top_model.vram_estimate_mb or 4000,
        )

    def _find_vision_candidate(self, context: RoutingContext) -> ModelProfile | None:
        """Busca el primer modelo disponible con capacidad multimodal de visión."""
        for profile in self._registry.list_models():
            if profile.name in context.excluded_model_ids:
                continue
            if (profile.vision or profile.supports_vision) and self._is_model_eligible(
                profile, context, ignore_vision_check=True
            ):
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
        if not ignore_vision_check and (context.requires_vision or context.task_type == TaskType.VISION):
            if not (profile.vision or profile.supports_vision):
                return False

        # Comprobar requerimiento de herramientas
        if context.requires_tools:
            if not (profile.tool_calling or profile.supports_tools):
                return False

        # Comprobar restricción de VRAM si se especificó
        if context.max_available_vram_mb is not None and profile.vram_estimate_mb is not None:
            if profile.vram_estimate_mb > context.max_available_vram_mb:
                return False

        return True
