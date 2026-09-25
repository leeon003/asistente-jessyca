"""tests/router/test_phase5_controlled_routing.py
Suite de validación oficial para la FASE 5: Activación Controlada del Model Router.

Cubre exhaustivamente los 10 tests requeridos por la especificación:
1. Router desactivado (MODEL_ROUTER_ENABLED=False conserva comportamiento anterior)
2. Router activado (MODEL_ROUTER_ENABLED=True selecciona según RoutingPolicy)
3. Modelo recomendado no disponible (Fallback automático a modelo secundario/seguro)
4. Modelo genera timeout (Fallback controlado sin congelar el flujo)
5. VRAM insuficiente (VRAMGovernor previene selección de modelo incompatible)
6. Nemotron no instalado (Sin falsa disponibilidad en catálogo ni decisiones)
7. Logging estructurado (Campos de Sección 13 completos y válidos en JSONL)
8. Voice loop (Voz sin límite de 15s, VAD natural y baja latencia a Gemma 4)
9. Integración MCP (Herramientas FastMCP operan con normalidad)
10. Tool verification (No False-Success: acción no verificada nunca se reporta como exitosa)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pytest

from core.llm.exceptions import (
    InferenceError,
    ProviderTimeoutError,
)
from core.llm.experimental_router import (
    ExperimentalRouter,
    RouterDecision,
    RouterMode,
    ShadowLogger,
    TaskCategory,
)
from core.llm.model_profile import ModelProfile
from core.llm.model_registry import ModelRegistry
from core.llm.vram_governor import VRAMGovernor
from core.local_agent.conversational_handler import ConversationalDialogueHandler
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest, JessycaResponse
from services.voice.audio_capture import CalibratedVoiceCaptureEngine
from skills.browser_youtube_skill import BrowserYouTubeSkill


@pytest.fixture
def temp_log_file(tmp_path: Path) -> Path:
    return tmp_path / "test_phase5_shadow.jsonl"


# ─── TEST 1: ROUTER DESACTIVADO ──────────────────────────────────────────────
class TestPhase5RouterDisabled:
    """Test 1: Router desactivado (MODEL_ROUTER_ENABLED=False).

    Debe conservar 100% el comportamiento anterior (modelo fijo 'current_model').
    """

    def test_router_disabled_preserves_current_model(
        self, monkeypatch: pytest.MonkeyPatch, temp_log_file: Path
    ) -> None:
        monkeypatch.setenv("MODEL_ROUTER_ENABLED", "false")
        monkeypatch.setenv("MODEL_ROUTER_MODE", "controlled")
        logger_mock = ShadowLogger(log_path=temp_log_file)
        router = ExperimentalRouter(
            mode=RouterMode.CONTROLLED,
            enabled=False,
            shadow_logger=logger_mock,
        )

        exec_model, decision = router.route_execution(
            user_text="Analiza este traceback complejo de Python con error de Singleton",
            current_model="gemma4:e4b",
            request_id="req_t1_01",
        )

        # A pesar de que la recomendación técnica es Qwen3, la ejecución fija DEBE ser gemma4:e4b
        assert router.is_enabled() is False
        assert exec_model == "gemma4:e4b"
        assert decision.recommended_model == "qwen3:8b"


# ─── TEST 2: ROUTER ACTIVADO ─────────────────────────────────────────────────
class TestPhase5RouterEnabled:
    """Test 2: Router activado (MODEL_ROUTER_ENABLED=True).

    Debe seleccionar el modelo según RoutingPolicy y evidencia verificada.
    """

    def test_router_enabled_selects_qwen_for_technical(
        self, monkeypatch: pytest.MonkeyPatch, temp_log_file: Path
    ) -> None:
        monkeypatch.setenv("MODEL_ROUTER_ENABLED", "true")
        logger_mock = ShadowLogger(log_path=temp_log_file)
        router = ExperimentalRouter(
            mode=RouterMode.CONTROLLED,
            enabled=True,
            shadow_logger=logger_mock,
        )

        exec_model, decision = router.route_execution(
            user_text="Analiza este traceback de error de Python y memory leak",
            current_model="gemma4:e4b",
            request_id="req_t2_01",
        )

        assert router.is_enabled() is True
        assert exec_model == "qwen3:8b"
        assert decision.task_type == TaskCategory.TECHNICAL
        assert "qwen3:8b" in decision.recommended_model

    def test_router_enabled_selects_gemma_for_fast_interaction(
        self, monkeypatch: pytest.MonkeyPatch, temp_log_file: Path
    ) -> None:
        monkeypatch.setenv("MODEL_ROUTER_ENABLED", "true")
        logger_mock = ShadowLogger(log_path=temp_log_file)
        router = ExperimentalRouter(
            mode=RouterMode.CONTROLLED,
            enabled=True,
            shadow_logger=logger_mock,
        )

        exec_model, decision = router.route_execution(
            user_text="Jessica abre el bloc de notas",
            current_model="gemma4:e4b",
            is_voice=True,
            request_id="req_t2_02",
        )

        assert exec_model == "gemma4:e4b"
        assert decision.task_type == TaskCategory.FAST_INTERACTION


# ─── TEST 3: MODELO RECOMENDADO NO DISPONIBLE ───────────────────────────────
class TestPhase5UnavailableModelFallback:
    """Test 3: Modelo recomendado no disponible.

    Debe realizar fallback a modelo secundario/seguro sin error fatal.
    """

    def test_fallback_when_recommended_model_disabled(
        self, monkeypatch: pytest.MonkeyPatch, temp_log_file: Path
    ) -> None:
        registry = ModelRegistry.get_instance()
        # Deshabilitar temporalmente qwen3:8b en el catálogo
        qwen_prof = registry.get("qwen3:8b")
        disabled_qwen = ModelProfile(
            model_id=qwen_prof.model_id,
            name=qwen_prof.name,
            provider=qwen_prof.provider,
            capabilities=qwen_prof.capabilities,
            context_length=qwen_prof.context_length,
            max_context_length=qwen_prof.max_context_length,
            input_modalities=qwen_prof.input_modalities,
            output_modalities=qwen_prof.output_modalities,
            priority=qwen_prof.priority,
            vram_estimate_mb=qwen_prof.vram_estimate_mb,
            enabled=False,  # Marcado como no disponible
        )
        registry.register(disabled_qwen, overwrite=True)

        try:
            logger_mock = ShadowLogger(log_path=temp_log_file)
            router = ExperimentalRouter(
                mode=RouterMode.CONTROLLED,
                enabled=True,
                shadow_logger=logger_mock,
                registry=registry,
            )

            assert router.is_model_available("qwen3:8b") is False

            exec_model, decision = router.route_execution(
                user_text="Analiza este código python y busca un deadlock",
                current_model="gemma4:e4b",
                request_id="req_t3_01",
            )

            # Debe haber hecho fallback al modelo base disponible (gemma4:e4b)
            assert exec_model == "gemma4:e4b"
        finally:
            # Restaurar perfil original
            registry.register(qwen_prof, overwrite=True)


# ─── TEST 4: TIMEOUT Y FALLBACK ──────────────────────────────────────────────
class TestPhase5TimeoutFallback:
    """Test 4: Modelo genera timeout.

    Debe realizar fallback sin congelar la aplicación ni la voz.
    """

    def test_timeout_triggers_fallback_to_next_model(
        self, temp_log_file: Path
    ) -> None:
        logger_mock = ShadowLogger(log_path=temp_log_file)
        router = ExperimentalRouter(
            mode=RouterMode.CONTROLLED,
            enabled=True,
            shadow_logger=logger_mock,
        )

        decision = RouterDecision(
            recommended_model="qwen3:8b",
            confidence=0.90,
            reason="Prueba de timeout",
            task_type=TaskCategory.TECHNICAL,
            estimated_complexity="medium",
            fallback_chain=("gemma4:e4b",),
            is_voice_command=False,
            nemotron_available=False,
        )

        def mock_executor(model_name: str) -> str:
            if model_name == "qwen3:8b":
                raise ProviderTimeoutError(provider_name="ollama", timeout_seconds=12.0)
            return f"Respuesta exitosa de {model_name}"

        result, successful_model, attempts = router.execute_with_fallback(
            primary_model="qwen3:8b",
            decision=decision,
            execute_fn=mock_executor,
            timeout_seconds=12.0,
        )

        assert successful_model == "gemma4:e4b"
        assert "gemma4:e4b" in result
        assert attempts == ["qwen3:8b", "gemma4:e4b"]


# ─── TEST 5: VRAM INSUFICIENTE ───────────────────────────────────────────────
class TestPhase5VRAMGovernorConstraint:
    """Test 5: VRAM insuficiente.

    Debe evitar seleccionar un modelo incompatible con la memoria restante.
    """

    def test_vram_governor_blocks_incompatible_model(
        self, temp_log_file: Path
    ) -> None:
        # Simular gobernador de VRAM con presupuesto muy bajo o saturado
        governor = VRAMGovernor(total_vram_mb=6000, reserved_system_mb=2000)
        # usable_budget = 4000 MB. Qwen3 requiere 5700 MB -> NO CABE
        logger_mock = ShadowLogger(log_path=temp_log_file)
        router = ExperimentalRouter(
            mode=RouterMode.CONTROLLED,
            enabled=True,
            shadow_logger=logger_mock,
            vram_governor=governor,
        )

        can_fit, reason, report = router.check_vram_capacity("qwen3:8b")
        assert can_fit is False
        assert "VRAM insuficiente" in reason

        # Al solicitar ejecución para tarea técnica (que requeriría Qwen3)
        exec_model, decision = router.route_execution(
            user_text="Analiza este código de python con recursión infinita",
            current_model="gemma4:e4b",
            request_id="req_t5_01",
        )

        # Debe degradar a gemma4:e4b para evitar OOM
        assert exec_model == "gemma4:e4b"


# ─── TEST 6: NEMOTRON NO INSTALADO ───────────────────────────────────────────
class TestPhase5NemotronNotInstalled:
    """Test 6: Nemotron no instalado.

    No debe producir falsa disponibilidad ni inventar acceso remoto si está deshabilitado.
    """

    def test_nemotron_strictly_unavailable_by_default(
        self, monkeypatch: pytest.MonkeyPatch, temp_log_file: Path
    ) -> None:
        monkeypatch.setenv("NEMOTRON_ENABLED", "false")
        logger_mock = ShadowLogger(log_path=temp_log_file)
        router = ExperimentalRouter(
            mode=RouterMode.CONTROLLED,
            enabled=True,
            shadow_logger=logger_mock,
        )

        assert router.is_nemotron_enabled() is False
        assert router.is_model_available("nvidia/nemotron-3-ultra-550b-a55b") is False

        exec_model, decision = router.route_execution(
            user_text="Analiza las contradicciones complejas entre este diseño de arquitectura y la concurrencia",
            current_model="gemma4:e4b",
            request_id="req_t6_01",
        )

        assert decision.nemotron_available is False
        assert "nemotron" not in exec_model.lower()
        # Se asigna a Qwen3 local como alternativa de razonamiento local
        assert exec_model == "qwen3:8b"


# ─── TEST 7: LOGGING ESTRUCTURADO ────────────────────────────────────────────
class TestPhase5StructuredLogging:
    """Test 7: Logging.

    Cada decisión debe generar un registro estructurado válido con los campos de Sección 13.
    """

    def test_log_decision_contains_all_section_13_fields(
        self, temp_log_file: Path
    ) -> None:
        logger_mock = ShadowLogger(log_path=temp_log_file)
        router = ExperimentalRouter(
            mode=RouterMode.CONTROLLED,
            enabled=True,
            shadow_logger=logger_mock,
        )

        exec_model, decision = router.route_execution(
            user_text="Analiza el rendimiento del recolector de basura",
            current_model="gemma4:e4b",
            is_voice=False,
            request_id="req_t7_struct_01",
        )

        assert temp_log_file.exists()
        lines = temp_log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1

        record = json.loads(lines[-1])
        # Validación de campos conceptuales de Sección 13:
        expected_fields = [
            "timestamp",
            "request_id",
            "input_type",
            "intent",
            "current_model",
            "recommended_model",
            "selected_model",
            "routing_reason",
            "policy",
            "vram_state",
            "latency_ms",
            "success",
            "fallback",
            "error",
            "verification",
        ]
        for field in expected_fields:
            assert field in record, f"Falta campo obligatorio '{field}' en log"

        assert record["request_id"] == "req_t7_struct_01"
        assert record["selected_model"] == exec_model


# ─── TEST 8: VOICE LOOP NATURAL Y SIN CORTES ARTIFICIALES ────────────────────
class TestPhase5VoiceLoopIntegrity:
    """Test 8: Voice loop.

    La activación del Router no debe romper el flujo de voz ni imponer cortes fijos de 15s.
    """

    def test_voice_capture_allows_natural_speech_duration(self) -> None:
        engine = CalibratedVoiceCaptureEngine()
        # Debe permitir captura prolongada (300 segundos = 5 minutos) gobernada por VAD
        assert engine.max_capture_ms >= 60000
        assert engine.vad_service.max_speech_duration_seconds >= 60.0

    def test_voice_input_prioritizes_low_latency_gemma(
        self, temp_log_file: Path
    ) -> None:
        logger_mock = ShadowLogger(log_path=temp_log_file)
        router = ExperimentalRouter(
            mode=RouterMode.CONTROLLED,
            enabled=True,
            shadow_logger=logger_mock,
        )

        # Entrada proveniente de voz
        exec_model, decision = router.route_execution(
            user_text="Jessica qué hora es",
            current_model="gemma4:e4b",
            is_voice=True,
            request_id="req_t8_voice_01",
        )

        # Debe priorizar Gemma 4 para latencia conversacional mínima (<400ms)
        assert exec_model == "gemma4:e4b"
        assert decision.is_voice_command is True


# ─── TEST 9: INTEGRACIÓN MCP PRESERVADA ───────────────────────────────────────
class TestPhase5MCPIntegration:
    """Test 9: MCP.

    La activación del Router no debe romper las herramientas MCP.
    """

    def test_mcp_server_and_tools_initialization(self) -> None:
        from server import ServerLifecycleState, create_mcp_server
        from tools.discovery import ToolDiscoveryEngine
        from tools.tool_registry import ToolRegistry

        server = create_mcp_server()
        assert server is not None
        assert server.state == ServerLifecycleState.STOPPED
        assert server._fastmcp_instance is not None

        # Verificar que el registro de herramientas MCP y descubrimiento operan normalmente
        registry = ToolRegistry()
        engine = ToolDiscoveryEngine(registry=registry)
        tools = engine.discover_tools()
        assert len(tools) > 0
        tool_names = [t.name for t in tools]
        assert "system_health" in tool_names or "calculadora_basica" in tool_names


# ─── TEST 10: TOOL VERIFICATION (NO FALSE-SUCCESS) ───────────────────────────
class TestPhase5ToolVerificationNoFalseSuccess:
    """Test 10: Tool verification.

    Una acción no verificada NUNCA debe reportarse como exitosa.
    """

    def test_youtube_unverified_playback_never_claims_success(self) -> None:
        skill = BrowserYouTubeSkill()
        # Simular fallo en verificación de reproducción en YouTube
        resultado = skill.ejecutar({
            "operacion": "play",
            "query": "musica clasica",
            "simulate_unverifiable": True,
        })

        # Regla fundamental: Si no se pudo verificar, verified debe ser False
        assert resultado.get("verified") is False
        assert resultado.get("verification_status") == "NOT_VERIFIABLE"
        # El mensaje nunca debe engañar diciendo que se está reproduciendo con éxito
        assert "no fue posible verificar" in resultado.get("mensaje", "").lower()

    def test_youtube_simulated_play_failure(self) -> None:
        skill = BrowserYouTubeSkill()
        resultado = skill.ejecutar({
            "operacion": "play",
            "query": "rock instrumental",
            "simulated_play_failure": True,
        })

        assert resultado.get("exito") is False
        assert resultado.get("verified") is False
        assert resultado.get("error_code") == "PLAYBACK_FAILED"
        assert "no pude iniciar la reproducción" in resultado.get("mensaje", "").lower()
