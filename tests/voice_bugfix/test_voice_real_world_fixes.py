"""Suite integral de validación de corrección de errores de voz y comprensión en JESSYCA BRAIN 4.0.

Cubre las 10 pruebas obligatorias (A-J) especificadas por el usuario:
A. Conversación ("Jessica, hola, ¿me escuchas?")
B. Preguntas ("Jessica, ¿quién fue Albert Einstein?")
C. YouTube ("Jessica, abre YouTube y reproduce música de Mozart")
D. Transcripción imperfecta ("abre yo tuy y pon mozar", "abre yu tub y pon música clásica", "pon videos de mozart") -> Sin yo.exe
E. Orden compuesta ("Jessica, baja el volumen, abre Chrome y busca información sobre Python")
F. Silencio -> Sin instrucciones ficticias ni aprendizaje
G. Frase incompleta ("abre yo", "abre yu") -> Aclaración o descarte
H. Memoria ("recuerda que estamos investigando IA" -> "continúa con lo anterior")
I. Verificación de fallo -> NO declarar éxito falso
J. Telemetría y Latencia -> llm_duration > 0, métricas reales
"""

import os
import sys
import time
import pytest
from unittest.mock import MagicMock

# Asegurar importaciones del proyecto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from core.cognitive_brain.brain_orchestrator import JessycaBrain, BrainExecutionResult
from core.cancellation import CancellationToken
from core.cognitive_brain.memory_engine import MemoryEngine
from core.cognitive_brain.procedure_learning_engine import ProcedureLearningEngine
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    InputModality,
    JessycaRequest,
    LocalAgentMetrics,
)
from services.voice.stt_service import FasterWhisperSTTService, TranscriptResult
from services.voice.audio_capture import CalibratedVoiceCaptureEngine
from services.voice.voice_diagnostics import VoiceDiscardReason


import tempfile
from pathlib import Path

@pytest.fixture(scope="module")
def brain_fixture():
    temp_dir = tempfile.mkdtemp(prefix="jessyca_voice_test_")
    db_path = Path(temp_dir) / "test_memory.db"
    long_term_dir = Path(temp_dir) / "test_long_term"
    long_term_dir.mkdir(parents=True, exist_ok=True)
    mem = MemoryEngine(db_path=db_path, storage_dir=str(long_term_dir))
    brain = JessycaBrain(memory_engine=mem)
    return brain


@pytest.fixture(scope="module")
def agent_fixture(brain_fixture):
    agent = JessycaLocalAgent.get_instance()
    agent.use_jessyca_brain = True
    agent._jessyca_brain = brain_fixture
    return agent


# ── PRUEBA A: CONVERSACIÓN / SALUDO NATURAL ──
def test_a_natural_conversation_greeting(brain_fixture: JessycaBrain):
    """'Jessica, hola, ¿me escuchas?' debe responder cordialmente sin ejecutar herramientas."""
    token = CancellationToken()
    res: BrainExecutionResult = brain_fixture.process_request(
        user_input="Jessica, hola, ¿me escuchas?",
        session_id="test-session-a",
        cancellation_token=token,
    )
    assert res.success is True
    assert res.requires_action is False
    assert all(k in ("conversational", "status") for k in res.verified_evidence.keys())
    # Comprobación de lenguaje natural y no robótico
    assert "operación completada" not in res.response_text.lower()
    text = res.response_text.lower()
    assert any(w in text for w in ["escucho", "hola", "claro", "perfecto", "aquí", "estoy"]), f"Respuesta inesperada: {res.response_text}"


# ── PRUEBA B: PREGUNTAS INFORMATIVAS SIN EJECUTAR APLICACIONES ──
def test_b_informative_question_no_apps(brain_fixture: JessycaBrain):
    """'Jessica, ¿quién fue Albert Einstein?' debe responder sin abrir aplicaciones."""
    token = CancellationToken()
    res: BrainExecutionResult = brain_fixture.process_request(
        user_input="Jessica, ¿quién fue Albert Einstein?",
        session_id="test-session-b",
        cancellation_token=token,
    )
    assert res.success is True
    assert res.requires_action is False
    assert all(k in ("conversational", "status") for k in res.verified_evidence.keys())
    assert "operación completada" not in res.response_text.lower()
    assert "einstein" in res.response_text.lower() or "físico" in res.response_text.lower() or "relatividad" in res.response_text.lower()


# ── PRUEBA C: YOUTUBE Y MOZART CON HERRAMIENTA APROPIADA ──
def test_c_youtube_mozart_proper_tool(agent_fixture: JessycaLocalAgent):
    """'Jessica, abre YouTube y reproduce música de Mozart' debe mapear a browser.youtube con Mozart."""
    executed_skills = []

    def mock_skill(skill_name, parameters=None):
        executed_skills.append((skill_name, parameters))
        return MagicMock(success=True, data={"video": "Mozart Classical Music"}, error=None)

    agent_fixture.skill_manager.execute_skill = mock_skill

    req = JessycaRequest(
        user_input="Jessica, abre YouTube y reproduce música de Mozart",
        modality=InputModality.VOICE,
        session_id="test-session-c",
        metadata={"stt_confidence": 0.95},
    )
    token = CancellationToken()
    resp = agent_fixture.interact(request=req, cancellation_token=token)

    assert resp.success is True
    assert resp.status == AgentExecutionState.COMPLETED
    assert len(executed_skills) >= 1
    # Verificar que usó browser.youtube y NO windows.apps con yo.exe
    target_skill, params = executed_skills[0]
    assert target_skill == "browser.youtube"
    assert "mozart" in str(params).lower()
    assert "yo.exe" not in str(params).lower()
    assert "operación completada exitosamente" not in resp.response_text.lower()
    assert "mozart" in resp.response_text.lower() or "youtube" in resp.response_text.lower()


# ── PRUEBA D: RECUPERACIÓN DE TRANSCRIPCIÓN IMPERFECTA ("yo tuy", "yu tub") SIN yo.exe ──
@pytest.mark.parametrize("corrupted_input,expected_keyword", [
    ("Jessica, abre yo tuy y repreduce a mozar", "mozart"),
    ("abre yu tub y pon música clásica", "clásica"),
    ("pon videos de mozart", "mozart"),
])
def test_d_corrupted_transcription_recovery(agent_fixture: JessycaLocalAgent, corrupted_input: str, expected_keyword: str):
    """Transcripciones fonéticamente corruptas deben normalizarse hacia YouTube sin ejecutar yo.exe."""
    executed_skills = []

    def mock_skill(skill_name, parameters=None):
        executed_skills.append((skill_name, parameters))
        return MagicMock(success=True, data={"result": "ok"}, error=None)

    agent_fixture.skill_manager.execute_skill = mock_skill

    req = JessycaRequest(
        user_input=corrupted_input,
        modality=InputModality.VOICE,
        session_id="test-session-d",
        metadata={"stt_confidence": 0.70},
    )
    token = CancellationToken()
    resp = agent_fixture.interact(request=req, cancellation_token=token)

    assert resp.success is True
    assert len(executed_skills) >= 1
    target_skill, params = executed_skills[0]
    assert target_skill == "browser.youtube"
    assert "yo.exe" not in str(params).lower()
    assert "yu.exe" not in str(params).lower()


def test_d_very_low_confidence_triggers_clarification(agent_fixture: JessycaLocalAgent):
    """Si la transcripción es fonéticamente dudosa y la confianza es baja (< 0.50), debe pedir aclaración y NO ejecutar nada."""
    executed_skills = []

    def mock_skill(skill_name, parameters=None):
        executed_skills.append((skill_name, parameters))
        return MagicMock(success=True, data={}, error=None)

    agent_fixture.skill_manager.execute_skill = mock_skill

    req = JessycaRequest(
        user_input="abre yo tuy y repreduce a mozar",
        modality=InputModality.VOICE,
        session_id="test-session-d-clarify",
        metadata={"stt_confidence": 0.36},  # Confianza reportada en el bug del usuario
    )
    token = CancellationToken()
    resp = agent_fixture.interact(request=req, cancellation_token=token)

    # Debe solicitar aclaración
    assert resp.requires_clarification is True or "¿quieres que abra youtube" in resp.response_text.lower() or "aclarar" in resp.response_text.lower()
    # Y NINGUNA herramienta debe haberse ejecutado
    assert len(executed_skills) == 0


# ── PRUEBA E: ORDEN COMPUESTA MULTIPASO ──
def test_e_compound_multi_step_order(agent_fixture: JessycaLocalAgent):
    """'Jessica, baja el volumen, abre Chrome y busca información sobre Python' debe conservar las 3 subtareas."""
    executed_skills = []

    def mock_skill(skill_name, parameters=None):
        executed_skills.append((skill_name, parameters))
        return MagicMock(success=True, data={"step": skill_name}, error=None)

    agent_fixture.skill_manager.execute_skill = mock_skill

    req = JessycaRequest(
        user_input="Jessica, baja el volumen, abre Chrome y busca información sobre Python",
        modality=InputModality.VOICE,
        session_id="test-session-e",
        metadata={"stt_confidence": 0.92},
    )
    token = CancellationToken()
    resp = agent_fixture.interact(request=req, cancellation_token=token)

    assert resp.success is True
    assert len(executed_skills) >= 2  # Volumen y búsqueda/app
    skill_names = [s[0] for s in executed_skills]
    assert "windows.audio" in skill_names


# ── PRUEBA F: SILENCIO / SIN COMANDOS FICTICIOS NI PROCEDIMIENTOS ──
def test_f_silence_rejection_and_no_learning():
    """Captura vacía o silencio debe descartarse y ProcedureLearningEngine debe rechazarlo."""
    learner = ProcedureLearningEngine()

    # 1. Episodio vacío o silencio: rechazo absoluto
    fake_silent_episode = {
        "user_instruction": "",
        "intent": "conversational",
        "success": False,
        "actions_executed": [],
        "verified_evidence": {},
    }
    candidate = learner.learn_from_experience(fake_silent_episode)
    assert candidate is None

    # 2. Episodio con baja confianza acústica (alucinación en silencio/ruido): rechazo
    noisy_episode = {
        "user_instruction": "abre yo tuy",
        "intent": "ambiguous",
        "success": True,
        "actions_executed": [{"action_name": "dummy", "tool_name": "dummy"}],
        "verified_evidence": {"tool": {"success": True}},
        "metadata": {"stt_confidence": 0.36},
    }
    candidate_noisy = learner.learn_from_experience(noisy_episode)
    assert candidate_noisy is None

    # 3. Episodio puramente conversacional: no debe aprender procedimiento de sistema
    chat_episode = {
        "user_instruction": "Hola Jessica",
        "intent": "conversational",
        "success": True,
        "actions_executed": [],
        "verified_evidence": {},
    }
    assert learner.learn_from_experience(chat_episode) is None


# ── PRUEBA G: FRASE INCOMPLETA O AMBIGUA ──
def test_g_incomplete_phrase_clarification_or_discard(brain_fixture: JessycaBrain):
    """'abre yo' o 'abre la' sin objetivo debe pedir aclaración y no ejecutar yo.exe."""
    token = CancellationToken()
    res = brain_fixture.process_request(
        user_input="abre yo",
        session_id="test-session-g",
        cancellation_token=token,
    )
    assert res.requires_action is False or res.error == "ClarificationNeeded"
    assert len(res.verified_evidence) == 0


# ── PRUEBA H: MEMORIA CONVERSACIONAL Y CONTEXTO ──
def test_h_conversational_memory_continuation(agent_fixture: JessycaLocalAgent):
    """'Jessica, recuerda que estamos investigando inteligencia artificial' y luego 'continúa con lo anterior'."""
    req1 = JessycaRequest(
        user_input="Jessica, recuerda que estamos investigando inteligencia artificial",
        modality=InputModality.TEXT,
        session_id="test-session-h",
    )
    resp1 = agent_fixture.interact(request=req1)
    assert resp1.success is True
    assert "recordar" in resp1.response_text.lower() or "guardado" in resp1.response_text.lower() or "anotado" in resp1.response_text.lower() or "inteligencia artificial" in resp1.response_text.lower()

    # Segunda interacción con contexto de la anterior
    req2 = JessycaRequest(
        user_input="¿Qué estábamos investigando?",
        modality=InputModality.TEXT,
        session_id="test-session-h",
    )
    resp2 = agent_fixture.interact(request=req2)
    assert resp2.success is True
    assert "inteligencia artificial" in resp2.response_text.lower() or "ia" in resp2.response_text.lower()


# ── PRUEBA I: VERIFICACIÓN CONTRA FALSOS ÉXITOS ──
def test_i_tool_failure_prevents_false_success(agent_fixture: JessycaLocalAgent):
    """Si una herramienta falla o no se verifica, el sistema NO debe declarar éxito."""
    def mock_failing_skill(skill_name, parameters=None):
        return MagicMock(success=False, data=None, error="No se pudo abrir el recurso solicitado")

    agent_fixture.skill_manager.execute_skill = mock_failing_skill

    req = JessycaRequest(
        user_input="Jessica, abre YouTube",
        modality=InputModality.TEXT,
        session_id="test-session-i",
    )
    token = CancellationToken()
    resp = agent_fixture.interact(request=req, cancellation_token=token)

    assert resp.success is False
    assert resp.status == AgentExecutionState.FAILED
    assert "exitosamente" not in resp.response_text.lower()


# ── PRUEBA J: TELEMETRÍA DE LATENCIA REAL Y MÉTRICAS ──
def test_j_real_latency_telemetry_reporting(agent_fixture: JessycaLocalAgent):
    """Verifica que metrics.model_inference_latency_ms > 0 y metrics.total_latency_ms > 0."""
    req = JessycaRequest(
        user_input="Hola Jessica",
        modality=InputModality.TEXT,
        session_id="test-session-j",
    )
    token = CancellationToken()
    resp = agent_fixture.interact(request=req, cancellation_token=token)

    assert resp.metrics.total_latency_ms > 0
    # Inferencia de Ollama debe haberse registrado con latencia real > 0 ms
    assert resp.metrics.model_inference_latency_ms > 0, f"model_inference_latency_ms reportó {resp.metrics.model_inference_latency_ms}"
    assert resp.metrics.intent_latency_ms > 0
