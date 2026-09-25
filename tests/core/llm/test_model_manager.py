"""Tests unitarios exhaustivos para ModelManager (Fase 1: Multi-LLM Foundation)."""

import pytest

from core.llm.exceptions import ModelNotFoundError
from core.llm.model_manager import ModelManager, get_model_manager
from core.llm.model_registry import ModelRegistry


class TestModelManager:
    """Pruebas de gestión y resolución de modelos para ModelManager."""

    def setup_method(self) -> None:
        """Restablece el registro global antes de cada test."""
        ModelRegistry.reset_registry()

    def test_default_model_resolution(self) -> None:
        """Verifica que sin argumentos se resuelva el modelo predeterminado."""
        manager = ModelManager(default_model_name="gemma4:e4b")
        profile = manager.get_model()
        assert profile.name == "gemma4:e4b"
        assert manager.get_default_model_name() == "gemma4:e4b"

    def test_explicit_model_resolution(self) -> None:
        """Verifica la resolución explícita de un modelo específico."""
        manager = ModelManager()
        profile = manager.get_model("qwen3:8b")
        assert profile.name == "qwen3:8b"
        assert profile.provider == "ollama"

    def test_set_valid_default_model(self) -> None:
        """Verifica el cambio dinámico del modelo predeterminado."""
        manager = ModelManager()
        manager.set_default_model("llama3.2")
        assert manager.get_default_model_name() == "llama3.2"
        assert manager.get_model().name == "llama3.2"

    def test_set_invalid_default_model_raises_error(self) -> None:
        """Verifica que intentar fijar un modelo inexistente como default falle de inmediato."""
        manager = ModelManager()
        with pytest.raises(ModelNotFoundError):
            manager.set_default_model("modelo-ficticio-no-registrado")

    def test_list_available_models(self) -> None:
        """Verifica que se liste la totalidad de modelos disponibles."""
        manager = ModelManager()
        models = manager.list_available_models()
        assert len(models) >= 5
        names = [m.name for m in models]
        assert "qwen3-vl:4b" in names

    def test_is_model_available(self) -> None:
        """Verifica la comprobación rápida de disponibilidad."""
        manager = ModelManager()
        assert manager.is_model_available("llama3.1") is True
        assert manager.is_model_available("modelo_fantasma") is False

    def test_singleton_accessor(self) -> None:
        """Verifica que get_model_manager() retorne una instancia funcional."""
        m1 = get_model_manager()
        m2 = ModelManager.get_instance()
        assert m1 is m2

    def test_auto_route_delegation_to_model_router(self) -> None:
        """Verifica que solicitar 'auto-routed' delegue la resolución al ModelRouter."""
        manager = ModelManager()
        profile = manager.get_model("auto-routed")
        # Por defecto el contexto resuelve a gemma4:e4b (análisis y verificación)
        assert profile.name == "gemma4:e4b"
        assert profile.enabled is True

    def test_auto_route_with_specific_context(self) -> None:
        """Verifica que auto-routed respete el RoutingContext suministrado (ej. clasificación -> llama3.2)."""
        from core.llm.routing_policy import RoutingContext, TaskComplexity, TaskType

        manager = ModelManager()
        ctx = RoutingContext(task_type=TaskType.CLASSIFICATION, complexity=TaskComplexity.LOW)
        profile = manager.get_model("auto-routed", context=ctx)
        assert profile.name == "llama3.2"

        ctx_vision = RoutingContext(task_type=TaskType.VISION)
        profile_vision = manager.get_model("auto-routed", context=ctx_vision)
        assert profile_vision.name == "qwen3-vl:4b"

    def test_auto_route_fallback_on_router_error(self) -> None:
        """Verifica que si el router arroja una excepción, ModelManager use fallback seguro al default."""
        class BrokenRouter:
            def route(self, context: object) -> object:
                raise RuntimeError("Simulated router outage")

        manager = ModelManager(default_model_name="gemma4:e4b", router=BrokenRouter())
        profile = manager.get_model("auto-routed")
        assert profile.name == "gemma4:e4b"
