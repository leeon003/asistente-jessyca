"""Suite integral de tests y benchmark para el Router Inteligente Experimental (tests/router/test_router_suite.py).

Verifica exhaustivamente:
1. Modos de operación (STATIC, SHADOW, EXPERIMENTAL).
2. Evaluación de los 50 casos del Benchmark de Routing (Fast, Technical, Reasoning, Planning, Offline, Ambiguous).
3. Respeto al flag de seguridad NEMOTRON_ENABLED=false (exclusión total de Nemotron).
4. Cadena de fallback determinista (Nemotron timeout/connection -> Qwen -> Gemma).
5. No declaración de falso éxito ante fallo total.
6. Regla estricta de voz (baja latencia en comandos interactivos).
7. Umbral de confianza y reversión a modelo local seguro.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.llm.exceptions import (
    InferenceError,
    ProviderConnectionError,
    ProviderTimeoutError,
)
from core.llm.experimental_router import (
    ExperimentalRouter,
    RouterDecision,
    RouterMode,
    ShadowLogger,
    TaskCategory,
)
from tests.router.test_cases import ROUTER_BENCHMARK_CASES, RouterTestCase


# ── FIXTURES ─────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_shadow_log(tmp_path: Path) -> Path:
    """Provee una ruta temporal para logs shadow aislados."""
    log_file = tmp_path / "test_shadow_log.jsonl"
    return log_file


@pytest.fixture
def shadow_logger(temp_shadow_log: Path) -> ShadowLogger:
    """Instancia de ShadowLogger apuntando a archivo temporal."""
    return ShadowLogger(log_path=temp_shadow_log)


# ── 1. TESTS DE MODOS DE OPERACIÓN ───────────────────────────────────────────

class TestRouterModes:
    """Verifica el comportamiento estricto de los modos STATIC, SHADOW y EXPERIMENTAL."""

    def test_static_mode_preserves_current_model(self, monkeypatch: pytest.MonkeyPatch, temp_shadow_log: Path) -> None:
        """En modo STATIC, el router NO altera el modelo de ejecución y NO genera logs shadow."""
        monkeypatch.setenv("MODEL_ROUTER_MODE", "static")
        monkeypatch.setenv("NEMOTRON_ENABLED", "true")
        logger_mock = ShadowLogger(log_path=temp_shadow_log)
        router = ExperimentalRouter(mode=RouterMode.STATIC, shadow_logger=logger_mock)

        exec_model, decision = router.route_execution(
            user_text="Planifica cómo solucionar este error de arquitectura y valida cada etapa",
            current_model="gemma4:e4b",
        )

        # Invariante: Modelo de ejecución idéntico al actual
        assert exec_model == "gemma4:e4b"
        assert decision.recommended_model == "nvidia/nemotron-3-ultra-550b-a55b"
        # No debe haber escrito en el archivo shadow
        assert not temp_shadow_log.exists() or temp_shadow_log.stat().st_size == 0

    def test_shadow_mode_logs_recommendation_without_changing_execution(
        self, monkeypatch: pytest.MonkeyPatch, temp_shadow_log: Path
    ) -> None:
        """En modo SHADOW, el router recomienda pero la ejecución permanece fija en el modelo actual."""
        monkeypatch.setenv("MODEL_ROUTER_MODE", "shadow")
        monkeypatch.setenv("NEMOTRON_ENABLED", "true")
        logger_mock = ShadowLogger(log_path=temp_shadow_log)
        router = ExperimentalRouter(mode=RouterMode.SHADOW, shadow_logger=logger_mock)

        exec_model, decision = router.route_execution(
            user_text="Diseña un plan para solucionar este problema multi-step",
            current_model="gemma4:e4b",
            request_id="req_shadow_test_01",
        )

        # Invariante: Ejecución inalterada
        assert exec_model == "gemma4:e4b"
        assert decision.recommended_model == "nvidia/nemotron-3-ultra-550b-a55b"

        # Verificación del log shadow
        assert temp_shadow_log.exists()
        lines = temp_shadow_log.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["request_id"] == "req_shadow_test_01"
        assert entry["current_model"] == "gemma4:e4b"
        assert entry["execution_model"] == "gemma4:e4b"
        assert entry["recommended_model"] == "nvidia/nemotron-3-ultra-550b-a55b"
        assert entry["router_mode"] == "shadow"
        assert entry["verification_result"] == "SHADOW_RECORDED"

    def test_experimental_mode_activates_recommended_model(
        self, monkeypatch: pytest.MonkeyPatch, temp_shadow_log: Path
    ) -> None:
        """En modo EXPERIMENTAL, el router realmente selecciona el modelo recomendado."""
        monkeypatch.setenv("MODEL_ROUTER_MODE", "experimental")
        monkeypatch.setenv("NEMOTRON_ENABLED", "true")
        logger_mock = ShadowLogger(log_path=temp_shadow_log)
        router = ExperimentalRouter(mode=RouterMode.EXPERIMENTAL, shadow_logger=logger_mock)

        exec_model, decision = router.route_execution(
            user_text="Analiza este traceback de Python con error de Singleton",
            current_model="gemma4:e4b",
            request_id="req_exp_test_01",
        )

        # En modo experimental, el modelo de ejecución es el recomendado (Qwen3)
        assert exec_model == "qwen3:8b"
        assert decision.recommended_model == "qwen3:8b"

        # Verificación en log
        assert temp_shadow_log.exists()
        entry = json.loads(temp_shadow_log.read_text(encoding="utf-8").strip())
        assert entry["execution_model"] == "qwen3:8b"
        assert entry["router_mode"] == "experimental"


# ── 2. TESTS DEL BENCHMARK (50 CASOS) ────────────────────────────────────────

class TestRouterBenchmarkDataset:
    """Ejecuta los 50 casos de prueba y valida exactitud de clasificación y modelos aceptables."""

    @pytest.mark.parametrize("case", ROUTER_BENCHMARK_CASES, ids=lambda c: c.test_id)
    def test_benchmark_case_routing(self, case: RouterTestCase, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifica que cada caso del benchmark clasifique a la categoría y modelo esperados."""
        # Configurar entorno para el caso
        if case.category in (TaskCategory.COMPLEX_REASONING, TaskCategory.AGENT_PLANNING):
            monkeypatch.setenv("NEMOTRON_ENABLED", "true")
        else:
            monkeypatch.setenv("NEMOTRON_ENABLED", "true")

        if case.is_offline:
            monkeypatch.setenv("INTERNET_AVAILABLE", "false")
        else:
            monkeypatch.setenv("INTERNET_AVAILABLE", "true")

        router = ExperimentalRouter()
        decision = router.route_decision(
            user_text=case.prompt,
            is_voice=case.is_voice,
            is_offline=case.is_offline,
        )

        # 1. Validar categoría de tarea
        assert decision.task_type == case.expected_task_type, (
            f"[{case.test_id}] Categoría esperada {case.expected_task_type}, "
            f"obtenida {decision.task_type} para prompt: '{case.prompt}'"
        )

        # 2. Validar que el modelo esté dentro del conjunto de modelos aceptables
        assert decision.recommended_model in case.acceptable_models, (
            f"[{case.test_id}] Modelo recomendado '{decision.recommended_model}' "
            f"no está en aceptables {case.acceptable_models} para prompt: '{case.prompt}'"
        )

        # 3. Validar confianza mínima
        assert decision.confidence >= case.minimum_confidence, (
            f"[{case.test_id}] Confianza {decision.confidence:.2f} inferior "
            f"a mínima requerida {case.minimum_confidence:.2f}"
        )


# ── 3. TESTS DE NEMOTRON DESHABILITADO Y PROTECCIONES ───────────────────────

class TestNemotronDisabledProtection:
    """Verifica que si NEMOTRON_ENABLED=false, Nemotron NUNCA es seleccionado."""

    @pytest.mark.parametrize("prompt", [
        "Planifica cómo solucionar este error de arquitectura y valida cada etapa paso a paso",
        "Analiza por qué el router está tomando decisiones contradictorias en el benchmark",
        "Diseña un plan para solucionar este problema multi-step e investiga los archivos",
    ])
    def test_nemotron_never_recommended_when_disabled(
        self, prompt: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Incluso en tareas de alta complejidad, si Nemotron está deshabilitado debe usar Qwen3."""
        monkeypatch.setenv("NEMOTRON_ENABLED", "false")
        router = ExperimentalRouter()

        decision = router.route_decision(user_text=prompt)

        assert "nemotron" not in decision.recommended_model.lower(), (
            f"Violación de seguridad: Nemotron fue recomendado con NEMOTRON_ENABLED=false para '{prompt}'"
        )
        assert decision.recommended_model == "qwen3:8b"
        assert decision.nemotron_available is False


# ── 4. TESTS DE REGLA ESTRICTA DE VOZ ────────────────────────────────────────

class TestVoiceLatencyRules:
    """Verifica que las órdenes de voz rápidas siempre prioricen a Gemma 4 (<400ms)."""

    @pytest.mark.parametrize("voice_prompt", [
        "Hola Jessica",
        "Abre el bloc",
        "Abre Google",
        "Cierra Google",
        "¿Qué hora es?",
        "Silencia el volumen",
    ])
    def test_voice_commands_always_route_to_gemma(
        self, voice_prompt: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Las órdenes de voz simples van a Gemma 4 independientemente del estado de Nemotron."""
        monkeypatch.setenv("NEMOTRON_ENABLED", "true")
        router = ExperimentalRouter()

        decision = router.route_decision(user_text=voice_prompt, is_voice=True)

        assert decision.recommended_model == "gemma4:e4b"
        assert decision.is_voice_command is True
        assert decision.task_type == TaskCategory.FAST_INTERACTION


# ── 5. TESTS DE FALLBACK DETERMINISTA Y TIMEOUTS ─────────────────────────────

class TestFallbackChain:
    """Verifica la cadena de fallback Nemotron -> Qwen -> Gemma y manejo de errores."""

    def test_primary_model_success_no_fallback_needed(self) -> None:
        """Si el modelo primario tiene éxito, no se llama a ningún fallback."""
        router = ExperimentalRouter()
        decision = RouterDecision(
            recommended_model="nvidia/nemotron-3-ultra-550b-a55b",
            confidence=0.91,
            reason="Complex reasoning",
            task_type=TaskCategory.COMPLEX_REASONING,
            estimated_complexity="high",
            fallback_chain=("qwen3:8b", "gemma4:e4b"),
            is_voice_command=False,
            nemotron_available=True,
        )

        mock_infer = MagicMock(return_value={"plan": "paso 1", "verified": True})
        res, model, attempts = router.execute_with_fallback(
            primary_model=decision.recommended_model,
            decision=decision,
            execute_fn=mock_infer,
        )

        assert res["verified"] is True
        assert model == "nvidia/nemotron-3-ultra-550b-a55b"
        assert attempts == ["nvidia/nemotron-3-ultra-550b-a55b"]
        assert mock_infer.call_count == 1

    def test_nemotron_timeout_cascades_to_qwen(self) -> None:
        """Si Nemotron da timeout, la ejecución pasa inmediatamente a Qwen3 y tiene éxito."""
        router = ExperimentalRouter()
        decision = RouterDecision(
            recommended_model="nvidia/nemotron-3-ultra-550b-a55b",
            confidence=0.91,
            reason="Complex planning",
            task_type=TaskCategory.AGENT_PLANNING,
            estimated_complexity="high",
            fallback_chain=("qwen3:8b", "gemma4:e4b"),
            is_voice_command=False,
            nemotron_available=True,
        )

        def mock_execution(model_name: str) -> dict[str, Any]:
            if "nemotron" in model_name:
                raise ProviderTimeoutError("Nemotron API timed out after 30.0s")
            return {"output": f"Éxito ejecutado con {model_name}"}

        res, model, attempts = router.execute_with_fallback(
            primary_model=decision.recommended_model,
            decision=decision,
            execute_fn=mock_execution,
        )

        assert model == "qwen3:8b"
        assert attempts == ["nvidia/nemotron-3-ultra-550b-a55b", "qwen3:8b"]
        assert "qwen3:8b" in res["output"]

    def test_nemotron_connection_error_cascades_to_qwen(self) -> None:
        """Si Nemotron tiene un fallo de conexión/red, la ejecución pasa a Qwen3."""
        router = ExperimentalRouter()
        decision = RouterDecision(
            recommended_model="nvidia/nemotron-3-ultra-550b-a55b",
            confidence=0.89,
            reason="Complex reasoning",
            task_type=TaskCategory.COMPLEX_REASONING,
            estimated_complexity="high",
            fallback_chain=("qwen3:8b", "gemma4:e4b"),
            is_voice_command=False,
            nemotron_available=True,
        )

        def mock_execution(model_name: str) -> dict[str, Any]:
            if "nemotron" in model_name:
                raise ProviderConnectionError("HTTPSConnectionPool: remote endpoint unreachable")
            return {"output": "Recuperado por Qwen"}

        res, model, attempts = router.execute_with_fallback(
            primary_model=decision.recommended_model,
            decision=decision,
            execute_fn=mock_execution,
        )

        assert model == "qwen3:8b"
        assert attempts == ["nvidia/nemotron-3-ultra-550b-a55b", "qwen3:8b"]
        assert res["output"] == "Recuperado por Qwen"

    def test_qwen_failure_cascades_to_gemma(self) -> None:
        """Si Nemotron y Qwen fallan, la ejecución pasa a Gemma 4 local."""
        router = ExperimentalRouter()
        decision = RouterDecision(
            recommended_model="nvidia/nemotron-3-ultra-550b-a55b",
            confidence=0.88,
            reason="Planning",
            task_type=TaskCategory.AGENT_PLANNING,
            estimated_complexity="high",
            fallback_chain=("qwen3:8b", "gemma4:e4b"),
            is_voice_command=False,
            nemotron_available=True,
        )

        def mock_execution(model_name: str) -> str:
            if "nemotron" in model_name:
                raise ProviderTimeoutError("Nemotron timed out")
            if "qwen" in model_name:
                raise InferenceError("Qwen Ollama socket error")
            return "Respuesta de emergencia de Gemma 4"

        res, model, attempts = router.execute_with_fallback(
            primary_model=decision.recommended_model,
            decision=decision,
            execute_fn=mock_execution,
        )

        assert model == "gemma4:e4b"
        assert attempts == ["nvidia/nemotron-3-ultra-550b-a55b", "qwen3:8b", "gemma4:e4b"]
        assert res == "Respuesta de emergencia de Gemma 4"

    def test_all_models_fail_raises_without_false_success(self) -> None:
        """Si todos los modelos fallan, se levanta InferenceError y NUNCA se declara falso éxito."""
        router = ExperimentalRouter()
        decision = RouterDecision(
            recommended_model="nvidia/nemotron-3-ultra-550b-a55b",
            confidence=0.90,
            reason="Failure test",
            task_type=TaskCategory.AGENT_PLANNING,
            estimated_complexity="high",
            fallback_chain=("qwen3:8b", "gemma4:e4b"),
            is_voice_command=False,
            nemotron_available=True,
        )

        def mock_all_fail(model_name: str) -> Any:
            raise InferenceError(f"Falla total en {model_name}")

        with pytest.raises(InferenceError) as exc_info:
            router.execute_with_fallback(
                primary_model=decision.recommended_model,
                decision=decision,
                execute_fn=mock_all_fail,
            )

        assert "Todos los modelos de la cadena de fallback fallaron" in str(exc_info.value)


# ── 6. TESTS DE UMBRAL DE CONFIANZA ──────────────────────────────────────────

class TestConfidenceThresholdSafety:
    """Verifica que el router aplique reversión a modelo seguro si confianza < threshold."""

    def test_low_confidence_reverts_to_safe_local_model(self) -> None:
        """Si la confianza calculada es menor que 0.80, revierte automáticamente a Gemma 4."""
        router = ExperimentalRouter(confidence_threshold=0.98)  # Umbral muy exigente

        # Texto que daría Qwen con confianza ~0.93
        decision = router.route_decision(user_text="Analiza este error de python traceback")

        # Al no alcanzar 0.98, debe revertir a gemma4:e4b como modelo seguro
        assert decision.recommended_model == "gemma4:e4b"
        assert "fallback seguro local" in decision.reason
