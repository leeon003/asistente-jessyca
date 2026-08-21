"""Tests unitarios exhaustivos para ModelRegistry (Fase 1: Multi-LLM Foundation)."""

import pytest

from core.llm.exceptions import DuplicateModelError, ModelNotFoundError
from core.llm.model_profile import ModelProfile
from core.llm.model_registry import ModelRegistry, get_model_profile


class TestModelRegistry:
    """Pruebas funcionales y de catálogo para ModelRegistry."""

    def setup_method(self) -> None:
        """Restablece el registro global antes de cada test."""
        ModelRegistry.reset_registry()

    def test_default_models_registered(self) -> None:
        """Verifica que los 5 modelos objetivo estén registrados por defecto."""
        registry = ModelRegistry.get_instance()
        names = registry.list_names()
        expected = ["gemma4:e4b", "llama3.1", "llama3.2", "qwen3-vl:4b", "qwen3:8b"]
        for exp in expected:
            assert exp in names
            assert registry.exists(exp) is True

    def test_get_model_success_all_five(self) -> None:
        """Verifica la recuperación exitosa de perfiles individuales."""
        # 1. llama3.2:latest / llama3.2
        p_llama32 = ModelRegistry.get_profile("llama3.2:latest")
        assert p_llama32.name == "llama3.2"
        assert p_llama32.provider == "ollama"

        # 2. llama3.1:latest / llama3.1
        p_llama31 = ModelRegistry.get_profile("llama3.1:latest")
        assert p_llama31.name == "llama3.1"
        assert p_llama31.context_length == 131072

        # 3. qwen3:8b
        p_qwen = ModelRegistry.get_profile("qwen3:8b")
        assert p_qwen.name == "qwen3:8b"
        assert p_qwen.tool_calling is True

        # 4. qwen3-vl:4b
        p_vl = ModelRegistry.get_profile("qwen3-vl:4b")
        assert p_vl.vision is True
        assert "image" in p_vl.input_modalities

        # 5. gemma4:e4b
        p_gemma = ModelRegistry.get_profile("gemma4:e4b")
        assert p_gemma.name == "gemma4:e4b"
        assert p_gemma.enabled is True

    def test_get_nonexistent_model_raises_error(self) -> None:
        """Verifica que solicitar un modelo inexistente lance ModelNotFoundError."""
        with pytest.raises(ModelNotFoundError) as exc_info:
            ModelRegistry.get_profile("modelo-inexistente")
        assert exc_info.value.code == "MODEL_NOT_FOUND"
        assert "modelo-inexistente" in str(exc_info.value)

    def test_register_custom_model(self) -> None:
        """Verifica el registro dinámico de nuevos perfiles de modelos."""
        registry = ModelRegistry.get_instance()
        custom_profile = ModelProfile(
            model_id="custom-model:latest",
            provider="ollama",
            capabilities=("completion",),
            description="Modelo personalizado para pruebas",
        )
        registry.register(custom_profile)
        assert registry.exists("custom-model:latest") is True
        assert registry.get("custom-model:latest").model_id == "custom-model:latest"

    def test_duplicate_registration_prevention(self) -> None:
        """Verifica que registrar un duplicado sin flag overwrite lance DuplicateModelError."""
        registry = ModelRegistry.get_instance()
        duplicate_profile = ModelProfile(model_id="gemma4:e4b", provider="ollama")
        with pytest.raises(DuplicateModelError):
            registry.register(duplicate_profile, overwrite=False)

        # Con overwrite=True no debe lanzar error
        registry.register(duplicate_profile, overwrite=True)

    def test_alias_resolution(self) -> None:
        """Verifica que la resolución de nombres tolere etiquetas de versión (e.g. :latest)."""
        registry = ModelRegistry.get_instance()
        profile = registry.get("llama3.1:latest")
        assert profile.name == "llama3.1"

    def test_unregister_model(self) -> None:
        """Verifica la eliminación controlada de modelos del catálogo."""
        registry = ModelRegistry.get_instance()
        assert registry.exists("llama3.2") is True
        removed = registry.unregister("llama3.2")
        assert removed is True
        assert registry.exists("llama3.2") is False

        # Segundo intento de unregister retorna False
        assert registry.unregister("llama3.2") is False

    def test_get_model_profile_convenience_function(self) -> None:
        """Verifica la función helper a nivel de módulo."""
        p = get_model_profile("gemma4:e4b")
        assert p.model_id == "gemma4:e4b"
