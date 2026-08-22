"""Suite de Pruebas de Certificación para Aclaración Conversacional y Seguimiento (Fase 53).

Valida:
1. test_missing_parameter: Intención incompleta ("Abre una aplicación" -> "Claro. ¿Cuál aplicación quieres abrir?").
2. test_multi_parameter_followup: Tarea multi-parámetro ("Pon una alarma" -> "¿Para qué hora?" -> "¿Para qué día?").
3. test_ambiguous_request: Desambiguación sin adivinar ("Abre notas" -> "¿Te refieres al Bloc de notas...?").
4. test_low_confidence_clarification: Compuerta de calidad STT para baja confianza o audio distorsionado ("pre calculadora").
5. test_partial_request: Detección de órdenes truncadas ("dame un informe de lo...").
6. test_confirmation_yes: Flujo de confirmación afirmativa contextual ("Sí").
7. test_confirmation_no: Flujo de confirmación cancelada ("No").
8. test_yes_without_pending_confirmation: Inmunidad a falsas confirmaciones ("Sí" sin confirmación previa).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.local_agent import (
    AgentExecutionState,
    JessycaLocalAgent,
    JessycaRequest,
)


@pytest.fixture(autouse=True)
def reset_local_agent():
    agent = JessycaLocalAgent.get_instance()
    agent.reset()
    yield
    agent.reset()


# ── 1. INTENCIÓN INCOMPLETA ──


def test_missing_parameter():
    """Valida: 'Abre una aplicación' -> 'Claro. ¿Cuál aplicación quieres abrir?'."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "sess_missing_param"

    r = agent.interact(JessycaRequest(user_input="Abre una aplicación", session_id=session_id))
    assert r.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert r.requires_clarification is True
    assert "Cuál aplicación quieres abrir" in r.response_text or "Qué aplicación" in r.response_text


# ── 2. TAREA MULTI-PARÁMETRO CON SLOT-FILLING ──


def test_multi_parameter_followup():
    """Valida: 'Pon una alarma' -> '¿Para qué hora?' -> 'A las ocho' -> '¿Para qué día?' -> 'Para mañana'."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "sess_alarm_slots"

    # Turno 1: Iniciar tarea sin parámetros
    r1 = agent.interact(JessycaRequest(user_input="Pon una alarma", session_id=session_id))
    assert r1.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert "¿Para qué hora?" in r1.response_text

    # Turno 2: Entregar primer parámetro (hora)
    r2 = agent.interact(JessycaRequest(user_input="A las ocho", session_id=session_id))
    assert r2.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert "¿Para qué día?" in r2.response_text

    # Turno 3: Entregar segundo parámetro (día)
    r3 = agent.interact(JessycaRequest(user_input="Para mañana", session_id=session_id))
    assert r3.success is True
    assert r3.status == AgentExecutionState.COMPLETED
    assert "8:00" in r3.response_text
    assert "mañana" in r3.response_text.lower()


# ── 3. DESAMBIGUACIÓN CONTEXTUAL ──


def test_ambiguous_request():
    """Valida: 'Abre notas' -> Pregunta aclaratoria sin adivinar."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "sess_ambiguous_notes"

    r = agent.interact(JessycaRequest(user_input="Abre notas", session_id=session_id))
    assert r.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert r.requires_clarification is True
    assert "Bloc de notas" in r.response_text


# ── 4. COMPUERTA DE CALIDAD ANTE BAJA CONFIANZA O AUDIO DUDOSO ──


def test_low_confidence_clarification():
    """Valida que transcripciones truncadas o dudosas ('pre calculadora') no ejecuten y soliciten repetición."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "sess_low_confidence"

    r = agent.interact(JessycaRequest(user_input="pre calculadora", session_id=session_id))
    assert r.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert r.requires_clarification is True
    assert "No te entendí bien. ¿Puedes repetirlo?" in r.response_text


# ── 5. DETECCIÓN DE FRASE TRUNCADA / PARCIAL ──


def test_partial_request():
    """Valida que frases que terminan abruptamente ('dame un informe de lo...') soliciten tema."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "sess_partial_speech"

    r = agent.interact(JessycaRequest(user_input="Jessica dame un informe de lo...", session_id=session_id))
    assert r.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert r.requires_clarification is True
    assert "tema" in r.response_text.lower()


# ── 6. CONFIRMACIÓN: RESPUESTA AFIRMATIVA ('SÍ') ──


def test_confirmation_yes():
    """Valida que 'Sí' ejecute la acción sensible si existe confirmación pendiente."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "sess_confirm_yes"

    with patch("os.remove"), patch("os.path.exists", return_value=True):
        # Turno 1: Orden sensible
        r1 = agent.interact(JessycaRequest(user_input="Elimina el archivo temporal", session_id=session_id))
        assert r1.requires_confirmation is True
        assert r1.status == AgentExecutionState.AWAITING_CONFIRMATION

        # Turno 2: Usuario confirma con "Sí"
        r2 = agent.interact(JessycaRequest(user_input="Sí", session_id=session_id))
        assert r2.success is True
        assert r2.status == AgentExecutionState.COMPLETED
        assert r2.intent == "delete_file"


# ── 7. CONFIRMACIÓN: RESPUESTA NEGATIVA ('NO') ──


def test_confirmation_no():
    """Valida que 'No' cancele la acción sensible pendiente limpiamente."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "sess_confirm_no"

    # Turno 1: Orden sensible
    r1 = agent.interact(JessycaRequest(user_input="Elimina el archivo temporal", session_id=session_id))
    assert r1.requires_confirmation is True

    # Turno 2: Usuario rechaza con "No"
    r2 = agent.interact(JessycaRequest(user_input="No", session_id=session_id))
    assert r2.success is True
    assert r2.intent == "cancel_task"
    assert "cancelada" in r2.response_text.lower()


# ── 8. NO CONFUSIÓN: 'SÍ' SIN CONFIRMACIÓN PENDIENTE ──


def test_yes_without_pending_confirmation():
    """Valida que 'Sí' en frío no ejecute ninguna acción sensible y se trate como diálogo normal."""
    agent = JessycaLocalAgent.get_instance()
    session_id = "sess_yes_cold"

    r = agent.interact(JessycaRequest(user_input="Sí", session_id=session_id))
    assert r.success is True
    assert r.status == AgentExecutionState.COMPLETED
    assert r.intent == "general_query"
    assert r.tools_executed == () or len(r.tools_executed) == 0
    assert "¿En qué puedo ayudarte?" in r.response_text or "hola" in r.response_text.lower()
