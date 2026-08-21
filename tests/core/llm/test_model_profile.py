"""Tests unitarios exhaustivos para ModelProfile (Fase 1: Multi-LLM Foundation)."""

import dataclasses

import pytest

from core.llm.exceptions import ModelRegistrationError
from core.llm.model_profile import ModelProfile


class TestModelProfile:
    """Pruebas de validación, estructura e inmutabilidad para ModelProfile."""

    def test_create_valid_profile_with_all_fields(self) -> None:
        profile = ModelProfile(
            model_id="qwen3:8b",
            provider="ollama",
            capabilities=("completion", "tools", "thinking"),
            context_length=40960,
            input_modalities=("text",),
            output_modalities=("text",),
            vision=False,
            tool_calling=True,
            reasoning=True,
            priority=1,
            vram_estimate_mb=5700,
            enabled=True,
            default_parameters={"temperature": 0.1},
            description="Modelo Qwen 3 8B",
        )
        assert profile.model_id == "qwen3:8b"
        assert profile.name == "qwen3:8b"
        assert profile.provider == "ollama"
        assert "thinking" in profile.capabilities
        assert profile.context_length == 40960
        assert profile.max_context_length == 40960
        assert profile.vision is False
        assert profile.supports_vision is False
        assert profile.tool_calling is True
        assert profile.supports_tools is True
        assert profile.reasoning is True
        assert profile.priority == 1
        assert profile.vram_estimate_mb == 5700
        assert profile.enabled is True
        assert profile.default_parameters == {"temperature": 0.1}

    def test_model_profile_immutability(self) -> None:
        profile = ModelProfile(model_id="gemma4:e4b", provider="ollama")
        with pytest.raises(dataclasses.FrozenInstanceError):
            profile.name = "nuevo_nombre"  # type: ignore[misc]

    def test_invalid_empty_name_raises_error(self) -> None:
        with pytest.raises(ModelRegistrationError) as exc_info:
            ModelProfile(model_id="", provider="ollama")
        assert exc_info.value.code == "INVALID_MODEL_NAME"

        with pytest.raises(ModelRegistrationError):
            ModelProfile(model_id="   ", provider="ollama")

    def test_invalid_empty_provider_raises_error(self) -> None:
        with pytest.raises(ModelRegistrationError) as exc_info:
            ModelProfile(model_id="llama3.1", provider="")
        assert exc_info.value.code == "INVALID_PROVIDER_NAME"

    def test_invalid_context_length_raises_error(self) -> None:
        with pytest.raises(ModelRegistrationError) as exc_info:
            ModelProfile(model_id="test_model", provider="ollama", context_length=-10)
        assert exc_info.value.code == "INVALID_CONTEXT_LENGTH"

        with pytest.raises(ModelRegistrationError):
            ModelProfile(model_id="test_model", provider="ollama", context_length=0)

    def test_to_dict_serialization(self) -> None:
        profile = ModelProfile(
            model_id="qwen3-vl:4b",
            provider="ollama",
            capabilities=("completion", "vision"),
            context_length=262144,
            input_modalities=("text", "image"),
            output_modalities=("text",),
            vision=True,
            tool_calling=True,
            reasoning=False,
            priority=2,
            vram_estimate_mb=3600,
            enabled=True,
            description="Modelo multimodal",
        )
        d = profile.to_dict()
        assert d["model_id"] == "qwen3-vl:4b"
        assert d["name"] == "qwen3-vl:4b"
        assert d["vision"] is True
        assert d["supports_vision"] is True
        assert d["tool_calling"] is True
        assert d["supports_tools"] is True
        assert d["vram_estimate_mb"] == 3600
        assert d["enabled"] is True
        assert "image" in d["input_modalities"]
        assert isinstance(d["capabilities"], list)
