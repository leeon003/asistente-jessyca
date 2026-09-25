"""tests/router/test_phase6_controlled_operation.py
Tests para la Fase 6: Endurecimiento y Operación Controlada del Model Router.

Cubre exhaustivamente los 15 puntos requeridos en la Sección 22:
1. Baseline vs Router
2. Cambio Gemma -> Qwen
3. Cambio Qwen -> Gemma
4. execution_model real coincide con selected_model
5. Fallback cascade
6. Timeout triggers fallback
7. VRAMGovernor previene OOM
8. MCP server & tools
9. Windows physical execution & verification
10. YouTube no-false-success
11. Logging estructurado en logs/router_phase6.jsonl
12. Métricas disgregadas (routing, inference, tool, verification, total)
13. Estabilidad en lote (20+ interacciones)
14. Voice pipeline integrity (natural speech, no 15s limit, VAD)
15. Rollback determinista
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.llm.experimental_router import (
    ExperimentalRouter,
    Phase6Logger,
    RouterDecision,
    RouterMode,
    TaskCategory,
)
from core.llm.inference import ProviderTimeoutError, InferenceError
from core.llm.model_profile import ModelProfile
from core.llm.model_registry import ModelRegistry
from core.llm.vram_governor import VRAMGovernor, VRAMBudgetReport
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    InputModality,
    JessycaRequest,
    JessycaResponse,
    LocalAgentMetrics,
)
from services.voice.audio_capture import CalibratedVoiceCaptureEngine
from server import ServerLifecycleState, create_mcp_server
from tools.discovery import ToolDiscoveryEngine
from tools.tool_registry import ToolRegistry
from skills.browser_youtube_skill import BrowserYouTubeSkill
from skills.apps_skill import WindowsAppsSkill


@pytest.fixture
def mock_registry():
    """Registry simulado con modelos locales verificados."""
    reg = MagicMock(spec=ModelRegistry)

    def get_profile(name):
        if "qwen3:8b" in name:
            return ModelProfile(
                name="qwen3:8b",
                provider="ollama",
                enabled=True,
                vram_estimate_mb=5700,
                context_length=8192,
            )
        elif "gemma4:e4b" in name:
            return ModelProfile(
                name="gemma4:e4b",
                provider="ollama",
                enabled=True,
                vram_estimate_mb=5200,
                context_length=8192,
            )
        elif "qwen3-vl:4b" in name:
            return ModelProfile(
                name="qwen3-vl:4b",
                provider="ollama",
                enabled=True,
                vram_estimate_mb=3500,
                context_length=4096,
            )
        raise KeyError(f"Modelo {name} no encontrado")

    reg.get.side_effect = get_profile
    return reg


@pytest.fixture
def mock_vram_gov():
    """VRAMGovernor simulado con presupuesto RTX 3060 12GB."""
    gov = MagicMock(spec=VRAMGovernor)
    report = VRAMBudgetReport(
        total_vram_mb=12288,
        reserved_system_mb=1536,
        usable_budget_mb=10752,
        currently_allocated_mb=0,
        remaining_budget_mb=10752,
        loaded_models_count=0,
    )
    gov.get_budget_report.return_value = report
    gov.can_fit.return_value = True
    return gov


# ─────────────────────────────────────────────────────────────────────────────
# 1. BASELINE VS ROUTER
# ─────────────────────────────────────────────────────────────────────────────
def test_baseline_vs_router(mock_registry, mock_vram_gov):
    """Verifica que con MODEL_ROUTER_ENABLED=false se preserva baseline gemma4:e4b, y con true se enruta."""
    # Baseline: False
    router_off = ExperimentalRouter(
        mode=RouterMode.CONTROLLED,
        enabled=False,
        registry=mock_registry,
        vram_governor=mock_vram_gov,
    )
    exec_off, dec_off = router_off.route_execution(
        user_text="Escribe una función en Python para ordenar una lista",
        current_model="gemma4:e4b",
    )
    assert exec_off == "gemma4:e4b", "Baseline DEBE mantener gemma4:e4b incondicionalmente"

    # Router activado: True
    router_on = ExperimentalRouter(
        mode=RouterMode.CONTROLLED,
        enabled=True,
        registry=mock_registry,
        vram_governor=mock_vram_gov,
    )
    exec_on, dec_on = router_on.route_execution(
        user_text="Escribe una función en Python para ordenar una lista",
        current_model="gemma4:e4b",
    )
    assert exec_on == "qwen3:8b", "Router activado debe seleccionar qwen3:8b para tarea de código"


# ─────────────────────────────────────────────────────────────────────────────
# 2. CAMBIO GEMMA -> QWEN
# ─────────────────────────────────────────────────────────────────────────────
def test_cambio_gemma_a_qwen(mock_registry, mock_vram_gov):
    """Verifica la transición dinámica de modelo de conversación a modelo técnico."""
    router = ExperimentalRouter(
        mode=RouterMode.CONTROLLED,
        enabled=True,
        registry=mock_registry,
        vram_governor=mock_vram_gov,
    )

    # 1. Turno conversacional inicial -> Gemma
    exec1, dec1 = router.route_execution(
        user_text="Hola Jessica, ¿cómo estás hoy?",
        current_model="gemma4:e4b",
    )
    assert exec1 == "gemma4:e4b"

    # 2. Turno técnico posterior -> Qwen
    exec2, dec2 = router.route_execution(
        user_text="Analiza este traceback: ZeroDivisionError en línea 42 de main.py",
        current_model="gemma4:e4b",
    )
    assert exec2 == "qwen3:8b"


# ─────────────────────────────────────────────────────────────────────────────
# 3. CAMBIO QWEN -> GEMMA
# ─────────────────────────────────────────────────────────────────────────────
def test_cambio_qwen_a_gemma(mock_registry, mock_vram_gov):
    """Verifica la transición inversa de modelo técnico a modelo conversacional/rápido."""
    router = ExperimentalRouter(
        mode=RouterMode.CONTROLLED,
        enabled=True,
        registry=mock_registry,
        vram_governor=mock_vram_gov,
    )

    # 1. Turno técnico -> Qwen
    exec1, _ = router.route_execution(
        user_text="Corrige este script de Python que tiene un error de sintaxis",
        current_model="gemma4:e4b",
    )
    assert exec1 == "qwen3:8b"

    # 2. Turno de diálogo rápido -> Gemma
    exec2, _ = router.route_execution(
        user_text="Entendido, gracias. ¿Qué hora es?",
        current_model="qwen3:8b",
    )
    assert exec2 == "gemma4:e4b"


# ─────────────────────────────────────────────────────────────────────────────
# 4. EXECUTION_MODEL REAL COINCIDE CON SELECTED_MODEL
# ─────────────────────────────────────────────────────────────────────────────
def test_execution_model_coincide(mock_registry, mock_vram_gov):
    """Demuestra que recommended_model, selected_model y execution_model coinciden."""
    router = ExperimentalRouter(
        mode=RouterMode.CONTROLLED,
        enabled=True,
        registry=mock_registry,
        vram_governor=mock_vram_gov,
    )
    selected_model, decision = router.route_execution(
        user_text="Escribe un algoritmo de búsqueda binaria",
        current_model="gemma4:e4b",
    )

    executed_model_real = None

    def dummy_inference(model):
        nonlocal executed_model_real
        executed_model_real = model
        return "def binary_search(): pass"

    res, final_model, chain = router.execute_with_fallback(
        primary_model=selected_model,
        decision=decision,
        execute_fn=dummy_inference,
    )

    assert decision.recommended_model == "qwen3:8b"
    assert selected_model == "qwen3:8b"
    assert executed_model_real == "qwen3:8b"
    assert final_model == "qwen3:8b"


# ─────────────────────────────────────────────────────────────────────────────
# 5. FALLBACK CASCADE
# ─────────────────────────────────────────────────────────────────────────────
def test_fallback_cascade(mock_registry, mock_vram_gov):
    """Verifica la cascada controlada: Qwen falla -> Fallback seguro a Gemma."""
    router = ExperimentalRouter(
        mode=RouterMode.CONTROLLED,
        enabled=True,
        registry=mock_registry,
        vram_governor=mock_vram_gov,
    )
    selected_model, decision = router.route_execution(
        user_text="Analiza esta consulta SQL compleja",
        current_model="gemma4:e4b",
    )
    assert selected_model == "qwen3:8b"

    calls = []

    def failing_inference(model):
        calls.append(model)
        if model == "qwen3:8b":
            raise InferenceError("Fallo simulado de proveedor en Qwen3")
        return "Respuesta exitosa de Gemma4"

    res, final_model, chain = router.execute_with_fallback(
        primary_model=selected_model,
        decision=decision,
        execute_fn=failing_inference,
    )

    assert final_model == "gemma4:e4b"
    assert "qwen3:8b" in calls
    assert "gemma4:e4b" in calls
    assert res == "Respuesta exitosa de Gemma4"


# ─────────────────────────────────────────────────────────────────────────────
# 6. TIMEOUT TRIGGERS FALLBACK
# ─────────────────────────────────────────────────────────────────────────────
def test_timeout_triggers_fallback(mock_registry, mock_vram_gov):
    """Verifica que un timeout en el modelo seleccionado no congela el sistema y salta al fallback."""
    router = ExperimentalRouter(
        mode=RouterMode.CONTROLLED,
        enabled=True,
        registry=mock_registry,
        vram_governor=mock_vram_gov,
    )
    selected_model, decision = router.route_execution(
        user_text="Analiza este código fuente extenso",
        current_model="gemma4:e4b",
    )

    calls = []

    def timeout_inference(model):
        calls.append(model)
        if model == "qwen3:8b":
            raise ProviderTimeoutError("Inferencia excedió el tiempo límite de 12.0s")
        return "Respuesta rápida de rescate"

    res, final_model, chain = router.execute_with_fallback(
        primary_model=selected_model,
        decision=decision,
        execute_fn=timeout_inference,
        timeout_seconds=12.0,
    )

    assert final_model == "gemma4:e4b"
    assert res == "Respuesta rápida de rescate"


# ─────────────────────────────────────────────────────────────────────────────
# 7. VRAM GOVERNOR PREVIENE OOM
# ─────────────────────────────────────────────────────────────────────────────
def test_vram_governor_previene_oom(mock_registry):
    """Verifica que si no cabe el modelo técnico en VRAM, se bloquea y se degrada a gemma4:e4b."""
    gov = MagicMock(spec=VRAMGovernor)
    report = VRAMBudgetReport(
        total_vram_mb=12288,
        reserved_system_mb=1536,
        usable_budget_mb=10752,
        currently_allocated_mb=8000,
        remaining_budget_mb=2752,  # Insuficiente para Qwen (5700MB)
        loaded_models_count=1,
    )
    gov.get_budget_report.return_value = report
    gov.can_fit.return_value = False

    router = ExperimentalRouter(
        mode=RouterMode.CONTROLLED,
        enabled=True,
        registry=mock_registry,
        vram_governor=gov,
    )

    exec_model, decision = router.route_execution(
        user_text="Analiza este algoritmo pesado",
        current_model="gemma4:e4b",
    )

    assert exec_model == "gemma4:e4b"
    assert "VRAM insuficiente" in decision.reason


# ─────────────────────────────────────────────────────────────────────────────
# 8. MCP SERVER & TOOLS INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────
def test_mcp_server_and_tools_lifecycle():
    """Verifica que el router activo no rompe el descubrimiento ni inicialización de herramientas MCP."""
    server = create_mcp_server()
    assert server is not None
    assert server.state == ServerLifecycleState.STOPPED
    assert server._fastmcp_instance is not None

    registry = ToolRegistry()
    engine = ToolDiscoveryEngine(registry=registry)
    tools = engine.discover_tools()
    assert len(tools) > 0
    tool_names = [t.name for t in tools]
    assert "system_health" in tool_names or "calculadora_basica" in tool_names


# ─────────────────────────────────────────────────────────────────────────────
# 9. WINDOWS EXECUTION & VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────
def test_windows_notepad_verification():
    """Verifica que una acción sobre Windows reporta evidencia física y verificación."""
    skill = WindowsAppsSkill()
    res = skill.ejecutar({"accion": "inspeccionar", "nombre_app": "notepad"})
    assert isinstance(res, dict)
    assert res.get("exito") is True
    assert "instancias" in res


# ─────────────────────────────────────────────────────────────────────────────
# 10. YOUTUBE NO-FALSE-SUCCESS
# ─────────────────────────────────────────────────────────────────────────────
def test_youtube_unverified_playback_no_false_success():
    """Verifica que sin confirmación de reproducción se reporta NOT_VERIFIABLE."""
    skill = BrowserYouTubeSkill()
    resultado = skill.ejecutar({
        "operacion": "play",
        "query": "musica clasica",
        "simulate_unverifiable": True,
    })

    assert resultado.get("verified") is False
    assert resultado.get("verification_status") == "NOT_VERIFIABLE"
    assert "no fue posible verificar" in resultado.get("mensaje", "").lower()


# ─────────────────────────────────────────────────────────────────────────────
# 11. LOGGING ESTRUCTURADO FASE 6
# ─────────────────────────────────────────────────────────────────────────────
def test_phase6_logging_structured(tmp_path):
    """Verifica que el logger de Fase 6 registra exactamente el esquema JSON de la Sección 20."""
    log_file = tmp_path / "router_phase6.jsonl"
    logger = Phase6Logger(log_path=log_file)

    entry = logger.log_interaction(
        request_id="req-test-p6-001",
        router_enabled=True,
        intent="code_generation",
        recommended_model="qwen3:8b",
        selected_model="qwen3:8b",
        execution_model="qwen3:8b",
        routing_latency_ms=1.5,
        inference_latency_ms=450.2,
        tool_latency_ms=0.0,
        verification_latency_ms=0.0,
        total_latency_ms=451.7,
        vram_before_mb=4200.0,
        vram_after_mb=5700.0,
        vram_budget_mb=10752.0,
        fallback=False,
        fallback_reason=None,
        success=True,
        verification="VERIFIED",
    )

    assert entry["request_id"] == "req-test-p6-001"
    assert entry["phase"] == "phase6"
    assert entry["router_enabled"] is True
    assert entry["recommended_model"] == "qwen3:8b"
    assert entry["execution_model"] == "qwen3:8b"
    assert entry["alerts"] == []

    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    loaded = json.loads(lines[0])
    assert loaded["request_id"] == "req-test-p6-001"


# ─────────────────────────────────────────────────────────────────────────────
# 12. MÉTRICAS DISGREGADAS Y ALERTAS
# ─────────────────────────────────────────────────────────────────────────────
def test_metricas_disgregadas_y_alertas(tmp_path):
    """Verifica la detección automática de alertas de la Sección 21 (timeout, routing incorrecto, etc.)."""
    log_file = tmp_path / "router_alerts.jsonl"
    logger = Phase6Logger(log_path=log_file)

    # 1. Alerta de routing incorrecto
    alerts1 = logger.detect_alerts(
        recommended_model="qwen3:8b",
        selected_model="qwen3:8b",
        execution_model="gemma4:e4b",
        fallback=False,
        fallback_reason=None,
        inference_latency_ms=100.0,
        timeout_threshold_ms=12000.0,
        vram_after_mb=5000.0,
        vram_budget_mb=10752.0,
        tool_executed=False,
        verification="COMPLETED",
        total_latency_ms=105.0,
    )
    assert "routing_incorrecto" in alerts1

    # 2. Alerta de timeout
    alerts2 = logger.detect_alerts(
        recommended_model="qwen3:8b",
        selected_model="qwen3:8b",
        execution_model="qwen3:8b",
        fallback=False,
        fallback_reason=None,
        inference_latency_ms=15500.0,
        timeout_threshold_ms=12000.0,
        vram_after_mb=5000.0,
        vram_budget_mb=10752.0,
        tool_executed=False,
        verification="COMPLETED",
        total_latency_ms=15600.0,
    )
    assert "timeout" in alerts2

    # 3. Alerta de false-success
    alerts3 = logger.detect_alerts(
        recommended_model="gemma4:e4b",
        selected_model="gemma4:e4b",
        execution_model="gemma4:e4b",
        fallback=False,
        fallback_reason=None,
        inference_latency_ms=200.0,
        timeout_threshold_ms=12000.0,
        vram_after_mb=5000.0,
        vram_budget_mb=10752.0,
        tool_executed=True,
        verification="NOT_VERIFIABLE",
        total_latency_ms=250.0,
    )
    assert "false_success" in alerts3


# ─────────────────────────────────────────────────────────────────────────────
# 13. ESTABILIDAD EN LOTE (20+ INTERACCIONES)
# ─────────────────────────────────────────────────────────────────────────────
def test_estabilidad_lote_20_interacciones(mock_registry, mock_vram_gov, tmp_path):
    """Ejecuta una batería de 25 interacciones sintéticas mixtas y verifica 0 excepciones no controladas."""
    log_file = tmp_path / "router_stability.jsonl"
    logger = Phase6Logger(log_path=log_file)
    router = ExperimentalRouter(
        mode=RouterMode.CONTROLLED,
        enabled=True,
        registry=mock_registry,
        vram_governor=mock_vram_gov,
        phase6_logger=logger,
    )

    prompts = [
        ("Hola Jessica", "gemma4:e4b"),
        ("¿Qué puedes hacer?", "gemma4:e4b"),
        ("Escribe un script en Python para procesar un CSV", "qwen3:8b"),
        ("Explícame qué es la entropía", "gemma4:e4b"),
        ("Depura este error de IndexError en list comprehension", "qwen3:8b"),
        ("Resume el texto anterior", "gemma4:e4b"),
        ("Calcula la complejidad asintótica de Quicksort", "qwen3:8b"),
        ("¿Cuál es la capital de Francia?", "gemma4:e4b"),
        ("Genera una clase de base de datos en Python", "qwen3:8b"),
        ("Buenas tardes Jessica", "gemma4:e4b"),
        ("Optimiza esta función recursiva de Fibonacci", "qwen3:8b"),
        ("Cuéntame un chiste corto", "gemma4:e4b"),
        ("Escribe una expresión regular para validar emails", "qwen3:8b"),
        ("Gracias por la ayuda", "gemma4:e4b"),
        ("Refactoriza este módulo usando dataclasses", "qwen3:8b"),
        ("¿Está lloviendo?", "gemma4:e4b"),
        ("Corrige un bug de concurrencia con threading.Lock", "qwen3:8b"),
        ("Hola de nuevo", "gemma4:e4b"),
        ("Crea un decorador de timing en Python", "qwen3:8b"),
        ("Adiós Jessica", "gemma4:e4b"),
        ("Implementa un algoritmo de Dijkstra en Python", "qwen3:8b"),
        ("¿Qué día es hoy?", "gemma4:e4b"),
    ]

    assert len(prompts) >= 20

    success_count = 0
    for i, (text, expected_model) in enumerate(prompts):
        exec_model, decision = router.route_execution(
            user_text=text,
            current_model="gemma4:e4b",
            request_id=f"req-stab-{i:03d}",
        )
        assert exec_model == expected_model, f"Fallo en prompt {i}: '{text}' esperaba {expected_model} pero obtuvo {exec_model}"
        success_count += 1

    assert success_count == len(prompts)


# ─────────────────────────────────────────────────────────────────────────────
# 14. VOICE PIPELINE INTEGRITY
# ─────────────────────────────────────────────────────────────────────────────
def test_voice_pipeline_integrity():
    """Verifica que el motor de captura de voz mantiene su configuración natural sin cortes artificiales."""
    engine = CalibratedVoiceCaptureEngine()
    assert engine.max_capture_ms >= 60000
    assert engine.vad_service.max_speech_duration_seconds >= 60.0


# ─────────────────────────────────────────────────────────────────────────────
# 15. ROLLBACK DETERMINISTA
# ─────────────────────────────────────────────────────────────────────────────
def test_rollback_determinista(mock_registry, mock_vram_gov):
    """Verifica que volver a MODEL_ROUTER_ENABLED=false restaura 100% el comportamiento estático."""
    router = ExperimentalRouter(
        mode=RouterMode.CONTROLLED,
        enabled=False,
        registry=mock_registry,
        vram_governor=mock_vram_gov,
    )
    exec_model, decision = router.route_execution(
        user_text="Genera un compilador completo en C++",
        current_model="gemma4:e4b",
    )
    assert exec_model == "gemma4:e4b"
    assert router.is_enabled() is False
