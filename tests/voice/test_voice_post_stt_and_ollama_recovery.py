"""Pruebas de validación post-STT: Diagnóstico Ollama, honestidad de limitaciones,
enrutamiento conversacional (YouTube / browser), estados y observabilidad.
"""

from __future__ import annotations

import io
import sys
import os
from unittest.mock import MagicMock, patch

import pytest

from core.logger import setup_logger, get_logger
from core.llm.inference import OllamaProvider, InferenceRequest
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState, InputModality, JessycaRequest
from core.local_agent.conversational_handler import ConversationalDialogueHandler
from core.routing.fast_router import FastRouter, RouteCategory
from services.voice.stt_service import get_stt_service


def test_logging_startup_no_stream_errors(capsys) -> None:
    """Verifica que el arranque y emisión del logger centralizado no emitan '--- Logging error ---'."""
    setup_logger(force=True)
    logger = get_logger("test.logging")
    # Emitir mensajes con acentos y caracteres de interfaz
    logger.info("Prueba de logging: caracteres especiales ╔═ ✓ éíóú ñ")
    logger.warning("Alerta de prueba en consola segura")

    captured = capsys.readouterr()
    assert "--- Logging error ---" not in captured.err
    assert "--- Logging error ---" not in captured.out


def test_ollama_diagnostics_and_live_or_controlled_status() -> None:
    """Diagnóstica la disponibilidad de Ollama, endpoint y modelos reales."""
    provider = OllamaProvider()
    diag = provider.get_diagnostic_status()
    assert "host" in diag
    assert "is_available" in diag
    assert "models_available" in diag

    if diag["is_available"]:
        # Si está activo, verificar inferencia directa
        req = InferenceRequest(
            prompt="¿Qué es un algoritmo en una sola frase?",
            model_name="gemma4:e4b",
            timeout_seconds=25.0,
        )
        res = provider.generate(req)
        assert res.success is True
        assert len(res.content.strip()) > 5


def test_controlled_ollama_failure_honesty() -> None:
    """Verifica que si Ollama está fuera de línea, la limitación se comunique con honestidad

    sin éxito ficticio ni frases genéricas ('Entendido...').
    """
    fake_provider = OllamaProvider(host="http://127.0.0.1:99999")  # Host no existente
    handler = ConversationalDialogueHandler(llm_provider=fake_provider)

    # Pregunta técnica que requiere LLM (no es un saludo ni concepto básico enlatado)
    resp_text = handler.generate_response(user_input="dime qué restricciones técnicas tienes en el cluster")

    assert handler._last_was_degraded is True
    assert "Entendido. ¿Puedes contarme un poco más" not in resp_text
    assert "no está disponible" in resp_text.lower() or "ollama" in resp_text.lower()

    # Integración con Core LocalAgent: verificar que el estado sea FAILED y success=False
    agent = JessycaLocalAgent.get_instance()
    agent.conversational_handler = handler

    req = JessycaRequest(
        user_input="dime qué restricciones técnicas tienes en la base de datos distribuida",
        modality=InputModality.TEXT,
    )
    res = agent.interact(req)

    assert res.success is False
    assert res.status == AgentExecutionState.FAILED
    assert res.error is not None
    assert "no está disponible" in res.spoken_text.lower() or "ollama" in res.spoken_text.lower()


def test_text_and_conversational_voice_routing_open_youtube() -> None:
    """Verifica el enrutamiento tanto por comando directo como por variación conversacional

    ('pero que abra su youtube', 'por favor abre youtube') hacia open_browser.
    """
    router = FastRouter()

    # 1. Comando directo estándar
    d1 = router.route("Abre YouTube")
    assert d1.intent == "open_browser"
    assert d1.target_skill == "browser.open"

    # 2. Variación conversacional con subjuntivo y partículas
    d2 = router.route("pero que abra su youtube")
    assert d2.intent == "open_browser"
    assert d2.target_skill == "browser.open"

    # 3. Cortesía
    d3 = router.route("por favor abre el youtube")
    assert d3.intent == "open_browser"
    assert d3.target_skill == "browser.open"


def test_ambiguous_command_requests_clarification() -> None:
    """Verifica que un verbo de acción sin objetivo válido ('abre') solicite aclaración

    en lugar de inventar acciones o caer ciegamente en general_query.
    """
    router = FastRouter()
    d = router.route("abre")
    assert d.category == RouteCategory.AMBIGUOUS
    assert d.suggested_response is not None
    assert "¿qué" in d.suggested_response.lower()


def test_consecutive_stt_requests_retain_cpu_model() -> None:
    stt = get_stt_service(device="cpu", compute_type="int8")
    stt.warmup()
    assert stt.is_ready is True
    m1_id = id(stt._model)

    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "sample_es_hola_jessica.wav")
    with open(fixture_path, "rb") as f:
        audio_bytes = f.read()

    r1 = stt.transcribe(audio_bytes)
    r2 = stt.transcribe(audio_bytes)

    assert id(stt._model) == m1_id
    assert r1.text is not None and len(r1.text) > 0
    assert r2.text is not None and len(r2.text) > 0
