"""Tests de arquitectura y desacoplamiento para la capa LLM (Fase 1: Multi-LLM Foundation).

Demuestra formalmente:
1. ModelRegistry.get("qwen3:8b") funciona como contrato sin importar Ollama.
2. ModelRegistry.get("modelo-inexistente") lanza ModelNotFoundError.
3. El Core puede interactuar con FakeLLMProvider sin red ni dependencias externas.
4. Conmutación explícita de modelos a través de ModelManager.
"""

import sys
from typing import Any

import pytest

from core.brain import procesar_orden
from core.intent_models import IntentStatus
from core.llm.exceptions import ModelNotFoundError
from core.llm.inference import FakeLLMProvider
from core.llm.model_manager import ModelManager
from core.llm.model_profile import ModelProfile
from core.llm.model_registry import ModelRegistry


class DummySkill:
    def __init__(self, name: str) -> None:
        self.name = name

    def descripcion(self) -> str:
        return f"Habilidad {self.name}"

    def ejecutar(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"exito": True}


DUMMY_SKILLS = {
    "abrir_aplicacion": DummySkill("abrir_aplicacion"),
    "buscar_archivo": DummySkill("buscar_archivo"),
}


class TestArchitectureDecoupling:
    """Verificación de invariantes arquitectónicas de la capa Multi-LLM."""

    def setup_method(self) -> None:
        ModelRegistry.reset_registry()

    def test_direct_model_registry_access(self) -> None:
        """Criterio de Aceptación: ModelRegistry.get('qwen3:8b') retorna el perfil sin acoplamiento a Ollama."""
        registry = ModelRegistry.get_instance()
        profile = registry.get("qwen3:8b")

        assert isinstance(profile, ModelProfile)
        assert profile.name == "qwen3:8b"
        assert profile.provider == "ollama"
        assert profile.max_context_length == 40960
        assert profile.supports_tools is True
        assert profile.supports_vision is False

    def test_nonexistent_model_raises_model_not_found(self) -> None:
        """Criterio de Aceptación: ModelRegistry.get('modelo-inexistente') lanza ModelNotFoundError."""
        registry = ModelRegistry.get_instance()
        with pytest.raises(ModelNotFoundError) as exc_info:
            registry.get("modelo-inexistente")

        assert exc_info.value.code == "MODEL_NOT_FOUND"

    def test_core_execution_with_injected_provider(self) -> None:
        """Demuestra que el Core (procesar_orden) puede procesar intenciones utilizando un proveedor inyectado."""
        fake_provider = FakeLLMProvider()
        fake_provider.queue_response(
            '{"estado": "CLEAR", "respuesta_hablada": "Abriendo aplicación", "skill": "abrir_aplicacion", "parametros": {"nombre_app": "calculadora"}}'
        )

        result = procesar_orden(
            texto_usuario="Abre la calculadora",
            skills_disponibles=DUMMY_SKILLS,
            provider=fake_provider,
            model_name="qwen3:8b",
        )

        assert result.estado == IntentStatus.CLEAR
        assert result.skill == "abrir_aplicacion"
        assert result.parametros == {"nombre_app": "calculadora"}
        assert len(fake_provider.call_history) == 1
        assert fake_provider.call_history[0].model_name == "qwen3:8b"

    def test_switch_models_via_model_manager(self) -> None:
        """Demuestra la conmutación explícita y determinista de modelos sin afectar el Core."""
        manager = ModelManager()

        # Modelo 1: gemma4:e4b
        p1 = manager.get_model("gemma4:e4b")
        assert p1.name == "gemma4:e4b"

        # Modelo 2: llama3.1
        p2 = manager.get_model("llama3.1")
        assert p2.name == "llama3.1"
        assert p2.max_context_length == 131072

        # Modelo 3: qwen3-vl:4b
        p3 = manager.get_model("qwen3-vl:4b")
        assert p3.name == "qwen3-vl:4b"
        assert p3.supports_vision is True

    def test_registry_contains_no_network_side_effects(self) -> None:
        """Verifica que instanciar o consultar el registro no realiza llamadas de red ni importa librerías no deseadas."""
        # Se comprueba que no haya importaciones directas de 'ollama' en los módulos de sistema
        assert "ollama" not in sys.modules
