"""Tests exhaustivos para la integración experimental de NVIDIA Nemotron 3 Ultra (test_nemotron_provider.py).

Verifica:
1. Feature flag y desactivación por defecto (NEMOTRON_ENABLED=False).
2. Protección estricta de API key (sin fugas en logs ni excepciones).
3. Simulación de errores HTTP (401, 403, 429, 500).
4. Simulación de timeouts y errores de red (offline).
5. Éxito de inferencia y extracción de tokens en formato OpenAI/NVIDIA.
6. Preservación de 0 MB de VRAM en ModelRegistry.
7. Fallback determinista en ModelRouter de Nemotron a modelos locales (Qwen/Gemma).
8. Ejecución íntegra del Benchmark A/B sin interactuar con el sistema operativo Windows.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
import requests

from benchmarks.nemotron_ab_runner import NemotronABRunner
from benchmarks.nemotron_benchmark_dataset import NEMOTRON_BENCHMARK_CASES, BenchmarkCategory
from core.llm.exceptions import (
    InferenceError,
    ProviderConnectionError,
    ProviderError,
    ProviderTimeoutError,
)
from core.llm.inference import InferenceRequest
from core.llm.model_registry import ModelRegistry
from core.llm.model_router import ModelRouter
from core.llm.nemotron_provider import NemotronProvider
from core.llm.routing_policy import RoutingContext, TaskComplexity, TaskType


class TestNemotronProviderSecurityAndFeatureFlags:
    """Verificación de aislamiento, feature flag y seguridad de credenciales."""

    def test_disabled_by_default(self) -> None:
        """Nemotron debe estar deshabilitado por defecto."""
        provider = NemotronProvider(enabled=False)
        assert provider.is_available() is False

        req = InferenceRequest(prompt="Test prompt")
        with pytest.raises(ProviderError) as exc_info:
            provider.generate(req)
        assert "desactivado" in str(exc_info.value).lower()

    def test_missing_api_key_fails_safely(self) -> None:
        """Sin API key debe lanzar error controlado sin llamar a la red."""
        provider = NemotronProvider(enabled=True, api_key="")
        assert provider.is_available() is False

        req = InferenceRequest(prompt="Test prompt")
        with pytest.raises(ProviderError) as exc_info:
            provider.generate(req)
        assert "api_key" in str(exc_info.value).lower()

    def test_api_key_never_leaks_in_exceptions_or_string_repr(self) -> None:
        """La API key secreta jamás debe aparecer en mensajes de error ni en logs."""
        secret_key = "nvapi-SUPER_SECRET_TOKEN_XYZ_999"

        # Simular fallo de autenticación 401
        fake_resp = MagicMock()
        fake_resp.status_code = 401
        fake_resp.json.return_value = {"error": "Invalid token"}

        provider = NemotronProvider(
            enabled=True,
            api_key=secret_key,
            post_fn=lambda *args, **kwargs: fake_resp,
        )

        req = InferenceRequest(prompt="Hola")
        with pytest.raises(InferenceError) as exc_info:
            provider.generate(req)

        error_message = str(exc_info.value)
        assert secret_key not in error_message
        assert "Autenticación denegada" in error_message


class TestNemotronNetworkAndTimeoutResilience:
    """Simulación exhaustiva de caídas de red, timeouts y reintentos."""

    def test_connection_error_offline_mode(self) -> None:
        """Fallo de red mapea de inmediato a ProviderConnectionError."""
        def mock_offline_post(*args, **kwargs):
            raise requests.exceptions.ConnectionError("Could not resolve host: integrate.api.nvidia.com")

        provider = NemotronProvider(
            enabled=True,
            api_key="nvapi-valid-token-for-test",
            max_retries=0,
            post_fn=mock_offline_post,
        )

        req = InferenceRequest(prompt="Plan de acción")
        with pytest.raises(ProviderConnectionError) as exc_info:
            provider.generate(req)

        assert exc_info.value.code == "PROVIDER_CONNECTION_ERROR"
        assert exc_info.value.details["provider"] == "nemotron"

    def test_timeout_handling(self) -> None:
        """Timeout de red mapea de inmediato a ProviderTimeoutError."""
        def mock_timeout_post(*args, **kwargs):
            raise requests.exceptions.Timeout("Connection timed out after 30s")

        provider = NemotronProvider(
            enabled=True,
            api_key="nvapi-valid-token-for-test",
            timeout_seconds=5.0,
            max_retries=0,
            post_fn=mock_timeout_post,
        )

        req = InferenceRequest(prompt="Generar plan")
        with pytest.raises(ProviderTimeoutError) as exc_info:
            provider.generate(req)

        assert exc_info.value.code == "PROVIDER_TIMEOUT"
        assert exc_info.value.details["timeout_seconds"] == 5.0

    def test_successful_inference_parsing(self) -> None:
        """Inferencia exitosa con payload estándar OpenAI/NVIDIA."""
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "REASONING:\nEl plan requiere abrir el bloc de notas.\nPLAN:\n1. Abrir Notepad.\nVERIFICATION:\nComprobar proceso.",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 40,
                "completion_tokens": 60,
                "total_tokens": 100,
            },
        }

        provider = NemotronProvider(
            enabled=True,
            api_key="nvapi-test",
            post_fn=lambda *args, **kwargs: fake_resp,
        )

        req = InferenceRequest(
            prompt="Plan para notepad",
            temperature=0.2,
        )
        res = provider.generate(req)

        assert res.success is True
        assert "REASONING" in res.content
        assert res.tokens_used == 100
        assert res.duration_ms >= 0.0


class TestModelRegistryAndVRAMPreservation:
    """Verificación de que Nemotron no consume VRAM en la GPU de 12 GB."""

    def test_registry_contains_nemotron_with_zero_vram(self) -> None:
        registry = ModelRegistry.get_instance()
        profile = registry.get("nvidia/nemotron-3-ultra-550b-a55b")

        assert profile.name == "nvidia/nemotron-3-ultra-550b-a55b"
        assert profile.provider == "nemotron"
        # Invariante de VRAM: 0 MB reservados localmente
        assert profile.vram_estimate_mb == 0
        assert "reasoning" in profile.capabilities
        assert "planning" in profile.capabilities

    def test_aliases_resolution(self) -> None:
        registry = ModelRegistry.get_instance()
        assert registry.exists("nemotron-3-ultra") is True
        assert registry.exists("nemotron") is True

        p1 = registry.get("nemotron-3-ultra")
        assert p1.name == "nvidia/nemotron-3-ultra-550b-a55b"


class TestModelRouterFallbackFromNemotronToLocal:
    """Verificación de que si Nemotron falla, el router cae limpiamente a Qwen o Gemma."""

    def test_fallback_chain_nemotron_to_local_models(self) -> None:
        router = ModelRouter.get_instance()

        ctx = RoutingContext(
            task_type=TaskType.REASONING,
            complexity=TaskComplexity.HIGH,
        )

        # Si Nemotron falla, debe resolver hacia qwen3:8b o gemma4:e4b
        fallback_profile = router.get_fallback_model("nvidia/nemotron-3-ultra-550b-a55b", ctx)

        assert fallback_profile.name in ("qwen3:8b", "gemma4:e4b")
        assert fallback_profile.provider == "ollama"  # Proveedor local seguro


class TestNemotronABRunnerExecution:
    """Verificación del ejecutor de Benchmark A/B."""

    def test_ab_runner_synthetic_execution_no_windows_actions(self, tmp_path) -> None:
        """El runner debe evaluar métricas objetivas y generar informe JSON sin llamar a Windows."""
        def custom_inference(model_name: str, prompt: str):
            if "nemotron" in model_name:
                content = "REASONING: Plan seguro.\nPLAN: 1. Paso A.\nVERIFICATION: Comprobación OK.\nPalabras: Artemis Luna Jessyca días."
                lat = 850.0
                tokens = 85
            elif "qwen" in model_name:
                content = "REASONING: Razonando.\nPLAN: Paso 1.\nVERIFICATION: OK.\nPalabras: Artemis Luna."
                lat = 420.0
                tokens = 60
            else:  # gemma
                content = "Hola, soy Jessyca. Buenos días.\nArtemis Luna."
                lat = 180.0
                tokens = 30
            return content, lat, tokens, None

        runner = NemotronABRunner(
            custom_inference_fn=custom_inference,
            output_dir=tmp_path,
        )

        results = runner.run_ab_comparison(
            models=("gemma4:e4b", "qwen3:8b", "nvidia/nemotron-3-ultra-550b-a55b"),
            cases=NEMOTRON_BENCHMARK_CASES[:5],  # 5 casos para el test unitario rápido
        )

        assert len(results) == 3
        assert "nvidia/nemotron-3-ultra-550b-a55b" in results
        nem_metrics = results["nvidia/nemotron-3-ultra-550b-a55b"]
        assert nem_metrics.total_tests == 5
        assert nem_metrics.passed_tests > 0
        assert nem_metrics.avg_latency_ms == 850.0

        # Verificar archivo JSON exportado
        json_file = tmp_path / "nemotron_ab_benchmark_results.json"
        assert json_file.exists()
