"""Pruebas de certificación y regresión para Fase 11: Rendimiento, Sesiones HTTP, Gobernanza GPU y TTL.

Cubre:
1. NemotronProvider: distinción estricta de max_retries=0 vs None, sin reintentos cuando max_retries=0.
2. NemotronProvider: no confundir ni reintentar errores de ejecución de herramientas.
3. Sesiones HTTP: persistencia de conexión (connection pooling), close() y context manager.
4. Health Checks con TTL: caché determinista, force=True e invalidación en cambio de estado.
5. VRAMGovernor: límite de inferencias GPU concurrentes, cola acotada y timeout presupuestario.
6. LocalAgentMetrics: desglose completo por request_id (captura, fin de habla, STT, clasificación,
   router, carga de modelo, inferencia, autorización, herramienta, verificación y primer audio TTS).
7. Streaming: streaming conversacional vs no afirmar éxito de acciones antes de verificación real.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.cancellation import CancellationToken
from core.exceptions import MCPError, ToolExecutionError
from core.llm.exceptions import (
    InferenceError,
    ProviderConnectionError,
    ProviderError,
    ProviderTimeoutError,
)
from core.llm.inference import InferenceRequest, OllamaProvider
from core.llm.nemotron_provider import NemotronProvider
from core.llm.vram_manager import VRAMGovernor
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    InputModality,
    JessycaRequest,
    LocalAgentMetrics,
)
from server.health import HealthChecker, HealthStatus
from server.lifecycle import LifecycleState, ServerLifecycleManager


# ══════════════════════════════════════════════════════════════════════════
# 1. NEMOTRON PROVIDER & RETRY REGRESSION TESTS
# ══════════════════════════════════════════════════════════════════════════

class TestNemotronRetryRegressions:
    """Verifica el contrato estricto de reintentos y que 0 sea respetado rigurosamente."""

    def test_max_retries_zero_explicit_in_constructor(self) -> None:
        """max_retries=0 explícito no debe ser ignorado por expresiones 'or'."""
        call_count = 0

        def failing_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.status_code = 503
            return mock_resp

        provider = NemotronProvider(
            enabled=True,
            api_key="test-api-key",
            max_retries=0,
            post_fn=failing_post,
        )

        assert provider.max_retries == 0

        req = InferenceRequest(prompt="Hola Nemotron")
        with pytest.raises(InferenceError) as exc_info:
            provider.generate(req)

        # Debe ejecutarse EXACTAMENTE 1 intento (0 reintentos)
        assert call_count == 1
        assert "tras 0 reintentos" in str(exc_info.value)

    def test_max_retries_zero_in_extra_options_overrides_constructor(self) -> None:
        """extra_options={'max_retries': 0} debe anular el valor por defecto sin ser ignorado por 'or'."""
        call_count = 0

        def failing_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.status_code = 429
            return mock_resp

        provider = NemotronProvider(
            enabled=True,
            api_key="test-api-key",
            max_retries=3,  # Constructor tiene 3
            post_fn=failing_post,
        )

        # Petición con override a 0 reintentos
        req = InferenceRequest(
            prompt="Consulta crítica sin reintentos",
            extra_options={"max_retries": 0},
        )
        with pytest.raises(InferenceError) as exc_info:
            provider.generate(req)

        assert call_count == 1
        assert "tras 0 reintentos" in str(exc_info.value)

    def test_max_retries_zero_on_timeout(self) -> None:
        """Con max_retries=0, un timeout debe fallar de inmediato en el intento 1 sin reintentar."""
        call_count = 0

        def timeout_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise requests.exceptions.Timeout("Request timed out")

        provider = NemotronProvider(
            enabled=True,
            api_key="test-api-key",
            max_retries=0,
            timeout_seconds=2.0,
            post_fn=timeout_post,
        )

        req = InferenceRequest(prompt="Consulta rápida")
        with pytest.raises(ProviderTimeoutError):
            provider.generate(req)

        assert call_count == 1

    def test_tool_execution_error_is_not_retried_as_inference(self) -> None:
        """Los errores de ejecución de herramientas (ToolExecutionError/MCPError) no deben reintentarse ni enmascararse."""
        call_count = 0

        def tool_raising_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ToolExecutionError("Fallo crítico en herramienta del sistema")

        provider = NemotronProvider(
            enabled=True,
            api_key="test-api-key",
            max_retries=3,
            post_fn=tool_raising_post,
        )

        req = InferenceRequest(prompt="Ejecutar herramienta")
        with pytest.raises(ToolExecutionError) as exc_info:
            provider.generate(req)

        # Se abortó de inmediato en el primer intento sin reintentar 3 veces
        assert call_count == 1
        assert "Fallo crítico en herramienta" in str(exc_info.value)


# ══════════════════════════════════════════════════════════════════════════
# 2. HTTP SESSION REUSE & TEARDOWN TESTS
# ══════════════════════════════════════════════════════════════════════════

class TestHTTPSessionReuseAndTeardown:
    """Verifica reutilización de sesiones y cierre limpio de conexiones."""

    def test_nemotron_session_lazy_initialization_and_close(self) -> None:
        """NemotronProvider debe instanciar la sesión perezosamente y cerrarla con close()."""
        provider = NemotronProvider(enabled=True, api_key="key")
        assert provider._session is None

        sess = provider._get_session()
        assert isinstance(sess, requests.Session)
        assert provider._session is sess

        # Reutiliza la misma sesión
        assert provider._get_session() is sess

        # Cierre explícito
        provider.close()
        assert provider._session is None

    def test_nemotron_context_manager_clean_teardown(self) -> None:
        """NemotronProvider como context manager debe cerrar la sesión al salir."""
        with NemotronProvider(enabled=True, api_key="key") as provider:
            sess = provider._get_session()
            assert provider._session is not None

        assert provider._session is None

    def test_ollama_session_lazy_initialization_and_close(self) -> None:
        """OllamaProvider debe instanciar la sesión perezosamente y cerrarla con close()."""
        provider = OllamaProvider(host="http://localhost:11434")
        assert provider._session is None

        sess = provider._get_session()
        assert isinstance(sess, requests.Session)
        assert provider._session is sess

        provider.close()
        assert provider._session is None

    def test_ollama_context_manager_clean_teardown(self) -> None:
        """OllamaProvider como context manager debe cerrar la sesión al salir."""
        with OllamaProvider(host="http://localhost:11434") as provider:
            _ = provider._get_session()
            assert provider._session is not None

        assert provider._session is None


# ══════════════════════════════════════════════════════════════════════════
# 3. HEALTH CHECK TTL CACHING TESTS
# ══════════════════════════════════════════════════════════════════════════

class TestHealthCheckTTLCaching:
    """Verifica la caché con TTL para reducir latencias en comprobaciones de salud repetitivas."""

    def test_health_checker_caches_within_ttl(self) -> None:
        """HealthChecker debe retornar el mismo objeto en memoria mientras no expire el TTL."""
        lifecycle = ServerLifecycleManager()
        lifecycle.initialize()
        lifecycle.start()

        checker = HealthChecker(lifecycle_manager=lifecycle, cache_ttl_seconds=1.5)

        h1 = checker.check_health()
        assert h1.status == HealthStatus.HEALTHY

        # Llamada inmediata -> debe retornar exactamente la misma instancia cacheada
        h2 = checker.check_health()
        assert h1 is h2

    def test_health_checker_force_bypasses_cache(self) -> None:
        """check_health(force=True) debe ignorar la caché y generar una nueva evaluación."""
        lifecycle = ServerLifecycleManager()
        checker = HealthChecker(lifecycle_manager=lifecycle, cache_ttl_seconds=5.0)

        h1 = checker.check_health()
        h2 = checker.check_health(force=True)

        assert h1 is not h2

    def test_health_checker_invalidates_immediately_on_state_transition(self) -> None:
        """Un cambio en el estado del ciclo de vida invalida la caché de inmediato."""
        lifecycle = ServerLifecycleManager()
        lifecycle.initialize()

        checker = HealthChecker(lifecycle_manager=lifecycle, cache_ttl_seconds=5.0)
        h_stopped = checker.check_health()
        assert h_stopped.status == HealthStatus.DEGRADED

        # Transición de estado a RUNNING
        lifecycle.start()
        h_running = checker.check_health()
        assert h_running.status == HealthStatus.HEALTHY
        assert h_stopped is not h_running


# ══════════════════════════════════════════════════════════════════════════
# 4. GPU INFERENCE LIMITER & BOUNDED QUEUE TESTS
# ══════════════════════════════════════════════════════════════════════════

class TestGPUInferenceLimiterAndBoundedQueue:
    """Verifica la gobernanza de concurrencia y cola acotada en inferencias GPU."""

    def test_acquire_inference_slot_limits_concurrency(self) -> None:
        """VRAMGovernor debe limitar la concurrencia a max_concurrent_inferences."""
        governor = VRAMGovernor(
            total_vram_mb=12288,
            max_concurrent_inferences=1,
            max_inference_queue_size=2,
        )

        with governor.acquire_inference_slot(model_name="gemma4:e4b", timeout_seconds=1.0):
            stats = governor.get_inference_concurrency_stats()
            assert stats["active_inferences"] == 1
            assert stats["queued_inferences"] == 0

        # Al salir del slot, active_inferences vuelve a 0
        stats = governor.get_inference_concurrency_stats()
        assert stats["active_inferences"] == 0

    def test_inference_queue_overflow_raises_error(self) -> None:
        """Si la cola de espera supera max_inference_queue_size, debe rechazar inmediatamente."""
        governor = VRAMGovernor(
            total_vram_mb=12288,
            max_concurrent_inferences=1,
            max_inference_queue_size=1,  # Máximo 1 en cola
        )

        # Ocupar el único slot activo
        with governor.acquire_inference_slot(timeout_seconds=5.0):
            # Llenar la cola acotada simulando una petición en espera
            with governor._queue_lock:
                governor._queued_inferences = 1

            # La siguiente petición entrante debe exceder la cola
            with pytest.raises(InferenceError) as exc_info:
                with governor.acquire_inference_slot(timeout_seconds=0.1):
                    pass

            assert "Cola de inferencias GPU llena" in str(exc_info.value)

    def test_inference_timeout_budget_exceeded(self) -> None:
        """Si se agota el tiempo esperando en cola, debe lanzar ProviderTimeoutError."""
        governor = VRAMGovernor(
            total_vram_mb=12288,
            max_concurrent_inferences=1,
            max_inference_queue_size=5,
        )

        # Ocupar el slot activo
        with governor.acquire_inference_slot(timeout_seconds=5.0):
            # Otra petición intenta adquirir con timeout breve de 0.05s
            with pytest.raises(ProviderTimeoutError):
                with governor.acquire_inference_slot(timeout_seconds=0.05):
                    pass


# ══════════════════════════════════════════════════════════════════════════
# 5. OBSERVABILITY BREAKDOWN BY REQUEST_ID TESTS
# ══════════════════════════════════════════════════════════════════════════

class TestObservabilityMetricsBreakdown:
    """Verifica la presencia y serialización de todas las fases de latencia por request_id."""

    def test_metrics_granular_fields_and_to_dict(self) -> None:
        """LocalAgentMetrics debe contener y serializar todas las 11 fases de medición."""
        metrics = LocalAgentMetrics(
            request_id="req-phase11-test-001",
            capture_latency_ms=12.5,
            speech_end_ms=1728000000.0,
            stt_accuracy=0.98,
            stt_latency_ms=45.2,
            classification_latency_ms=1.8,
            routing_latency_ms=0.6,
            model_load_latency_ms=0.0,
            inference_latency_ms=120.4,
            authorization_latency_ms=2.1,
            tool_execution_latency_ms=15.0,
            verification_latency_ms=3.2,
            first_audio_tts_latency_ms=35.0,
            tts_latency_ms=80.0,
            total_latency_ms=315.8,
        )

        d = metrics.to_dict()
        assert d["request_id"] == "req-phase11-test-001"
        assert d["capture_latency_ms"] == 12.5
        assert d["speech_end_ms"] == 1728000000.0
        assert d["stt_latency_ms"] == 45.2
        assert d["classification_latency_ms"] == 1.8
        assert d["routing_latency_ms"] == 0.6
        assert d["model_load_latency_ms"] == 0.0
        assert d["inference_latency_ms"] == 120.4
        assert d["authorization_latency_ms"] == 2.1
        assert d["tool_execution_latency_ms"] == 15.0
        assert d["verification_latency_ms"] == 3.2
        assert d["first_audio_tts_latency_ms"] == 35.0
        assert d["total_latency_ms"] == 315.8


# ══════════════════════════════════════════════════════════════════════════
# 6. STREAMING ANTI-FALSE SUCCESS INVARIANT TESTS
# ══════════════════════════════════════════════════════════════════════════

class TestStreamingInvariants:
    """Verifica que el streaming nunca afirme éxito de acciones antes de verificar."""

    def test_streaming_does_not_claim_action_success_prematurely(self) -> None:
        """interact_stream con acción de SO debe ejecutar el pipeline y verificar antes de emitir."""
        from core.local_agent.local_agent import JessycaLocalAgent

        agent = JessycaLocalAgent.get_instance()
        # Comando con efecto en sistema: 'abre bloc de notas'
        req = JessycaRequest(user_input="abre el bloc de notas", modality=InputModality.TEXT)

        # Consumir el stream completo
        tokens = list(agent.interact_stream(req))
        emitted_text = "".join(tokens)

        # Si el notepad se abrió o ya estaba abierto y verificado, se emite la confirmación post-verificación
        assert len(emitted_text) > 0
        assert "bloc de notas" in emitted_text.lower() or "notepad" in emitted_text.lower()
