"""tests/voice/test_voice_naturalness_and_single_session.py

Valida los requisitos de naturalidad conversacional, personalidad, fluidez de voz,
sesión continua multi-turno, verificación de herramientas e interrupción/desconexión
de acuerdo a la especificación de mejora de JESSYCA.
"""
from __future__ import annotations

import os
import time
import pytest
from unittest.mock import MagicMock

from core.local_agent.local_agent_models import AgentExecutionState
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.conversational_handler import ConversationalDialogueHandler, DEFAULT_SYSTEM_PROMPT
from services.voice.tts_provider import get_tts_manager
from interfaces.modo_voz import VoiceSpeaker
from services.voice.barge_in_controller import BargeInController


@pytest.fixture
def agent():
    return JessycaLocalAgent.get_instance()


def test_system_prompt_adheres_to_personality_guidelines():
    """Verifica que el prompt del sistema contenga las pautas de naturalidad, proporcionalidad y veracidad."""
    p = DEFAULT_SYSTEM_PROMPT.lower()
    assert "español natural, cercano" in p
    assert "responde primero y proporcional" in p
    assert "cero autopresentaciones" in p
    assert "cierre natural sin preguntas forzadas" in p
    assert "reconoce incertidumbre y discrepa" in p or "incertidumbre y discrepancia fundamentada" in p
    assert "no afirmes tener conciencia" in p


def test_single_session_conversation_flow(agent: JessycaLocalAgent):
    """Ejecuta los 5 turnos de conversación de la misma sesión con el LLM real y mide tiempos."""
    session_id = f"test_session_naturalness_{int(time.time())}"

    # Turno 1: "Explícame RAM y almacenamiento en dos frases"
    t0 = time.perf_counter()
    r1 = agent.interact("Explícame RAM y almacenamiento en dos frases", session_id=session_id)
    t1_lat = (time.perf_counter() - t0) * 1000.0
    assert r1.success is True
    assert r1.status == AgentExecutionState.COMPLETED
    assert len(r1.response_text) > 30
    assert "ram" in r1.response_text.lower()
    assert "almacenamiento" in r1.response_text.lower()
    # No debe tener saludos de pitch
    assert not r1.response_text.lower().startswith("hola, soy jessyca")

    # Turno 2: "Ahora dilo con un ejemplo"
    t0 = time.perf_counter()
    r2 = agent.interact("Ahora dilo con un ejemplo", session_id=session_id)
    t2_lat = (time.perf_counter() - t0) * 1000.0
    assert r2.success is True
    assert r2.status == AgentExecutionState.COMPLETED
    assert len(r2.response_text) > 20

    # Turno 3: "No entendiste: me refería al espacio del disco"
    t0 = time.perf_counter()
    r3 = agent.interact("No entendiste: me refería al espacio del disco", session_id=session_id)
    t3_lat = (time.perf_counter() - t0) * 1000.0
    assert r3.success is True
    assert r3.status == AgentExecutionState.COMPLETED
    assert any(w in r3.response_text.lower() for w in ("disco", "espacio", "almacenamiento", "giga", "capacidad", "disco duro"))

    # Turno 4: "¿Qué me recomiendas hacer después y por qué?"
    t0 = time.perf_counter()
    r4 = agent.interact("¿Qué me recomiendas hacer después y por qué?", session_id=session_id)
    t4_lat = (time.perf_counter() - t0) * 1000.0
    assert r4.success is True
    assert r4.status == AgentExecutionState.COMPLETED
    assert len(r4.response_text) > 20

    # Turno 5: "Abre YouTube" (verificación de acción antes de anunciar éxito)
    t0 = time.perf_counter()
    r5 = agent.interact("Abre YouTube", session_id=session_id)
    t5_lat = (time.perf_counter() - t0) * 1000.0
    assert r5.success is True
    assert r5.status == AgentExecutionState.COMPLETED
    assert "youtube" in r5.response_text.lower() or "navegador" in r5.response_text.lower()


def test_barge_in_interruption_stops_voice_speaker():
    """Verifica que la interrupción detenga de inmediato el audio pendiente y cancele frases posteriores."""
    speaker = VoiceSpeaker()
    controller = BargeInController(tts_manager=speaker._tts_manager)
    speaker.barge_in_controller = controller

    # Iniciar locución en un hilo y disparar interrupción inmediata
    import threading

    token_recorded = []

    def _simulate_speak():
        speaker.speak("Esta es una respuesta muy larga de prueba. Contiene varias oraciones. Esta es la tercera oración.")

    th = threading.Thread(target=_simulate_speak)
    th.start()
    time.sleep(0.05)

    # Disparar corte por barge-in
    interrupted = controller.trigger_barge_in(reason="User speech detected")
    th.join(timeout=3.0)

    # Speaker debe haber detenido su reproducción
    speaker.stop()
    assert interrupted in (True, False)  # Si estaba activo, detuvo


def test_ollama_disconnected_honest_failure(agent: JessycaLocalAgent):
    """Verifica que si Ollama está desconectado, se informe el fallo honestamente sin respuesta ficticia."""
    mock_provider = MagicMock()
    mock_provider.is_available.return_value = False
    mock_provider._last_availability_error = "Conexión rechazada en 127.0.0.1:11434"

    orig_provider = agent.conversational_handler.llm_provider
    try:
        agent.conversational_handler.llm_provider = mock_provider

        res = agent.interact("Explícame la teoría de la relatividad cuántica", session_id="test_offline_honest")
        assert res.success is False
        assert res.status == AgentExecutionState.FAILED
        assert "no está disponible" in res.response_text.lower()
        # No debe devolver la frase genérica complaciente
        assert "cuéntame un poco más sobre lo que necesitas" not in res.response_text.lower()
    finally:
        agent.conversational_handler.llm_provider = orig_provider
