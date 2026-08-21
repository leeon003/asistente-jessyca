"""Tests unitarios exhaustivos para ModelRouter y RoutingPolicy (Fase 2: Dynamic Model Router)."""

from core.llm.model_profile import ModelProfile
from core.llm.model_registry import ModelRegistry
from core.llm.model_router import ModelRouter, get_model_router
from core.llm.routing_policy import (
    RoutingContext,
    TaskComplexity,
    TaskType,
)


class TestModelRouter:
    """Pruebas funcionales de enrutamiento dinámico, políticas y fallback."""

    def setup_method(self) -> None:
        """Restablece el registro a su estado de fábrica antes de cada prueba."""
        ModelRegistry.reset_registry()

    def test_routing_simple_and_classification(self) -> None:
        """Verifica que tareas simples o de clasificación se enruten a llama3.2."""
        router = ModelRouter()

        # Clasificación rápida -> llama3.2
        p1 = router.select_model_for_task(TaskType.CLASSIFICATION, complexity=TaskComplexity.LOW)
        assert p1.name == "llama3.2"

        # Tarea simple -> llama3.2
        p2 = router.select_model_for_task(TaskType.SIMPLE_TASK, complexity=TaskComplexity.LOW)
        assert p2.name == "llama3.2"

    def test_routing_conversation(self) -> None:
        """Verifica que tareas de conversación se enruten a llama3.1."""
        router = ModelRouter()
        p = router.select_model_for_task(TaskType.CONVERSATION, complexity=TaskComplexity.MEDIUM)
        assert p.name == "llama3.1"

    def test_routing_reasoning_and_planning(self) -> None:
        """Verifica que razonamiento, planificación y alta complejidad se enruten a qwen3:8b."""
        router = ModelRouter()

        # Razonamiento -> qwen3:8b
        p_reason = router.select_model_for_task(TaskType.REASONING)
        assert p_reason.name == "qwen3:8b"

        # Planificación -> qwen3:8b
        p_plan = router.select_model_for_task(TaskType.PLANNING)
        assert p_plan.name == "qwen3:8b"

        # Tarea general con complejidad HIGH -> escala a qwen3:8b
        p_high = router.select_model_for_task(TaskType.ANALYSIS_VERIFICATION, complexity=TaskComplexity.HIGH)
        assert p_high.name == "qwen3:8b"

    def test_routing_analysis_and_verification(self) -> None:
        """Verifica que análisis y verificación estándar se enruten a gemma4:e4b."""
        router = ModelRouter()
        p = router.select_model_for_task(TaskType.ANALYSIS_VERIFICATION, complexity=TaskComplexity.MEDIUM)
        assert p.name == "gemma4:e4b"

    def test_routing_vision(self) -> None:
        """Verifica que tareas con requerimiento visual se enruten a qwen3-vl:4b."""
        router = ModelRouter()

        # Por TaskType.VISION
        p1 = router.select_model_for_task(TaskType.VISION)
        assert p1.name == "qwen3-vl:4b"
        assert p1.vision is True

        # Por flag requires_vision=True
        p2 = router.select_model_for_task(TaskType.CLASSIFICATION, requires_vision=True)
        assert p2.name == "qwen3-vl:4b"
        assert p2.vision is True

    def test_routing_fallback_when_model_disabled(self) -> None:
        """Verifica que si el modelo primario está deshabilitado, el router seleccione el siguiente candidato compatible."""
        registry = ModelRegistry.get_instance()
        # Deshabilitar qwen3:8b
        disabled_qwen = ModelProfile(
            model_id="qwen3:8b",
            provider="ollama",
            capabilities=("completion", "tools", "thinking"),
            enabled=False,
        )
        registry.register(disabled_qwen, overwrite=True)

        router = ModelRouter(registry=registry)
        # La tarea de razonamiento debe hacer fallback (a gemma4:e4b o llama3.1)
        selected = router.select_model_for_task(TaskType.REASONING)
        assert selected.name != "qwen3:8b"
        assert selected.enabled is True

    def test_routing_fallback_on_insufficient_vram(self) -> None:
        """Verifica que si la VRAM disponible es insuficiente, se elija un modelo más ligero."""
        router = ModelRouter()
        # qwen3:8b requiere ~5700MB. Si solo hay 3000MB disponibles, debe elegir llama3.2 (~2500MB)
        selected = router.select_model_for_task(
            TaskType.REASONING,
            max_vram_mb=3000,
        )
        assert selected.name == "llama3.2"

    def test_routing_fallback_explicit_method(self) -> None:
        """Verifica el método get_fallback_model ante fallo del modelo seleccionado."""
        router = ModelRouter()
        context = RoutingContext(task_type=TaskType.REASONING)

        # Si qwen3:8b falla en runtime, get_fallback_model debe excluirlo y ofrecer el respaldo
        fallback_profile = router.get_fallback_model("qwen3:8b", context=context)
        assert fallback_profile.name != "qwen3:8b"
        assert fallback_profile.enabled is True

    def test_routing_nonexistent_preferred_model_falls_back(self) -> None:
        """Verifica que solicitar un modelo preferido inexistente active el fallback de forma transparente."""
        router = ModelRouter()
        context = RoutingContext(
            task_type=TaskType.CLASSIFICATION,
            preferred_model_id="modelo_inexistente_123",
        )
        selected = router.route(context)
        assert selected.name == "llama3.2"

    def test_singleton_accessor(self) -> None:
        """Verifica que get_model_router() retorne la instancia global."""
        r1 = get_model_router()
        r2 = ModelRouter.get_instance()
        assert r1 is r2
