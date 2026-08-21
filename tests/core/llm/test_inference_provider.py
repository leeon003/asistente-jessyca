"""Tests unitarios para LLMProvider, OllamaProvider y FakeLLMProvider (Fase 1: Multi-LLM Foundation)."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from core.llm.exceptions import (
    InferenceError,
    ProviderConnectionError,
    ProviderTimeoutError,
)
from core.llm.inference import (
    FakeLLMProvider,
    InferenceRequest,
    LLMProvider,
    OllamaProvider,
)
from core.llm.model_registry import ModelRegistry


class TestInferenceProviders:
    """Pruebas funcionales de proveedores de inferencia."""

    def setup_method(self) -> None:
        ModelRegistry.reset_registry()

    def test_fake_provider_satisfies_protocol(self) -> None:
        """Verifica que FakeLLMProvider cumpla con el protocolo LLMProvider."""
        provider = FakeLLMProvider()
        assert isinstance(provider, LLMProvider)
        assert provider.is_available() is True

    def test_fake_provider_predictable_responses(self) -> None:
        """Verifica que FakeLLMProvider entregue respuestas simuladas y registre historial."""
        provider = FakeLLMProvider()
        provider.queue_response('{"estado": "CLEAR", "skill": "abrir_aplicacion"}')

        req = InferenceRequest(prompt="Abre el bloc de notas", model_name="qwen3:8b")
        res = provider.generate(req)

        assert res.success is True
        assert res.model_name == "qwen3:8b"
        assert "abrir_aplicacion" in res.content
        assert len(provider.call_history) == 1
        assert provider.call_history[0].prompt == "Abre el bloc de notas"

    def test_fake_provider_generate_text_helper(self) -> None:
        """Verifica el método generate_text de FakeLLMProvider."""
        provider = FakeLLMProvider(default_response="Texto directo")
        text = provider.generate_text("hola")
        assert text == "Texto directo"

    def test_fake_provider_disconnection_simulation(self) -> None:
        """Verifica la simulación de caída de conexión en FakeLLMProvider."""
        provider = FakeLLMProvider()
        provider.is_connected = False
        with pytest.raises(ProviderConnectionError):
            provider.generate(InferenceRequest(prompt="test"))

    def test_ollama_provider_endpoint_property(self) -> None:
        """Verifica la propiedad endpoint de OllamaProvider."""
        provider = OllamaProvider(host="http://localhost:11434")
        assert provider.endpoint == "http://localhost:11434/api/generate"

    @patch("core.llm.inference.requests.post")
    def test_ollama_provider_successful_generation(self, mock_post: MagicMock) -> None:
        """Verifica que OllamaProvider construya el payload adecuado y devuelva InferenceResponse."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "response": '{"estado": "CLEAR", "skill": "buscar_archivo"}',
            "eval_count": 42,
        }
        mock_post.return_value = mock_resp

        provider = OllamaProvider(host="http://localhost:11434")
        req = InferenceRequest(
            prompt="Busca mis fotos",
            system_prompt="Eres Jessyca",
            model_name="llama3.1",
            temperature=0.2,
            stream=False,
        )
        res = provider.generate(req)

        assert res.success is True
        assert res.model_name == "llama3.1"
        assert res.tokens_used == 42
        assert "buscar_archivo" in res.content

        # Verificar payload enviado
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["model"] == "llama3.1"
        assert payload["prompt"] == "Busca mis fotos"
        assert payload["system"] == "Eres Jessyca"
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0.2

    @patch("core.llm.inference.requests.post", side_effect=requests.exceptions.ConnectionError("Connection refused"))
    def test_ollama_provider_connection_error_mapping(self, mock_post: MagicMock) -> None:
        """Verifica que fallos de conexión HTTP se mapeen limpiamente a ProviderConnectionError."""
        provider = OllamaProvider(host="http://localhost:11434")
        req = InferenceRequest(prompt="test")
        with pytest.raises(ProviderConnectionError) as exc_info:
            provider.generate(req)
        assert exc_info.value.code == "PROVIDER_CONNECTION_ERROR"
        assert "localhost:11434" in str(exc_info.value)

    @patch("core.llm.inference.requests.post", side_effect=requests.exceptions.Timeout("Request timed out"))
    def test_ollama_provider_timeout_mapping(self, mock_post: MagicMock) -> None:
        """Verifica que timeouts HTTP se mapeen a ProviderTimeoutError."""
        provider = OllamaProvider(host="http://localhost:11434", timeout_seconds=5.0)
        req = InferenceRequest(prompt="test")
        with pytest.raises(ProviderTimeoutError) as exc_info:
            provider.generate(req)
        assert exc_info.value.code == "PROVIDER_TIMEOUT"

    @patch("core.llm.inference.requests.post", side_effect=Exception("Unexpected internal failure"))
    def test_ollama_provider_generic_error_mapping(self, mock_post: MagicMock) -> None:
        """Verifica que errores inesperados se capturen como InferenceError."""
        provider = OllamaProvider(host="http://localhost:11434")
        req = InferenceRequest(prompt="test")
        with pytest.raises(InferenceError):
            provider.generate(req)

    @patch("core.llm.inference.requests.get")
    def test_ollama_provider_is_available(self, mock_get: MagicMock) -> None:
        """Verifica la comprobación de disponibilidad de OllamaProvider."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        provider = OllamaProvider(host="http://localhost:11434")
        assert provider.is_available() is True

        mock_get.side_effect = Exception("Offline")
        assert provider.is_available() is False
